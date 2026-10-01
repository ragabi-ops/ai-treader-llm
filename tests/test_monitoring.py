import json
import math
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from ai_treader_llm.monitoring.collector import (
    cpu_percent,
    parse_meminfo,
    parse_nvidia_csv,
    parse_proc_stat,
    parse_prometheus,
    sanitize_pipeline,
    sanitize_benchmark,
    sanitize_training,
)


class MonitoringParserTests(unittest.TestCase):
    def test_cpu_delta(self):
        previous = parse_proc_stat("cpu  100 0 40 860 0 0 0 0\n")
        current = parse_proc_stat("cpu  150 0 50 900 0 0 0 0\n")
        self.assertEqual(cpu_percent(previous, current), 60.0)
        self.assertIsNone(cpu_percent(current, current))

    def test_meminfo_units(self):
        parsed = parse_meminfo("MemTotal: 1024 kB\nMemAvailable: 256 kB\nSwapTotal: 0 kB\n")
        self.assertEqual(parsed["MemTotal"], 1024 * 1024)
        self.assertEqual(parsed["MemAvailable"], 256 * 1024)

    def test_nvidia_output(self):
        parsed = parse_nvidia_csv(
            "0, NVIDIA GeForce RTX 3080, GPU-id, 50, 4, 5120, 10240, 65, 200.50, 370.00, 1710\n"
        )
        self.assertEqual(parsed[0]["name"], "NVIDIA GeForce RTX 3080")
        self.assertEqual(parsed[0]["memory_percent"], 50.0)
        self.assertEqual(parsed[0]["power_draw_w"], 200.5)

    def test_prometheus_labels_are_collapsed(self):
        parsed = parse_prometheus(
            "# HELP tokens Tokens\nllamacpp:tokens_predicted_total 42\n"
            'llamacpp:requests_processing{model="safe"} 1\ninvalid NaN\n'
        )
        self.assertEqual(parsed["llamacpp:tokens_predicted_total"], 42)
        self.assertEqual(parsed["llamacpp:requests_processing"], 1)
        self.assertNotIn("invalid", parsed)


class MonitoringStatusTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 29, 20, 0, 10, tzinfo=timezone.utc)

    def test_pipeline_is_allowlisted_and_hides_prompt(self):
        value = {
            "schema_version": "1",
            "updated_at": "2026-09-29T20:00:05Z",
            "run_id": "run-1",
            "status": "running",
            "stage": "inference",
            "attempt": 2,
            "progress": {"completed": 4, "total": 10},
            "work": {
                "listing_id": 7,
                "symbol": "AAPL",
                "horizon": "1m",
                "as_of_timestamp": "2026-09-29T20:00:00Z",
                "replay_mode": "platform_replay",
                "raw_prompt": "must never escape",
            },
            "raw_prompt": "must never escape",
            "message": "Waiting for structured output",
        }
        result = sanitize_pipeline(value, None, self.now)
        self.assertTrue(result["connected"])
        self.assertFalse(result["stale"])
        self.assertEqual(result["progress"]["percent"], 40)
        self.assertNotIn("raw_prompt", json.dumps(result))

    def test_running_pipeline_becomes_stale(self):
        result = sanitize_pipeline(
            {
                "schema_version": "1",
                "updated_at": "2026-09-29T19:59:00Z",
                "status": "running",
                "stage": "collecting",
            },
            None,
            self.now,
        )
        self.assertTrue(result["stale"])

    def test_invalid_status_is_unavailable(self):
        result = sanitize_pipeline({"schema_version": "2"}, None, self.now)
        self.assertFalse(result["connected"])
        self.assertEqual(result["reason"], "unsupported_schema")

    def test_training_rejects_non_finite_metrics(self):
        value = {
            "schema_version": "1",
            "updated_at": "2026-09-29T20:00:05Z",
            "status": "running",
            "stage": "training",
            "loss": math.inf,
        }
        result = sanitize_training(value, None, self.now)
        self.assertTrue(result["connected"])
        self.assertIsNone(result["loss"])

    def test_benchmark_is_allowlisted_and_hides_payloads(self):
        result = sanitize_benchmark(
            {
                "schema_version": "1",
                "updated_at": "2026-09-29T20:00:05Z",
                "run_id": "bench-1",
                "workload_id": "endpoint-v1",
                "status": "running",
                "stage": "sustained",
                "progress": {"completed": 30, "total": 600},
                "failures": 0,
                "message": "Running sustained load",
                "prompt": "must not escape",
                "response": "must not escape",
            },
            None,
            self.now,
        )
        self.assertTrue(result["connected"])
        self.assertEqual(result["progress"]["percent"], 5)
        self.assertNotIn("prompt", json.dumps(result))
        self.assertNotIn("response", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
