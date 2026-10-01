import io
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from ai_treader_llm.benchmark import (
    BenchmarkError,
    StatusWriter,
    load_workload,
    percentile,
    measure_recovery,
    run_benchmark,
    summarize,
)


class FakeEndpointHandler(BaseHTTPRequestHandler):
    def log_message(self, _format, *_args):
        pass

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length))
        prompt_tokens = len(payload["messages"][-1]["content"].split())
        self._json({
            "choices": [{"finish_reason": "stop", "message": {"content": "READY"}}],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": 1,
                "prompt_tokens_details": {"cached_tokens": 0},
            },
            "timings": {
                "prompt_n": prompt_tokens,
                "predicted_n": 1,
                "prompt_per_second": 1000,
                "predicted_per_second": 100,
            },
        })

    def do_GET(self):  # noqa: N802
        self._json({
            "observed_at": "2026-10-01T00:00:00Z",
            "gpu": {"devices": [{
                "utilization_gpu_percent": 80,
                "memory_used_mib": 6000,
                "temperature_c": 60,
                "power_draw_w": 250,
            }]},
            "host": {"cpu_percent": 10, "memory": {"percent": 20}},
            "inference": {"active_requests": 1, "metrics": {"llamacpp:requests_deferred": 0}},
            "container": {"restart_count": 0},
        })

    def _json(self, value):
        body = json.dumps(value).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class BenchmarkSummaryTests(unittest.TestCase):
    def test_nearest_rank_percentiles_and_failures(self):
        records = [
            {
                "ok": True,
                "wall_ms": value,
                "prompt_tokens": 10,
                "prompt_tokens_processed": 4,
                "prompt_tokens_cached": 6,
                "generated_tokens": 5,
                "prompt_tokens_per_second": 100 + value,
                "predicted_tokens_per_second": 50 + value,
            }
            for value in (10, 20, 30, 40)
        ]
        records.append({"ok": False, "wall_ms": 1, "error": "http_error"})
        result = summarize(records)
        self.assertEqual(percentile([10, 20, 30, 40], 0.50), 20)
        self.assertEqual(result["latency_ms"]["p95"], 40)
        self.assertEqual(result["succeeded"], 4)
        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["prompt_tokens"], 40)
        self.assertEqual(result["prompt_tokens_processed"], 16)
        self.assertEqual(result["prompt_tokens_cached"], 24)
        self.assertEqual(result["generated_tokens"], 20)
        self.assertEqual(result["errors"], ["http_error"])

    def test_workload_rejects_unknown_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "workload.json"
            path.write_text(json.dumps({
                "schema_version": "1",
                "workload_id": "test",
                "model": "model",
                "seed": 1,
                "warmup_requests": 0,
                "phases": {"latency": {}, "context": {}, "concurrency": {}, "sustained": {}},
                "secret": "must be refused",
            }))
            with self.assertRaisesRegex(BenchmarkError, "unknown workload fields: secret"):
                load_workload(path)

    def test_status_writer_publishes_only_safe_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "benchmark.json"
            writer = StatusWriter(path, "run-1", "workload-1")
            writer.publish("running", "sustained", 10, 100, "Synthetic load", 2)
            value = json.loads(path.read_text())
            self.assertEqual(value["progress"], {"completed": 10, "total": 100})
            self.assertEqual(value["failures"], 2)
            self.assertNotIn("prompt", value)
            self.assertNotIn("response", value)

    def test_runner_executes_all_phases_without_recording_content(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), FakeEndpointHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                workload = root / "workload.json"
                request = {"messages": [{"role": "user", "content": "synthetic request"}], "max_tokens": 4}
                workload.write_text(json.dumps({
                    "schema_version": "1",
                    "workload_id": "test-v1",
                    "model": "test-model",
                    "seed": 1,
                    "warmup_requests": 1,
                    "phases": {
                        "latency": {"iterations": 2, "request": request},
                        "context": {"input_word_counts": [4], "request": {"max_tokens": 4}},
                        "concurrency": {"levels": [2], "requests_per_level": 2, "request": request},
                        "sustained": {"duration_seconds": 1, "request": request},
                    },
                }))
                base = f"http://127.0.0.1:{server.server_port}"
                report = run_benchmark(workload, base, base + "/status", 2, root / "status.json")
                self.assertEqual(report["status"], "succeeded")
                self.assertEqual(report["phases"]["latency"]["summary"]["succeeded"], 2)
                serialized = json.dumps(report)
                self.assertNotIn("synthetic request", serialized)
                self.assertNotIn("READY", serialized)
                self.assertGreaterEqual(report["telemetry"]["samples"], 1)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_recovery_observes_outage_then_completion(self):
        class FakeProcess:
            stderr = io.StringIO("")

            def poll(self):
                return 0

            def wait(self, timeout=None):
                return 0

        server = ThreadingHTTPServer(("127.0.0.1", 0), FakeEndpointHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            with patch("ai_treader_llm.benchmark.subprocess.Popen", return_value=FakeProcess()), patch(
                "ai_treader_llm.benchmark._health_ready", side_effect=[True, False, True]
            ):
                result = measure_recovery(base, "test-host", "test-container", "test-model", poll_interval=0)
            self.assertTrue(result["offline_observed"])
            self.assertTrue(result["completion"]["ok"])
            self.assertNotIn("READY", json.dumps(result))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
