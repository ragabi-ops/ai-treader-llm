import copy
import hashlib
import json
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ai_treader_llm import contract_fixtures, contracts_v2
from ai_treader_llm.contracts import ContractError, Contracts
from ai_treader_llm.datasets.manifests import validate_manifest
from ai_treader_llm.datasets.outcomes import validate_outcomes
from ai_treader_llm.datasets.samples import build_messages, read_jsonl, validate_dataset, validate_sample
from ai_treader_llm.evaluation.runner import evaluate

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "contracts/fixtures/v2"
EXAMPLES = ROOT / "examples/v2"


class SharedFixtureTests(unittest.TestCase):
    """The same files the platform's Go validator runs; codes must agree."""

    @classmethod
    def setUpClass(cls):
        cls.contracts = Contracts(ROOT / "contracts")

    def test_every_case_returns_its_code(self):
        cases = json.loads((FIXTURES / "analysis-cases.json").read_text())["cases"]
        self.assertGreater(len(cases), 20)
        for case in cases:
            with self.subTest(case["name"]):
                try:
                    contracts_v2.validate_analysis(case["analysis"], case["context"], self.contracts)
                    got = "valid"
                except contracts_v2.V2Error as error:
                    got = error.code
                self.assertEqual(case["expect"], got)

    def test_every_code_is_exercised(self):
        cases = json.loads((FIXTURES / "analysis-cases.json").read_text())["cases"]
        codes = {
            value for name, value in vars(contracts_v2).items()
            if name.isupper() and isinstance(value, str) and not name.endswith("_SCHEMA")
        }
        self.assertEqual(codes, {case["expect"] for case in cases} - {"valid"})

    def test_hash_vectors(self):
        vectors = json.loads((FIXTURES / "context-hash-vectors.json").read_text())["vectors"]
        for vector in vectors:
            with self.subTest(vector["name"]):
                self.assertEqual(vector["context"]["context_sha256"], contracts_v2.context_hash(vector["context"]))
                contracts_v2.validate_context(vector["context"], self.contracts)

    def test_committed_files_match_the_builder(self):
        for path, text in contract_fixtures.build().items():
            with self.subTest(str(path)):
                self.assertEqual(text, (ROOT / path).read_text(), "regenerate: python -m ai_treader_llm.contract_fixtures")


class CanonicalTests(unittest.TestCase):
    def test_sorted_compact_utf8(self):
        self.assertEqual(
            contracts_v2.canonical_json({"b": [1, "é "], "a": None, "c": True}),
            '{"a":null,"b":[1,"é "],"c":true}'.encode("utf-8"),
        )

    def test_control_characters_use_lowercase_escapes(self):
        self.assertEqual(contracts_v2.canonical_json("\x01\x1f\n"), b'"\\u0001\\u001f\\n"')

    def test_fractional_numbers_refused(self):
        with self.assertRaises(contracts_v2.V2Error):
            contracts_v2.canonical_json({"value": 1.5})

    def test_hash_ignores_its_own_field(self):
        context = contract_fixtures.base_context()
        sealed = dict(context, context_sha256="f" * 64)
        self.assertEqual(contracts_v2.context_hash(context), contracts_v2.context_hash(sealed))


class DatasetV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contracts = Contracts(ROOT / "contracts")
        cls.samples = read_jsonl(EXAMPLES / "samples.jsonl")
        cls.outcomes = read_jsonl(EXAMPLES / "outcomes.jsonl")

    def setUp(self):
        self.sample = copy.deepcopy(self.samples[0])

    def test_examples_valid(self):
        validate_outcomes(
            self.samples, self.outcomes, self.contracts,
            embargoed_starts={"validation": None, "test": "2025-03-05T21:00:00Z"},
        )

    def test_changed_content_rejected(self):
        self.sample["sources"][0]["content"] += " Changed."
        with self.assertRaisesRegex(ContractError, "hash mismatch"):
            validate_sample(self.sample, self.contracts)

    def test_expected_analysis_is_grounded(self):
        self.sample["expected_analysis"]["technicals"]["evidence_ids"] = ["news-1"]
        self.sample["expected_analysis"]["technicals"]["metric_refs"] = []
        with self.assertRaisesRegex(ContractError, "section_kind_mismatch"):
            validate_sample(self.sample, self.contracts)

    def test_mixed_versions_refused(self):
        v1 = read_jsonl(ROOT / "examples/samples.jsonl")[0]
        with self.assertRaisesRegex(ContractError, "mixed sample schema versions"):
            validate_dataset([self.sample, v1], self.contracts)

    def test_inputs_exclude_collection_metadata_and_targets(self):
        messages = json.dumps(build_messages(self.sample, self.contracts))
        for hidden in ("ingested_at", "expected_analysis", "Revenue grew in the latest filing", "split"):
            self.assertNotIn(hidden, messages)
        self.assertIn('\\"listing_id\\": 101', messages)

    def test_prediction_checked_against_v2_context(self):
        predictions = [
            {"sample_id": sample["sample_id"], "analysis": copy.deepcopy(sample["expected_analysis"])}
            for sample in self.samples
        ]
        predictions[1]["analysis"]["risks"][0]["evidence_ids"] = ["news-9"]
        report = evaluate(self.samples, predictions, self.contracts)
        self.assertEqual(report["valid"], 1)
        self.assertIn("unknown_evidence", report["failures"][0]["error"])


class OutcomeV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contracts = Contracts(ROOT / "contracts")
        cls.samples = read_jsonl(EXAMPLES / "samples.jsonl")
        cls.fixture = read_jsonl(EXAMPLES / "outcomes.jsonl")

    def setUp(self):
        self.outcomes = copy.deepcopy(self.fixture)

    def check(self, **kwargs):
        validate_outcomes(self.samples, self.outcomes, self.contracts, **kwargs)

    def test_unavailable_with_reason_is_valid(self):
        self.assertEqual(self.outcomes[1]["return"]["status"], "unavailable")
        self.check()

    def test_unavailable_must_not_carry_a_value(self):
        self.outcomes[1]["return"]["value"] = 0.0
        with self.assertRaises(ContractError):
            self.check()

    def test_available_must_carry_a_value(self):
        self.outcomes[0]["return"]["value"] = None
        with self.assertRaises(ContractError):
            self.check()

    def test_unknown_reason_rejected(self):
        self.outcomes[1]["return"]["reason"] = "model_said_so"
        with self.assertRaises(ContractError):
            self.check()

    def test_non_finite_rejected(self):
        self.outcomes[0]["return"]["value"] = float("nan")
        with self.assertRaisesRegex(ContractError, "non-finite"):
            self.check()

    def test_horizon_must_match_sample(self):
        self.outcomes[0]["horizon"]["end_session"] = "2025-02-04"
        with self.assertRaisesRegex(ContractError, "horizon differs"):
            self.check()

    def test_day_embargo_refused_for_v2(self):
        with self.assertRaisesRegex(ContractError, "embargoed starts"):
            self.check(embargo=timedelta(days=1))

    def test_sample_before_embargoed_start_rejected(self):
        with self.assertRaisesRegex(ContractError, "precedes the embargoed start"):
            self.check(embargoed_starts={"validation": None, "test": "2025-03-10T20:00:00Z"})

    def test_embargoed_start_before_earlier_labels_rejected(self):
        with self.assertRaisesRegex(ContractError, "precedes the earlier labels"):
            self.check(embargoed_starts={"validation": None, "test": "2025-02-01T00:00:00Z"})

    def test_missing_embargoed_start_rejected(self):
        with self.assertRaisesRegex(ContractError, "missing embargoed start"):
            self.check(embargoed_starts={"validation": None, "test": None})


class ManifestBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contracts = Contracts(ROOT / "contracts")

    def setUp(self):
        self.directory = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.directory)
        for name in ("samples.jsonl", "outcomes.jsonl", "dataset-manifest.json"):
            shutil.copy(EXAMPLES / name, self.directory / name)
        self.path = self.directory / "dataset-manifest.json"
        self.manifest = json.loads(self.path.read_text())

    def write(self):
        self.path.write_text(json.dumps(self.manifest))

    def boundary(self, text):
        return datetime.fromisoformat(text.replace("Z", "+00:00"))

    def test_valid_with_and_without_boundary(self):
        validate_manifest(self.path, self.contracts)
        summary = validate_manifest(self.path, self.contracts, evaluation_boundary=self.boundary("2025-06-01T00:00:00Z"))
        self.assertEqual(summary["evaluation_boundary"], "2025-06-01T00:00:00Z")

    def test_label_crossing_boundary_rejected(self):
        with self.assertRaisesRegex(ContractError, "label interval crosses"):
            validate_manifest(self.path, self.contracts, evaluation_boundary=self.boundary("2025-04-07T20:00:00Z"))

    def test_cutoff_at_boundary_rejected(self):
        with self.assertRaisesRegex(ContractError, "cutoff is not before"):
            validate_manifest(self.path, self.contracts, evaluation_boundary=self.boundary("2025-03-07T21:00:00Z"))

    def test_naive_boundary_rejected(self):
        with self.assertRaisesRegex(ContractError, "timezone"):
            validate_manifest(self.path, self.contracts, evaluation_boundary=datetime(2025, 6, 1))

    def test_v2_windows_checked_without_outcome_artifact(self):
        self.manifest["outcomes"] = None
        self.manifest["split_policy"]["embargoed_starts"]["test"] = "2025-03-10T20:00:00Z"
        self.write()
        with self.assertRaisesRegex(ContractError, "precedes the embargoed start"):
            validate_manifest(self.path, self.contracts)

    def test_v2_purge_cannot_be_disabled(self):
        self.manifest["split_policy"]["outcome_window_purged"] = False
        self.write()
        with self.assertRaisesRegex(ContractError, "always purged"):
            validate_manifest(self.path, self.contracts)

    def test_v1_boundary_without_outcomes_refused(self):
        v1 = self.directory / "v1"
        v1.mkdir()
        samples = (ROOT / "examples/samples.jsonl").read_bytes()
        (v1 / "samples.jsonl").write_bytes(samples)
        manifest = json.loads((ROOT / "examples/dataset-manifest.json").read_text())
        manifest["outcomes"] = None
        manifest["split_policy"]["outcome_window_purged"] = False
        manifest["samples"]["sha256"] = hashlib.sha256(samples).hexdigest()
        (v1 / "dataset-manifest.json").write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ContractError, "requires an outcome"):
            validate_manifest(v1 / "dataset-manifest.json", self.contracts,
                              evaluation_boundary=datetime(2026, 1, 1, tzinfo=timezone.utc))

    def test_version_mismatch_refused(self):
        self.manifest["schema_version"] = "1"
        self.manifest["analysis_horizons"] = ["5d"]
        self.manifest["split_policy"] = {"chronological": True, "outcome_window_purged": True, "embargo_days": 0}
        self.write()
        with self.assertRaisesRegex(ContractError, "differs from the manifest"):
            validate_manifest(self.path, self.contracts)


if __name__ == "__main__":
    unittest.main()
