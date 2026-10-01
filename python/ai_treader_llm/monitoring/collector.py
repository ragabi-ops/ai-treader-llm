"""Collect bounded, sanitized host and inference telemetry.

The dashboard is intentionally observational. It never returns prompts, model
responses, environment variables, Docker logs, credentials, or arbitrary files.
Future pipeline/training producers may atomically publish the small allowlisted
status documents described in docs/OBSERVABILITY.md.
"""
from __future__ import annotations

import json
import math
import os
import platform
import shutil
import socket
import subprocess
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

PIPELINE_STATUSES = {"idle", "queued", "running", "succeeded", "failed", "cancelled"}
PIPELINE_STAGES = {
    "idle",
    "collecting",
    "validating_context",
    "inference",
    "validating_output",
    "persisting",
    "evaluating",
    "complete",
}
TRAINING_STATUSES = {"idle", "queued", "running", "succeeded", "failed", "cancelled"}
TRAINING_STAGES = {
    "idle",
    "preparing",
    "loading_model",
    "training",
    "checkpointing",
    "exporting",
    "evaluating",
    "complete",
}
BENCHMARK_STATUSES = {"running", "succeeded", "failed", "cancelled"}
BENCHMARK_STAGES = {"warmup", "latency", "context", "concurrency", "sustained", "recovery", "complete"}
MAX_STATUS_BYTES = 64 * 1024


def iso_z(value: datetime | None = None) -> str:
    value = value or datetime.now(timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_rfc3339(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.endswith("Z"):
        return None
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return None


def bounded_text(value: object, maximum: int = 160) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.split())
    if not normalized:
        return None
    return normalized[:maximum]


def finite_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def percent(used: int | float, total: int | float) -> float | None:
    if total <= 0:
        return None
    return round(float(used) * 100.0 / float(total), 1)


def parse_proc_stat(text: str) -> tuple[int, int]:
    line = next((line for line in text.splitlines() if line.startswith("cpu ")), "")
    parts = line.split()[1:]
    if len(parts) < 4:
        raise ValueError("missing aggregate cpu counters")
    values = [int(value) for value in parts]
    idle = values[3] + (values[4] if len(values) > 4 else 0)
    return sum(values), idle


def cpu_percent(previous: tuple[int, int] | None, current: tuple[int, int]) -> float | None:
    if previous is None:
        return None
    total_delta = current[0] - previous[0]
    idle_delta = current[1] - previous[1]
    if total_delta <= 0:
        return None
    return round(max(0.0, min(100.0, (total_delta - idle_delta) * 100.0 / total_delta)), 1)


def parse_meminfo(text: str) -> dict[str, int]:
    values: dict[str, int] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, raw = line.split(":", 1)
        parts = raw.strip().split()
        if not parts:
            continue
        multiplier = 1024 if len(parts) > 1 and parts[1].lower() == "kb" else 1
        try:
            values[key] = int(parts[0]) * multiplier
        except ValueError:
            continue
    return values


def parse_nvidia_csv(text: str) -> list[dict[str, Any]]:
    keys = (
        "index",
        "name",
        "uuid",
        "utilization_gpu_percent",
        "utilization_memory_percent",
        "memory_used_mib",
        "memory_total_mib",
        "temperature_c",
        "power_draw_w",
        "power_limit_w",
        "clock_sm_mhz",
    )
    integers = {0, 3, 4, 5, 6, 7, 10}
    decimals = {8, 9}
    records: list[dict[str, Any]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        parts = [part.strip() for part in line.split(",")]
        if len(parts) != len(keys):
            raise ValueError("unexpected nvidia-smi field count")
        record: dict[str, Any] = {}
        for index, (key, value) in enumerate(zip(keys, parts, strict=True)):
            if index in integers:
                record[key] = int(value)
            elif index in decimals:
                record[key] = round(float(value), 2)
            else:
                record[key] = value
        record["memory_percent"] = percent(record["memory_used_mib"], record["memory_total_mib"])
        record["power_percent"] = percent(record["power_draw_w"], record["power_limit_w"])
        records.append(record)
    return records


def parse_prometheus(text: str) -> dict[str, float]:
    metrics: dict[str, float] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or " " not in line:
            continue
        name, raw = line.rsplit(None, 1)
        if "{" in name:
            name = name.split("{", 1)[0]
        try:
            value = float(raw)
        except ValueError:
            continue
        if math.isfinite(value):
            metrics[name] = value
    return metrics


def _read_status(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        if not path.exists():
            return None, "telemetry_not_connected"
        if path.stat().st_size > MAX_STATUS_BYTES:
            return None, "status_file_too_large"
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            return None, "invalid_status_document"
        return value, None
    except (OSError, json.JSONDecodeError):
        return None, "invalid_status_document"


def _safe_progress(value: object) -> dict[str, int] | None:
    if not isinstance(value, dict):
        return None
    completed, total = value.get("completed"), value.get("total")
    if isinstance(completed, bool) or isinstance(total, bool):
        return None
    if not isinstance(completed, int) or not isinstance(total, int) or total <= 0:
        return None
    if completed < 0 or completed > total:
        return None
    return {"completed": completed, "total": total, "percent": round(completed * 100 / total)}


def sanitize_pipeline(value: dict[str, Any] | None, error: str | None, now: datetime) -> dict[str, Any]:
    if value is None:
        return {"connected": False, "status": "unavailable", "stage": "unavailable", "reason": error}
    if value.get("schema_version") != "1":
        return {"connected": False, "status": "unavailable", "stage": "unavailable", "reason": "unsupported_schema"}
    status, stage = value.get("status"), value.get("stage")
    updated = parse_rfc3339(value.get("updated_at"))
    if status not in PIPELINE_STATUSES or stage not in PIPELINE_STAGES or updated is None:
        return {"connected": False, "status": "unavailable", "stage": "unavailable", "reason": "invalid_status_document"}
    age = max(0.0, (now - updated).total_seconds())
    work = value.get("work") if isinstance(value.get("work"), dict) else {}
    safe_work: dict[str, Any] = {}
    for key in ("symbol", "horizon", "as_of_timestamp", "replay_mode"):
        safe = bounded_text(work.get(key), 80)
        if safe is not None:
            safe_work[key] = safe
    listing_id = work.get("listing_id")
    if isinstance(listing_id, int) and not isinstance(listing_id, bool) and listing_id > 0:
        safe_work["listing_id"] = listing_id
    attempt = value.get("attempt")
    return {
        "connected": True,
        "status": status,
        "stage": stage,
        "updated_at": iso_z(updated),
        "age_seconds": round(age, 1),
        "stale": status in {"queued", "running"} and age > 15,
        "run_id": bounded_text(value.get("run_id"), 100),
        "attempt": attempt if isinstance(attempt, int) and not isinstance(attempt, bool) and attempt > 0 else None,
        "progress": _safe_progress(value.get("progress")),
        "work": safe_work,
        "message": bounded_text(value.get("message"), 200),
    }


def sanitize_training(value: dict[str, Any] | None, error: str | None, now: datetime) -> dict[str, Any]:
    if value is None:
        return {"connected": False, "status": "unavailable", "stage": "unavailable", "reason": error}
    if value.get("schema_version") != "1":
        return {"connected": False, "status": "unavailable", "stage": "unavailable", "reason": "unsupported_schema"}
    status, stage = value.get("status"), value.get("stage")
    updated = parse_rfc3339(value.get("updated_at"))
    if status not in TRAINING_STATUSES or stage not in TRAINING_STAGES or updated is None:
        return {"connected": False, "status": "unavailable", "stage": "unavailable", "reason": "invalid_status_document"}
    age = max(0.0, (now - updated).total_seconds())
    result: dict[str, Any] = {
        "connected": True,
        "status": status,
        "stage": stage,
        "updated_at": iso_z(updated),
        "age_seconds": round(age, 1),
        "stale": status in {"queued", "running"} and age > 15,
        "run_id": bounded_text(value.get("run_id"), 100),
        "dataset_id": bounded_text(value.get("dataset_id"), 100),
        "progress": _safe_progress(value.get("progress")),
        "message": bounded_text(value.get("message"), 200),
    }
    for key in ("epoch", "total_epochs", "step", "total_steps", "eta_seconds"):
        number = finite_number(value.get(key))
        result[key] = number
    result["loss"] = finite_number(value.get("loss"))
    return result


def sanitize_benchmark(value: dict[str, Any] | None, error: str | None, now: datetime) -> dict[str, Any]:
    if value is None:
        return {"connected": False, "status": "unavailable", "stage": "unavailable", "reason": error}
    if value.get("schema_version") != "1":
        return {"connected": False, "status": "unavailable", "stage": "unavailable", "reason": "unsupported_schema"}
    status, stage = value.get("status"), value.get("stage")
    updated = parse_rfc3339(value.get("updated_at"))
    if status not in BENCHMARK_STATUSES or stage not in BENCHMARK_STAGES or updated is None:
        return {"connected": False, "status": "unavailable", "stage": "unavailable", "reason": "invalid_status_document"}
    failures = value.get("failures")
    if not isinstance(failures, int) or isinstance(failures, bool) or failures < 0:
        failures = None
    age = max(0.0, (now - updated).total_seconds())
    return {
        "connected": True,
        "status": status,
        "stage": stage,
        "updated_at": iso_z(updated),
        "age_seconds": round(age, 1),
        "stale": status == "running" and age > 15,
        "run_id": bounded_text(value.get("run_id"), 100),
        "workload_id": bounded_text(value.get("workload_id"), 120),
        "progress": _safe_progress(value.get("progress")),
        "failures": failures,
        "message": bounded_text(value.get("message"), 200),
    }


class Collector:
    def __init__(
        self,
        root: Path,
        data_root: Path = Path("/data"),
        inference_url: str = "http://127.0.0.1:8080",
        container_name: str = "ai-treader-llm-inference-1",
        cache_seconds: float = 1.0,
    ):
        self.root = root.resolve()
        self.data_root = data_root.resolve()
        self.inference_url = inference_url.rstrip("/")
        self.container_name = container_name
        self.cache_seconds = cache_seconds
        self._lock = threading.Lock()
        self._last_snapshot: dict[str, Any] | None = None
        self._last_snapshot_at = 0.0
        self._last_cpu: tuple[int, int] | None = None
        self._slow_cache: dict[str, Any] | None = None
        self._slow_cache_at = 0.0
        self._events: deque[dict[str, Any]] = deque(maxlen=80)
        self._event_state: dict[str, object] = {}

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            monotonic = time.monotonic()
            if self._last_snapshot is not None and monotonic - self._last_snapshot_at < self.cache_seconds:
                return self._last_snapshot
            value = self._collect(monotonic)
            self._last_snapshot = value
            self._last_snapshot_at = monotonic
            return value

    def _run(self, args: list[str], timeout: float = 2.0) -> tuple[str | None, str | None]:
        try:
            result = subprocess.run(args, check=False, capture_output=True, text=True, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired):
            return None, "command_unavailable"
        if result.returncode != 0:
            return None, "command_failed"
        return result.stdout.strip(), None

    def _json_url(self, path: str, timeout: float = 1.5) -> tuple[Any | None, str | None, float | None]:
        started = time.monotonic()
        try:
            with urlopen(self.inference_url + path, timeout=timeout) as response:
                value = json.load(response)
            return value, None, round((time.monotonic() - started) * 1000, 1)
        except (OSError, URLError, ValueError, json.JSONDecodeError):
            return None, "endpoint_unavailable", None

    def _text_url(self, path: str, timeout: float = 1.5) -> tuple[str | None, str | None]:
        try:
            with urlopen(self.inference_url + path, timeout=timeout) as response:
                return response.read(256 * 1024).decode("utf-8"), None
        except (OSError, URLError, UnicodeDecodeError):
            return None, "endpoint_unavailable"

    def _host(self) -> dict[str, Any]:
        try:
            current_cpu = parse_proc_stat(Path("/proc/stat").read_text())
            utilization = cpu_percent(self._last_cpu, current_cpu)
            self._last_cpu = current_cpu
        except (OSError, ValueError):
            utilization = None
        try:
            memory = parse_meminfo(Path("/proc/meminfo").read_text())
        except OSError:
            memory = {}
        total = memory.get("MemTotal", 0)
        available = memory.get("MemAvailable", 0)
        swap_total = memory.get("SwapTotal", 0)
        swap_free = memory.get("SwapFree", 0)
        try:
            uptime = float(Path("/proc/uptime").read_text().split()[0])
        except (OSError, ValueError, IndexError):
            uptime = None
        try:
            loads = [round(value, 2) for value in os.getloadavg()]
        except OSError:
            loads = []
        network_rx = network_tx = 0
        try:
            for line in Path("/proc/net/dev").read_text().splitlines()[2:]:
                interface, raw = line.split(":", 1)
                if interface.strip() == "lo":
                    continue
                fields = raw.split()
                network_rx += int(fields[0])
                network_tx += int(fields[8])
        except (OSError, ValueError, IndexError):
            network_rx = network_tx = 0
        return {
            "hostname": socket.gethostname(),
            "kernel": platform.release(),
            "architecture": platform.machine(),
            "cpu_count": os.cpu_count(),
            "cpu_percent": utilization,
            "load_average": loads,
            "uptime_seconds": round(uptime) if uptime is not None else None,
            "memory": {
                "used_bytes": max(0, total - available),
                "available_bytes": available,
                "total_bytes": total,
                "percent": percent(total - available, total),
            },
            "swap": {
                "used_bytes": max(0, swap_total - swap_free),
                "total_bytes": swap_total,
                "percent": percent(swap_total - swap_free, swap_total),
            },
            "network": {"received_bytes": network_rx, "sent_bytes": network_tx},
        }

    def _storage(self) -> list[dict[str, Any]]:
        records = []
        for path in (Path("/"), self.data_root):
            try:
                usage = shutil.disk_usage(path)
                records.append({
                    "path": str(path),
                    "used_bytes": usage.used,
                    "free_bytes": usage.free,
                    "total_bytes": usage.total,
                    "percent": percent(usage.used, usage.total),
                })
            except OSError:
                records.append({"path": str(path), "error": "unavailable"})
        return records

    def _gpu(self) -> dict[str, Any]:
        fields = (
            "index,name,uuid,utilization.gpu,utilization.memory,memory.used,memory.total,"
            "temperature.gpu,power.draw,power.limit,clocks.sm"
        )
        output, error = self._run(["nvidia-smi", f"--query-gpu={fields}", "--format=csv,noheader,nounits"])
        if output is None:
            return {"available": False, "error": error}
        try:
            return {"available": True, "devices": parse_nvidia_csv(output)}
        except (ValueError, TypeError):
            return {"available": False, "error": "unexpected_output"}

    def _container(self) -> dict[str, Any]:
        output, error = self._run(["docker", "inspect", self.container_name])
        if output is None:
            return {"available": False, "error": error}
        try:
            item = json.loads(output)[0]
            state = item.get("State", {})
            health = state.get("Health", {}) if isinstance(state.get("Health"), dict) else {}
            ports = item.get("NetworkSettings", {}).get("Ports", {})
            binding = None
            if isinstance(ports.get("8080/tcp"), list) and ports["8080/tcp"]:
                binding = ports["8080/tcp"][0]
            return {
                "available": True,
                "name": bounded_text(item.get("Name", "").lstrip("/"), 100),
                "status": state.get("Status"),
                "running": bool(state.get("Running")),
                "health": health.get("Status"),
                "started_at": state.get("StartedAt"),
                "restart_count": item.get("RestartCount"),
                "image": bounded_text(item.get("Config", {}).get("Image"), 200),
                "binding": binding,
            }
        except (KeyError, IndexError, TypeError, json.JSONDecodeError):
            return {"available": False, "error": "unexpected_output"}

    def _inference(self) -> dict[str, Any]:
        health, health_error, latency = self._json_url("/health")
        models, models_error, _ = self._json_url("/v1/models")
        slots, slots_error, _ = self._json_url("/slots")
        metrics_text, metrics_error = self._text_url("/metrics")
        safe_slots = []
        if isinstance(slots, list):
            for item in slots:
                if not isinstance(item, dict):
                    continue
                safe_slots.append({
                    "id": item.get("id") if isinstance(item.get("id"), int) else None,
                    "task_id": item.get("id_task") if isinstance(item.get("id_task"), int) else None,
                    "processing": bool(item.get("is_processing")),
                    "context_size": item.get("n_ctx") if isinstance(item.get("n_ctx"), int) else None,
                    "prompt_tokens": item.get("n_prompt_tokens") if isinstance(item.get("n_prompt_tokens"), int) else None,
                    "prompt_tokens_processed": item.get("n_prompt_tokens_processed") if isinstance(item.get("n_prompt_tokens_processed"), int) else None,
                    "decoded_tokens": item.get("n_decoded") if isinstance(item.get("n_decoded"), int) else None,
                })
        model = None
        if isinstance(models, dict) and isinstance(models.get("data"), list) and models["data"]:
            candidate = models["data"][0]
            if isinstance(candidate, dict):
                meta = candidate.get("meta") if isinstance(candidate.get("meta"), dict) else {}
                model = {
                    "id": bounded_text(candidate.get("id"), 100),
                    "format": bounded_text(meta.get("format"), 30),
                    "quantization": bounded_text(meta.get("ftype"), 80),
                    "parameters": meta.get("n_params") if isinstance(meta.get("n_params"), int) else None,
                    "context_size": meta.get("n_ctx") if isinstance(meta.get("n_ctx"), int) else None,
                    "training_context_size": meta.get("n_ctx_train") if isinstance(meta.get("n_ctx_train"), int) else None,
                }
        metrics = parse_prometheus(metrics_text) if metrics_text is not None else {}
        return {
            "health": "ready" if isinstance(health, dict) and health.get("status") == "ok" else "offline",
            "health_error": health_error,
            "latency_ms": latency,
            "model": model,
            "models_error": models_error,
            "active_requests": sum(1 for slot in safe_slots if slot["processing"]),
            "slots": safe_slots,
            "slots_error": slots_error,
            "metrics_available": metrics_error is None,
            "metrics": metrics,
        }

    def _slow(self, monotonic: float) -> dict[str, Any]:
        if self._slow_cache is not None and monotonic - self._slow_cache_at < 30:
            return self._slow_cache
        os_name = None
        try:
            values = {}
            for line in Path("/etc/os-release").read_text().splitlines():
                if "=" in line:
                    key, value = line.split("=", 1)
                    values[key] = value.strip().strip('"')
            os_name = values.get("PRETTY_NAME")
        except OSError:
            pass
        commit, _ = self._run(["git", "-C", str(self.root), "rev-parse", "--short", "HEAD"])
        dirty_output, dirty_error = self._run(["git", "-C", str(self.root), "status", "--porcelain"])
        docker_version, _ = self._run(["docker", "version", "--format", "{{.Server.Version}}"])
        compose_version, _ = self._run(["docker", "compose", "version", "--short"])
        model_manifest = None
        try:
            manifests = sorted((self.data_root / "models").glob("*.manifest.json"))
            if manifests:
                raw = json.loads(manifests[0].read_text())
                model_manifest = {
                    "repository": bounded_text(raw.get("repository"), 120),
                    "revision": bounded_text(raw.get("revision"), 64),
                    "filename": bounded_text(raw.get("filename"), 160),
                    "sha256": bounded_text(raw.get("sha256"), 64),
                    "bytes": raw.get("bytes") if isinstance(raw.get("bytes"), int) else None,
                    "verified_at": bounded_text(raw.get("verified_at"), 60),
                }
        except (OSError, json.JSONDecodeError):
            pass
        runtime_image = None
        try:
            for line in (self.root / "configs/runtime.lock.env").read_text().splitlines():
                if line.startswith("LLAMA_IMAGE="):
                    runtime_image = bounded_text(line.split("=", 1)[1], 220)
        except OSError:
            pass
        self._slow_cache = {
            "os": os_name,
            "repository_commit": commit,
            "repository_dirty": None if dirty_error else bool(dirty_output),
            "docker_version": docker_version,
            "compose_version": compose_version,
            "runtime_image": runtime_image,
            "model_artifact": model_manifest,
        }
        self._slow_cache_at = monotonic
        return self._slow_cache

    def _event(self, now: str, level: str, category: str, message: str) -> None:
        self._events.appendleft({"timestamp": now, "level": level, "category": category, "message": message})

    def _record_events(self, snapshot: dict[str, Any]) -> None:
        now = snapshot["observed_at"]
        states = {
            "inference": snapshot["inference"]["health"],
            "requests": snapshot["inference"]["active_requests"],
            "container": snapshot["container"].get("health") or snapshot["container"].get("status"),
            "pipeline": (snapshot["pipeline"].get("status"), snapshot["pipeline"].get("stage")),
            "training": (snapshot["training"].get("status"), snapshot["training"].get("stage")),
            "benchmark": (snapshot["benchmark"].get("status"), snapshot["benchmark"].get("stage")),
        }
        if not self._event_state:
            self._event(now, "info", "monitor", "Dashboard telemetry collector started")
        messages = {
            "inference": lambda value: ("success" if value == "ready" else "error", "inference", f"Inference is {value}"),
            "requests": lambda value: ("info", "inference", f"Active inference requests: {value}"),
            "container": lambda value: ("success" if value == "healthy" else "warning", "runtime", f"Container state: {value}"),
            "pipeline": lambda value: ("info", "pipeline", f"Pipeline: {value[0]} / {value[1]}"),
            "training": lambda value: ("info", "training", f"Training: {value[0]} / {value[1]}"),
            "benchmark": lambda value: ("info", "benchmark", f"Benchmark: {value[0]} / {value[1]}"),
        }
        for key, value in states.items():
            if key in self._event_state and self._event_state[key] != value:
                level, category, message = messages[key](value)
                self._event(now, level, category, message)
            self._event_state[key] = value

    def _summary(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        reasons: list[str] = []
        status = "healthy"
        if snapshot["inference"]["health"] != "ready" or not snapshot["container"].get("running"):
            status = "offline"
            reasons.append("Inference is unavailable")
        if not snapshot["gpu"].get("available"):
            status = "offline" if status == "offline" else "degraded"
            reasons.append("GPU telemetry is unavailable")
        if not snapshot["pipeline"].get("connected"):
            status = "degraded" if status == "healthy" else status
            reasons.append("Pipeline telemetry producer is not connected")
        elif snapshot["pipeline"].get("stale"):
            status = "degraded" if status == "healthy" else status
            reasons.append("Pipeline telemetry is stale")
        if snapshot["training"].get("connected") and snapshot["training"].get("stale"):
            status = "degraded" if status == "healthy" else status
            reasons.append("Training telemetry is stale")
        if snapshot["benchmark"].get("connected") and snapshot["benchmark"].get("stale"):
            status = "degraded" if status == "healthy" else status
            reasons.append("Benchmark telemetry is stale")
        data_disk = next((item for item in snapshot["storage"] if item.get("path") == str(self.data_root)), None)
        if data_disk and isinstance(data_disk.get("percent"), (int, float)) and data_disk["percent"] >= 90:
            status = "degraded" if status == "healthy" else status
            reasons.append("Data disk usage is at least 90%")
        return {"status": status, "reasons": reasons}

    def _collect(self, monotonic: float) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        pipeline_raw, pipeline_error = _read_status(self.data_root / "status" / "pipeline.json")
        training_raw, training_error = _read_status(self.data_root / "status" / "training.json")
        benchmark_raw, benchmark_error = _read_status(self.data_root / "status" / "benchmark.json")
        snapshot = {
            "schema_version": "1",
            "observed_at": iso_z(now),
            "poll_interval_seconds": 2,
            "host": self._host(),
            "storage": self._storage(),
            "gpu": self._gpu(),
            "container": self._container(),
            "inference": self._inference(),
            "pipeline": sanitize_pipeline(pipeline_raw, pipeline_error, now),
            "training": sanitize_training(training_raw, training_error, now),
            "benchmark": sanitize_benchmark(benchmark_raw, benchmark_error, now),
            "deployment": self._slow(monotonic),
        }
        snapshot["summary"] = self._summary(snapshot)
        self._record_events(snapshot)
        snapshot["events"] = list(self._events)
        return snapshot
