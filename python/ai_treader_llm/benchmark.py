"""Reproducible, payload-safe endpoint performance benchmarks."""
from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class BenchmarkError(ValueError):
    """Raised when a workload or endpoint response is unusable."""


def iso_z() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(0, math.ceil(fraction * len(ordered)) - 1)
    return round(ordered[rank], 3)


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    successful = [item for item in records if item.get("ok")]
    wall = [float(item["wall_ms"]) for item in successful]
    predicted_rate = [
        float(item["predicted_tokens_per_second"])
        for item in successful
        if isinstance(item.get("predicted_tokens_per_second"), (int, float))
    ]
    prompt_rate = [
        float(item["prompt_tokens_per_second"])
        for item in successful
        if isinstance(item.get("prompt_tokens_per_second"), (int, float))
    ]
    return {
        "requests": len(records),
        "succeeded": len(successful),
        "failed": len(records) - len(successful),
        "success_rate": round(len(successful) / len(records), 4) if records else None,
        "latency_ms": {"p50": percentile(wall, 0.50), "p95": percentile(wall, 0.95), "max": max(wall, default=None)},
        "generation_tokens_per_second": {
            "p50": percentile(predicted_rate, 0.50),
            "p95": percentile(predicted_rate, 0.95),
            "min": min(predicted_rate, default=None),
        },
        "prompt_tokens_per_second": {
            "p50": percentile(prompt_rate, 0.50),
            "p95": percentile(prompt_rate, 0.95),
            "min": min(prompt_rate, default=None),
        },
        "prompt_tokens": sum(int(item.get("prompt_tokens", 0)) for item in successful),
        "prompt_tokens_processed": sum(int(item.get("prompt_tokens_processed", 0)) for item in successful),
        "prompt_tokens_cached": sum(int(item.get("prompt_tokens_cached", 0)) for item in successful),
        "generated_tokens": sum(int(item.get("generated_tokens", 0)) for item in successful),
        "errors": sorted({str(item["error"]) for item in records if item.get("error")}),
    }


def load_workload(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise BenchmarkError(f"invalid workload JSON: {error}") from error
    if not isinstance(value, dict):
        raise BenchmarkError("workload must be an object")
    allowed = {"schema_version", "workload_id", "model", "seed", "warmup_requests", "phases"}
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise BenchmarkError(f"unknown workload fields: {', '.join(unknown)}")
    if value.get("schema_version") != "1":
        raise BenchmarkError("workload schema_version must be 1")
    if not isinstance(value.get("workload_id"), str) or not value["workload_id"].strip():
        raise BenchmarkError("workload_id is required")
    if not isinstance(value.get("model"), str) or not value["model"].strip():
        raise BenchmarkError("model is required")
    if not isinstance(value.get("seed"), int) or isinstance(value.get("seed"), bool):
        raise BenchmarkError("seed must be an integer")
    warmup = value.get("warmup_requests")
    if not isinstance(warmup, int) or isinstance(warmup, bool) or warmup < 0:
        raise BenchmarkError("warmup_requests must be a non-negative integer")
    phases = value.get("phases")
    if not isinstance(phases, dict) or set(phases) != {"latency", "context", "concurrency", "sustained"}:
        raise BenchmarkError("phases must contain latency, context, concurrency, and sustained")
    return value, hashlib.sha256(raw).hexdigest()


class StatusWriter:
    def __init__(self, path: Path | None, run_id: str, workload_id: str):
        self.path = path
        self.run_id = run_id
        self.workload_id = workload_id

    def publish(
        self,
        status: str,
        stage: str,
        completed: int,
        total: int,
        message: str,
        failures: int = 0,
    ) -> None:
        if self.path is None:
            return
        value = {
            "schema_version": "1",
            "updated_at": iso_z(),
            "run_id": self.run_id,
            "workload_id": self.workload_id,
            "status": status,
            "stage": stage,
            "progress": {"completed": completed, "total": max(1, total)},
            "failures": failures,
            "message": message[:200],
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + ".tmp")
        temporary.write_text(json.dumps(value, separators=(",", ":"), allow_nan=False), encoding="utf-8")
        os.replace(temporary, self.path)


class TelemetrySampler:
    def __init__(self, url: str | None, interval: float = 1.0):
        self.url = url
        self.interval = interval
        self.samples: list[dict[str, Any]] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self.url is None:
            return
        self._thread = threading.Thread(target=self._run, name="benchmark-telemetry", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self.interval + 2)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                with urlopen(self.url, timeout=4) as response:
                    snapshot = json.load(response)
                gpu = (snapshot.get("gpu", {}).get("devices") or [{}])[0]
                metrics = snapshot.get("inference", {}).get("metrics", {})
                self.samples.append({
                    "observed_at": snapshot.get("observed_at"),
                    "gpu_utilization_percent": gpu.get("utilization_gpu_percent"),
                    "vram_used_mib": gpu.get("memory_used_mib"),
                    "temperature_c": gpu.get("temperature_c"),
                    "power_draw_w": gpu.get("power_draw_w"),
                    "host_cpu_percent": snapshot.get("host", {}).get("cpu_percent"),
                    "host_memory_percent": snapshot.get("host", {}).get("memory", {}).get("percent"),
                    "active_requests": snapshot.get("inference", {}).get("active_requests"),
                    "deferred_requests": metrics.get("llamacpp:requests_deferred"),
                    "container_restarts": snapshot.get("container", {}).get("restart_count"),
                })
            except (OSError, URLError, ValueError, json.JSONDecodeError, TypeError):
                self.samples.append({"observed_at": iso_z(), "error": "telemetry_unavailable"})
            self._stop.wait(self.interval)

    def summary(self) -> dict[str, Any]:
        def maximum(key: str) -> float | None:
            values = [float(row[key]) for row in self.samples if isinstance(row.get(key), (int, float))]
            return max(values, default=None)

        def minimum(key: str) -> float | None:
            values = [float(row[key]) for row in self.samples if isinstance(row.get(key), (int, float))]
            return min(values, default=None)

        return {
            "samples": len(self.samples),
            "unavailable_samples": sum(1 for row in self.samples if row.get("error")),
            "peak_gpu_utilization_percent": maximum("gpu_utilization_percent"),
            "peak_vram_used_mib": maximum("vram_used_mib"),
            "peak_temperature_c": maximum("temperature_c"),
            "peak_power_draw_w": maximum("power_draw_w"),
            "peak_host_cpu_percent": maximum("host_cpu_percent"),
            "peak_host_memory_percent": maximum("host_memory_percent"),
            "peak_active_requests": maximum("active_requests"),
            "peak_deferred_requests": maximum("deferred_requests"),
            "minimum_container_restarts": minimum("container_restarts"),
            "maximum_container_restarts": maximum("container_restarts"),
        }


class Endpoint:
    def __init__(self, base_url: str, model: str, seed: int, timeout: float):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.seed = seed
        self.timeout = timeout

    def completion(self, request_body: dict[str, Any]) -> dict[str, Any]:
        payload = {"model": self.model, "seed": self.seed, **request_body}
        started = time.monotonic()
        request = Request(
            self.base_url + "/v1/chat/completions",
            data=json.dumps(payload, separators=(",", ":"), allow_nan=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                value = json.load(response)
            wall_ms = round((time.monotonic() - started) * 1000, 3)
            choice = value.get("choices", [{}])[0]
            content = choice.get("message", {}).get("content")
            timings = value.get("timings") if isinstance(value.get("timings"), dict) else {}
            usage = value.get("usage") if isinstance(value.get("usage"), dict) else {}
            prompt_details = usage.get("prompt_tokens_details") if isinstance(usage.get("prompt_tokens_details"), dict) else {}
            if not isinstance(content, str) or not content.strip():
                raise BenchmarkError("empty_completion")
            return {
                "ok": True,
                "wall_ms": wall_ms,
                "finish_reason": choice.get("finish_reason"),
                "prompt_tokens": usage.get("prompt_tokens", timings.get("prompt_n")),
                "prompt_tokens_processed": timings.get("prompt_n"),
                "prompt_tokens_cached": prompt_details.get("cached_tokens", timings.get("cache_n", 0)),
                "generated_tokens": timings.get("predicted_n", usage.get("completion_tokens")),
                "prompt_tokens_per_second": timings.get("prompt_per_second"),
                "predicted_tokens_per_second": timings.get("predicted_per_second"),
            }
        except HTTPError as error:
            return {
                "ok": False,
                "wall_ms": round((time.monotonic() - started) * 1000, 3),
                "error": "http_error",
                "http_status": error.code,
            }
        except (OSError, URLError, TimeoutError) as error:
            name = "timeout" if isinstance(error, TimeoutError) else "endpoint_error"
            return {"ok": False, "wall_ms": round((time.monotonic() - started) * 1000, 3), "error": name}
        except (ValueError, KeyError, TypeError, json.JSONDecodeError, BenchmarkError) as error:
            return {"ok": False, "wall_ms": round((time.monotonic() - started) * 1000, 3), "error": str(error)}


def _request(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise BenchmarkError(f"{name}.request must be an object")
    return value


def _positive_int(value: object, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise BenchmarkError(f"{name} must be a positive integer")
    return value


def run_benchmark(
    workload_path: Path,
    base_url: str,
    telemetry_url: str | None,
    timeout: float,
    status_file: Path | None = None,
) -> dict[str, Any]:
    workload, workload_hash = load_workload(workload_path)
    run_id = str(uuid.uuid4())
    status = StatusWriter(status_file, run_id, workload["workload_id"])
    endpoint = Endpoint(base_url, workload["model"], workload["seed"], timeout)
    telemetry = TelemetrySampler(telemetry_url)
    started_at = iso_z()
    started = time.monotonic()
    report: dict[str, Any] = {
        "schema_version": "1",
        "run_id": run_id,
        "workload_id": workload["workload_id"],
        "workload_sha256": workload_hash,
        "model": workload["model"],
        "seed": workload["seed"],
        "endpoint": base_url,
        "started_at": started_at,
        "phases": {},
    }
    failures = 0
    telemetry.start()
    try:
        warmup_count = workload["warmup_requests"]
        latency = workload["phases"]["latency"]
        latency_request = _request(latency.get("request"), "latency")
        status.publish("running", "warmup", 0, max(1, warmup_count), "Warming model and prompt cache")
        warmup = []
        for index in range(warmup_count):
            warmup.append(endpoint.completion(latency_request))
            status.publish("running", "warmup", index + 1, max(1, warmup_count), "Warming model and prompt cache")
        report["warmup"] = summarize(warmup)
        failures += sum(1 for record in warmup if not record["ok"])

        iterations = _positive_int(latency.get("iterations"), "latency.iterations")
        latency_records = []
        for index in range(iterations):
            status.publish("running", "latency", index, iterations, "Measuring representative serial latency", failures)
            record = endpoint.completion(latency_request)
            failures += int(not record["ok"])
            latency_records.append(record)
        report["phases"]["latency"] = {"summary": summarize(latency_records), "requests": latency_records}

        context = workload["phases"]["context"]
        word_counts = context.get("input_word_counts")
        if not isinstance(word_counts, list) or not word_counts:
            raise BenchmarkError("context.input_word_counts must be a non-empty array")
        context_request = _request(context.get("request"), "context")
        context_records = []
        for index, raw_count in enumerate(word_counts):
            count = _positive_int(raw_count, "context input word count")
            status.publish("running", "context", index, len(word_counts), "Sweeping synthetic context sizes", failures)
            request_body = dict(context_request)
            request_body["messages"] = [{"role": "user", "content": ("evidence " * count) + "\nReply READY."}]
            record = endpoint.completion(request_body)
            record["input_word_count"] = count
            context_records.append(record)
        successful_contexts = [record for record in context_records if record["ok"]]
        failed_contexts = [record for record in context_records if not record["ok"]]
        report["phases"]["context"] = {
            "summary": summarize(context_records),
            "largest_successful_input_word_count": max(
                (record["input_word_count"] for record in successful_contexts), default=None
            ),
            "largest_successful_prompt_tokens": max(
                (
                    int(record["prompt_tokens"])
                    for record in successful_contexts
                    if isinstance(record.get("prompt_tokens"), int)
                ),
                default=None,
            ),
            "first_failed_input_word_count": min(
                (record["input_word_count"] for record in failed_contexts), default=None
            ),
            "requests": context_records,
        }

        concurrency = workload["phases"]["concurrency"]
        levels = concurrency.get("levels")
        if not isinstance(levels, list) or not levels:
            raise BenchmarkError("concurrency.levels must be a non-empty array")
        per_level = _positive_int(concurrency.get("requests_per_level"), "concurrency.requests_per_level")
        concurrency_request = _request(concurrency.get("request"), "concurrency")
        level_reports = []
        for level_index, raw_level in enumerate(levels):
            level = _positive_int(raw_level, "concurrency level")
            status.publish("running", "concurrency", level_index, len(levels), f"Measuring concurrency level {level}", failures)
            wall_started = time.monotonic()
            with ThreadPoolExecutor(max_workers=level) as pool:
                futures = [pool.submit(endpoint.completion, concurrency_request) for _ in range(per_level)]
                records = [future.result() for future in as_completed(futures)]
            failures += sum(1 for record in records if not record["ok"])
            level_reports.append({
                "concurrency": level,
                "wall_ms": round((time.monotonic() - wall_started) * 1000, 3),
                "summary": summarize(records),
                "requests": records,
            })
        report["phases"]["concurrency"] = level_reports

        sustained = workload["phases"]["sustained"]
        duration = _positive_int(sustained.get("duration_seconds"), "sustained.duration_seconds")
        sustained_request = _request(sustained.get("request"), "sustained")
        sustained_records = []
        sustained_started = time.monotonic()
        while time.monotonic() - sustained_started < duration:
            elapsed = min(duration, int(time.monotonic() - sustained_started))
            status.publish("running", "sustained", elapsed, duration, "Running sustained serial load", failures)
            record = endpoint.completion(sustained_request)
            failures += int(not record["ok"])
            sustained_records.append(record)
        actual_duration = round(time.monotonic() - sustained_started, 3)
        report["phases"]["sustained"] = {
            "requested_duration_seconds": duration,
            "actual_duration_seconds": actual_duration,
            "summary": summarize(sustained_records),
            "requests": sustained_records,
        }
        report["status"] = "succeeded" if failures == 0 else "completed_with_failures"
        status.publish("succeeded" if failures == 0 else "failed", "complete", 1, 1, "Benchmark complete", failures)
    except BaseException:
        status.publish("failed", "complete", 1, 1, "Benchmark stopped before completion", failures + 1)
        raise
    finally:
        telemetry.stop()
        report["completed_at"] = iso_z()
        report["duration_seconds"] = round(time.monotonic() - started, 3)
        report["telemetry"] = telemetry.summary()
        report["telemetry_samples"] = telemetry.samples
    return report


def write_report(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _health_ready(base_url: str, timeout: float) -> bool:
    try:
        with urlopen(base_url.rstrip("/") + "/health", timeout=timeout) as response:
            value = json.load(response)
        return isinstance(value, dict) and value.get("status") == "ok"
    except (OSError, URLError, TimeoutError, ValueError, json.JSONDecodeError):
        return False


def measure_recovery(
    base_url: str,
    ssh_host: str,
    container: str,
    model: str,
    timeout: float = 120,
    poll_interval: float = 0.05,
) -> dict[str, Any]:
    if not _health_ready(base_url, 3):
        raise BenchmarkError("endpoint must be healthy before recovery measurement")
    started_at = iso_z()
    started = time.monotonic()
    process = subprocess.Popen(
        [
            "ssh",
            "-o", "ClearAllForwardings=yes",
            "-o", "BatchMode=yes",
            ssh_host,
            "docker", "restart", container,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    unavailable_after_ms = None
    ready_after_ms = None
    deadline = started + timeout
    while time.monotonic() < deadline:
        ready = _health_ready(base_url, min(0.5, poll_interval * 4))
        elapsed_ms = round((time.monotonic() - started) * 1000, 3)
        if not ready and unavailable_after_ms is None:
            unavailable_after_ms = elapsed_ms
        if ready and unavailable_after_ms is not None and process.poll() is not None:
            ready_after_ms = elapsed_ms
            break
        time.sleep(poll_interval)
    try:
        return_code = process.wait(timeout=max(1, deadline - time.monotonic()))
    except subprocess.TimeoutExpired as error:
        process.kill()
        raise BenchmarkError("container restart command timed out") from error
    stderr = (process.stderr.read(4096) if process.stderr is not None else "").strip()
    if return_code != 0:
        raise BenchmarkError(f"container restart failed with exit {return_code}: {stderr[:200]}")
    if unavailable_after_ms is None:
        raise BenchmarkError("restart completed without observing endpoint unavailability")
    if ready_after_ms is None:
        raise BenchmarkError("endpoint did not recover before timeout")
    endpoint = Endpoint(base_url, model, 20261001, timeout)
    completion = endpoint.completion({
        "temperature": 0,
        "max_tokens": 32,
        "chat_template_kwargs": {"enable_thinking": False},
        "messages": [{"role": "user", "content": "Reply with READY."}],
    })
    completed_at = iso_z()
    return {
        "schema_version": "1",
        "started_at": started_at,
        "completed_at": completed_at,
        "endpoint": base_url,
        "ssh_host": ssh_host,
        "container": container,
        "model": model,
        "offline_observed": True,
        "unavailable_after_ms": unavailable_after_ms,
        "ready_after_ms": ready_after_ms,
        "first_completion_after_restart_ms": round((time.monotonic() - started) * 1000, 3),
        "completion": completion,
    }
