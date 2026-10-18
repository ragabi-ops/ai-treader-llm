import copy
import gzip
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from ai_treader_llm.contracts import ContractError, Contracts
from ai_treader_llm.datasets.reviews import validate_source_review
from ai_treader_llm.datasets.targets import validate_data_targets

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples/data-review-v1/sec-edgar-r11.json"
TARGETS = ROOT / "examples/data-review-v1/sec-edgar-r11-analysis-targets.json"


class DataSourceReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contracts = Contracts(ROOT / "contracts")
        cls.example = json.loads(EXAMPLE.read_text())
        cls.targets = json.loads(TARGETS.read_text())

    def test_real_sec_review_receipt_is_structurally_valid(self):
        summary = validate_source_review(EXAMPLE, self.contracts)
        self.assertEqual(summary["artifacts"], 10)
        self.assertEqual(summary["access_status"], "permitted")
        self.assertEqual(summary["survivorship_status"], "survivorship_biased")
        self.assertEqual(summary["target_status"], "ready")
        self.assertEqual(summary["targets"], 9)
        self.assertFalse(summary["bytes_verified"])

    def test_real_target_plan_pins_splits_and_keeps_labels_out(self):
        summary = validate_data_targets(TARGETS, self.contracts)
        self.assertEqual(summary["listings"], 3)
        self.assertEqual(summary["splits"], {"train": 3, "validation": 3, "test": 3})
        self.assertEqual(summary["held_out_boundary"], "2024-07-05T20:00:00Z")
        self.assertFalse(summary["labels_included"])
        self.assertFalse(summary["platform_files_verified"])

    def test_source_bytes_are_verified_when_root_is_supplied(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            content = b'{"real":"recorded source bytes"}\n'
            compressed = gzip.compress(content, mtime=0)
            (root / "page.json.gz").write_bytes(compressed)
            review = copy.deepcopy(self.example)
            review["target_readiness"] = self._pending_readiness(review["target_readiness"])
            review["artifacts"] = [{
                "path": "page.json.gz",
                "request": "sec:/test/page.json",
                "retrieved_at": "2026-09-26T17:51:49Z",
                "compression": "gzip",
                "compressed_sha256": hashlib.sha256(compressed).hexdigest(),
                "compressed_bytes": len(compressed),
                "content_sha256": hashlib.sha256(content).hexdigest(),
                "content_bytes": len(content),
            }]
            manifest = json.dumps({"pages": [{
                "file": "page.json.gz",
                "request": "sec:/test/page.json",
                "retrieved_at": "2026-09-26T17:51:49Z",
                "sha256": hashlib.sha256(content).hexdigest(),
                "bytes": len(content),
            }]}).encode()
            (root / "manifest.json").write_bytes(manifest)
            review["source"]["capture_manifest_sha256"] = hashlib.sha256(manifest).hexdigest()
            path = root / "review.json"
            path.write_text(json.dumps(review))
            summary = validate_source_review(path, self.contracts, source_root=root)
            self.assertTrue(summary["bytes_verified"])

            (root / "page.json.gz").write_bytes(compressed + b"changed")
            with self.assertRaisesRegex(ContractError, "hash mismatch"):
                validate_source_review(path, self.contracts, source_root=root)

    def test_ready_status_requires_every_dataset_control(self):
        with tempfile.TemporaryDirectory() as directory:
            review = copy.deepcopy(self.example)
            review["target_readiness"]["purge_embargo_pinned"] = False
            path = Path(directory) / "review.json"
            path.write_text(json.dumps(review))
            with self.assertRaisesRegex(ContractError, "readiness disagrees"):
                validate_source_review(path, self.contracts)

    def test_target_manifest_hash_and_source_coverage_are_bound(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target_path = root / "sec-edgar-r11-analysis-targets.json"
            target_path.write_bytes(TARGETS.read_bytes())
            review_path = root / "review.json"
            review = copy.deepcopy(self.example)
            review_path.write_text(json.dumps(review))
            self.assertEqual(validate_source_review(review_path, self.contracts)["targets"], 9)

            target = copy.deepcopy(self.targets)
            target["universe"]["listings"][0]["artifact_paths"].pop()
            target_path.write_text(json.dumps(target))
            with self.assertRaisesRegex(ContractError, "hash mismatch"):
                validate_source_review(review_path, self.contracts)

    def test_target_identity_and_embargo_tampering_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "targets.json"
            target = copy.deepcopy(self.targets)
            target["targets"][0]["symbol"] = "GE"
            path.write_text(json.dumps(target))
            with self.assertRaisesRegex(ContractError, "identity mismatch"):
                validate_data_targets(path, self.contracts)

            target = copy.deepcopy(self.targets)
            target["split_policy"]["embargo_evidence"][0]["sessions_after_label_end"].pop()
            path.write_text(json.dumps(target))
            with self.assertRaisesRegex(ContractError, "session count mismatch"):
                validate_data_targets(path, self.contracts)

    def test_duplicate_requests_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            review = copy.deepcopy(self.example)
            review["artifacts"][1]["request"] = review["artifacts"][0]["request"]
            path = Path(directory) / "review.json"
            path.write_text(json.dumps(review))
            with self.assertRaisesRegex(ContractError, "duplicate reviewed source request"):
                validate_source_review(path, self.contracts)

    @staticmethod
    def _pending_readiness(readiness):
        value = copy.deepcopy(readiness)
        value["status"] = "pending"
        for field in (
            "platform_listing_ids_pinned",
            "trading_calendar_pinned",
            "chronological_splits_pinned",
            "purge_embargo_pinned",
            "held_out_boundary_pinned",
        ):
            value[field] = False
        value["target_manifest"] = None
        return value


if __name__ == "__main__":
    unittest.main()
