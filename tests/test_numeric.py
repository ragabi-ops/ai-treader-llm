import copy
import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from ai_treader_llm import numeric, numeric_fixtures
from ai_treader_llm.contracts import Contracts


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "contracts/fixtures/numeric-v1"
EXAMPLES = ROOT / "examples/numeric-v1"


class NumericConformanceTests(unittest.TestCase):
    """Shared fixture behavior intended for the platform's Go validator."""

    @classmethod
    def setUpClass(cls):
        cls.contracts = Contracts(ROOT / "contracts")

    def test_every_case_returns_its_declared_code(self):
        suite = json.loads((FIXTURES / "cases.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(suite["cases"]), 50)
        for case in suite["cases"]:
            with self.subTest(case=case["name"]):
                documents = numeric_fixtures.apply_changes(suite["base"], case["changes"])
                try:
                    numeric_fixtures.run_case(case["operation"], documents, self.contracts)
                    code = "valid"
                except numeric.NumericError as error:
                    code = error.code
                self.assertEqual(case["expect"], code)

    def test_fixture_suite_exercises_each_public_error_code(self):
        suite = json.loads((FIXTURES / "cases.json").read_text(encoding="utf-8"))
        exercised = {case["expect"] for case in suite["cases"]}
        # invalid_json and artifact_mismatch require raw-byte/path fixtures below.
        expected = set(numeric.ERROR_CODES) - {"invalid_json", "artifact_mismatch"}
        self.assertEqual(expected, exercised - {"valid"})

    def test_hash_vectors_pin_canonical_utf8_bytes(self):
        vectors = json.loads((FIXTURES / "hash-vectors.json").read_text(encoding="utf-8"))
        for vector in vectors["vectors"]:
            with self.subTest(vector=vector["name"]):
                canonical = numeric.canonical_json(vector["value"])
                self.assertEqual(vector["canonical_utf8"].encode("utf-8"), canonical)
                self.assertEqual(vector["sha256"], hashlib.sha256(canonical).hexdigest())

    def test_committed_files_match_the_builder(self):
        for path, contents in numeric_fixtures.build().items():
            with self.subTest(path=path):
                self.assertEqual(contents, (ROOT / path).read_text(encoding="utf-8"))


class NumericArtifactBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contracts = Contracts(ROOT / "contracts")

    def setUp(self):
        self.directory = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.directory)
        for source in EXAMPLES.iterdir():
            shutil.copy(source, self.directory / source.name)

    def test_example_input_forecast_and_dataset_validate(self):
        inputs, calendar, rows = numeric.load_input(
            self.directory / "input-manifest.json", self.contracts
        )
        numeric.validate_forecast(
            numeric.read_json(self.directory / "forecast.json"),
            numeric.read_json(self.directory / "request.json"),
            inputs,
            calendar,
            rows,
            self.contracts,
        )
        summary = numeric.load_dataset(self.directory / "dataset-manifest.json", self.contracts)
        self.assertEqual(summary, {"dataset_id": "synthetic-numeric-v1", "features": 4, "labels": 4})

    def test_raw_artifact_tampering_is_rejected(self):
        with (self.directory / "features.jsonl").open("ab") as stream:
            stream.write(b"\n")
        with self.assertRaisesRegex(numeric.NumericError, "artifact_mismatch"):
            numeric.load_input(self.directory / "input-manifest.json", self.contracts)

    def test_labels_cannot_alias_prediction_inputs(self):
        path = self.directory / "dataset-manifest.json"
        manifest = numeric.read_json(path)
        manifest["labels"] = copy.deepcopy(manifest["input_manifest"])
        path.write_text(json.dumps(numeric.seal(manifest)), encoding="utf-8")
        with self.assertRaisesRegex(numeric.NumericError, "separate artifact"):
            numeric.load_dataset(path, self.contracts)

    def test_artifact_cannot_escape_its_manifest_directory(self):
        path = self.directory / "input-manifest.json"
        manifest = numeric.read_json(path)
        manifest["features"]["path"] = "../features.jsonl"
        path.write_text(json.dumps(numeric.seal(manifest)), encoding="utf-8")
        with self.assertRaisesRegex(numeric.NumericError, "escapes"):
            numeric.load_input(path, self.contracts)

    def test_duplicate_keys_and_json_floats_are_rejected_before_schema(self):
        for raw in ('{"a":1,"a":2}', '{"value":0.1}', '{"value":NaN}'):
            with self.subTest(raw=raw), self.assertRaisesRegex(
                numeric.NumericError, "invalid_json"
            ):
                numeric.loads(raw)


if __name__ == "__main__":
    unittest.main()
