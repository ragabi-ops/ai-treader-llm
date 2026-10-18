import copy
import gzip
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from ai_treader_llm.contracts import ContractError, Contracts
from ai_treader_llm.datasets.reviews import validate_source_review

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples/data-review-v1/sec-edgar-r11.json"


class DataSourceReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contracts = Contracts(ROOT / "contracts")
        cls.example = json.loads(EXAMPLE.read_text())

    def test_real_sec_review_receipt_is_structurally_valid(self):
        summary = validate_source_review(EXAMPLE, self.contracts)
        self.assertEqual(summary["artifacts"], 10)
        self.assertEqual(summary["access_status"], "permitted")
        self.assertEqual(summary["survivorship_status"], "survivorship_biased")
        self.assertEqual(summary["target_status"], "pending")
        self.assertFalse(summary["bytes_verified"])

    def test_source_bytes_are_verified_when_root_is_supplied(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            content = b'{"real":"recorded source bytes"}\n'
            compressed = gzip.compress(content, mtime=0)
            (root / "page.json.gz").write_bytes(compressed)
            review = copy.deepcopy(self.example)
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
            review["target_readiness"]["status"] = "ready"
            path = Path(directory) / "review.json"
            path.write_text(json.dumps(review))
            with self.assertRaisesRegex(ContractError, "readiness disagrees"):
                validate_source_review(path, self.contracts)

    def test_duplicate_requests_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            review = copy.deepcopy(self.example)
            review["artifacts"][1]["request"] = review["artifacts"][0]["request"]
            path = Path(directory) / "review.json"
            path.write_text(json.dumps(review))
            with self.assertRaisesRegex(ContractError, "duplicate reviewed source request"):
                validate_source_review(path, self.contracts)


if __name__ == "__main__":
    unittest.main()
