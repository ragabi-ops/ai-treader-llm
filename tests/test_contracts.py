import copy
import hashlib
import json
import shutil
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from ai_treader_llm.contracts import ContractError, Contracts
from ai_treader_llm.datasets.manifests import validate_manifest
from ai_treader_llm.datasets.outcomes import validate_outcomes
from ai_treader_llm.datasets.samples import build_messages, context_for, read_jsonl, validate_dataset, validate_sample
from ai_treader_llm.evaluation.runner import evaluate
from ai_treader_llm.evaluation.tools import FAILURE_CATEGORIES, evaluate_tool_calls

ROOT = Path(__file__).resolve().parents[1]


class ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contracts = Contracts(ROOT / "contracts")
        cls.fixture = read_jsonl(ROOT / "examples/samples.jsonl")[0]

    def setUp(self):
        self.sample = copy.deepcopy(self.fixture)

    def test_valid_fixture(self):
        validate_dataset([self.sample], self.contracts)

    def test_future_source_rejected(self):
        self.sample["sources"][0]["available_at"] = "2025-01-03T00:00:00Z"
        with self.assertRaisesRegex(ContractError, "future source"):
            validate_sample(self.sample, self.contracts)

    def test_late_ingestion_rejected_for_platform_replay(self):
        self.sample["sources"][0]["ingested_at"] = "2025-01-03T00:00:00Z"
        with self.assertRaisesRegex(ContractError, "not yet ingested"):
            validate_sample(self.sample, self.contracts)

    def test_public_information_can_be_collected_later(self):
        self.sample["replay_mode"] = "public_information"
        self.sample["sources"][0]["ingested_at"] = "2025-01-03T00:00:00Z"
        validate_sample(self.sample, self.contracts)

    def test_changed_source_content_rejected(self):
        self.sample["sources"][0]["content"] += " Changed."
        with self.assertRaisesRegex(ContractError, "hash mismatch"):
            validate_sample(self.sample, self.contracts)

    def test_later_collection_metadata_excluded_from_inputs(self):
        self.sample["replay_mode"] = "public_information"
        self.sample["sources"][0]["ingested_at"] = "2026-09-26T12:34:56Z"
        serialized = json.dumps(build_messages(self.sample, self.contracts))
        self.assertNotIn("2026-09-26T12:34:56Z", serialized)
        self.assertNotIn("ingested_at", serialized)

    def test_outcome_fields_rejected(self):
        self.sample["return_30d"] = 0.25
        with self.assertRaises(ContractError):
            validate_sample(self.sample, self.contracts)

    def test_unknown_source_fields_rejected(self):
        self.sample["sources"][0]["return_30d"] = 0.25
        with self.assertRaises(ContractError):
            validate_sample(self.sample, self.contracts)

    def test_labels_never_enter_messages(self):
        self.sample["expected_analysis"]["thesis"]["text"] = "SECRET_SUPERVISED_TARGET"
        serialized = json.dumps(build_messages(self.sample, self.contracts))
        self.assertNotIn("SECRET_SUPERVISED_TARGET", serialized)
        self.assertNotIn("expected_analysis", serialized)
        self.assertNotIn('"split"', serialized)

    def test_hallucinated_citation_rejected(self):
        self.sample["expected_analysis"]["thesis"]["evidence_ids"] = ["invented"]
        with self.assertRaisesRegex(ContractError, "unknown evidence"):
            validate_sample(self.sample, self.contracts)

    def test_hallucinated_metric_rejected(self):
        self.sample["expected_analysis"]["fundamentals"] = {
            "summary": {"text": "Example", "evidence_ids": []}, "metric_refs": ["invented"]}
        with self.assertRaisesRegex(ContractError, "unknown metric"):
            validate_sample(self.sample, self.contracts)

    def test_model_cannot_change_cutoff_or_symbol(self):
        context = context_for(self.sample)
        for field, value in [("symbol", "OTHER"), ("as_of_timestamp", "2025-01-01T00:00:00Z")]:
            analysis = copy.deepcopy(self.sample["expected_analysis"])
            analysis[field] = value
            with self.assertRaises(ContractError):
                self.contracts.analysis(analysis, context)

    def test_invalid_calendar_date_rejected(self):
        self.sample["as_of_timestamp"] = "2025-02-30T15:00:00Z"
        with self.assertRaises(ContractError):
            validate_sample(self.sample, self.contracts)

    def test_non_utc_time_rejected(self):
        self.sample["as_of_timestamp"] = "2025-01-02T15:00:00"
        with self.assertRaises(ContractError):
            validate_sample(self.sample, self.contracts)

    def test_duplicate_samples_rejected(self):
        with self.assertRaisesRegex(ContractError, "duplicate sample"):
            validate_dataset([self.sample, self.sample], self.contracts)

    def test_duplicate_evidence_rejected(self):
        self.sample["sources"].append(copy.deepcopy(self.sample["sources"][0]))
        with self.assertRaisesRegex(ContractError, "duplicate evidence"):
            validate_sample(self.sample, self.contracts)

    def test_split_time_overlap_rejected(self):
        other = copy.deepcopy(self.sample)
        other["sample_id"] = "another"
        other["split"] = "train"
        with self.assertRaisesRegex(ContractError, "splits overlap"):
            validate_dataset([other, self.sample], self.contracts)

    def test_cross_split_exact_source_duplicate_rejected(self):
        other = self.later_sample("another", "validation")
        self.sample["split"] = "train"
        with self.assertRaisesRegex(ContractError, "cross-split duplicate"):
            validate_dataset([self.sample, other], self.contracts)

    def test_cross_split_near_duplicate_rejected(self):
        self.sample["split"] = "train"
        words = [f"token{number}" for number in range(30)]
        self.set_source_content(self.sample, " ".join(words))
        other = self.later_sample("another", "validation")
        words[-1] = "replacement"
        self.set_source_content(other, " ".join(words))
        with self.assertRaisesRegex(ContractError, "cross-split duplicate"):
            validate_dataset([self.sample, other], self.contracts)

    def test_same_split_duplicate_source_allowed(self):
        other = copy.deepcopy(self.sample)
        other["sample_id"] = "another"
        validate_dataset([self.sample, other], self.contracts)

    def test_historical_source_may_recur_in_distinct_later_input(self):
        self.sample["split"] = "train"
        other = self.later_sample("another", "validation")
        new_source = copy.deepcopy(other["sources"][0])
        new_source["evidence_id"] = "news-2"
        new_source["content"] = (
            "A genuinely new later source adds enough distinct context to make this "
            "a different analysis case while retaining the historical source."
        )
        new_source["content_sha256"] = hashlib.sha256(new_source["content"].encode("utf-8")).hexdigest()
        other["sources"].append(new_source)
        validate_dataset([self.sample, other], self.contracts)

    def test_empty_dataset_rejected(self):
        with self.assertRaisesRegex(ContractError, "empty"):
            validate_dataset([], self.contracts)

    def test_missing_predictions_count_as_failures(self):
        report = evaluate([self.sample], [], self.contracts)
        self.assertEqual(report["validity_rate"], 0)
        self.assertEqual(report["failures"][0]["error"], "missing prediction")

    def test_structural_success_never_authorizes_promotion(self):
        predictions = [{"sample_id": self.sample["sample_id"], "analysis": self.sample["expected_analysis"]}]
        report = evaluate([self.sample], predictions, self.contracts)
        self.assertEqual(report["validity_rate"], 1)
        self.assertFalse(report["promotion_eligible"])

    def test_duplicate_and_unknown_predictions_rejected(self):
        row = {"sample_id": self.sample["sample_id"], "analysis": self.sample["expected_analysis"]}
        for rows in ([row, row], [{**row, "sample_id": "unknown"}]):
            with self.assertRaises(ContractError):
                evaluate([self.sample], rows, self.contracts)

    def test_invalid_prediction_counted_without_disappearing(self):
        report = evaluate([self.sample], [{"sample_id": self.sample["sample_id"], "analysis": {}}], self.contracts)
        self.assertEqual(report["total"], 1)
        self.assertEqual(report["valid"], 0)

    def later_sample(self, sample_id, split):
        other = copy.deepcopy(self.sample)
        other["sample_id"] = sample_id
        other["split"] = split
        other["as_of_timestamp"] = "2025-02-02T15:00:00Z"
        other["expected_analysis"]["as_of_timestamp"] = "2025-02-02T15:00:00Z"
        other["expected_analysis"]["timestamp"] = "2025-02-02T15:00:01Z"
        return other

    @staticmethod
    def set_source_content(sample, content):
        sample["sources"][0]["content"] = content
        sample["sources"][0]["content_sha256"] = hashlib.sha256(content.encode("utf-8")).hexdigest()


class OutcomeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contracts = Contracts(ROOT / "contracts")
        cls.fixture = read_jsonl(ROOT / "examples/samples.jsonl")[0]

    def setUp(self):
        self.train = copy.deepcopy(self.fixture)
        self.train["split"] = "train"
        self.validation = copy.deepcopy(self.fixture)
        self.validation["sample_id"] = "synthetic-002"
        self.validation["split"] = "validation"
        self.validation["as_of_timestamp"] = "2025-01-08T15:00:00Z"
        self.validation["expected_analysis"]["as_of_timestamp"] = "2025-01-08T15:00:00Z"
        self.validation["expected_analysis"]["timestamp"] = "2025-01-08T15:00:01Z"
        validation_content = "Synthetic fixture: a distinct later source with no financial figures supplied."
        self.validation["sources"][0]["content"] = validation_content
        self.validation["sources"][0]["content_sha256"] = hashlib.sha256(
            validation_content.encode("utf-8")
        ).hexdigest()
        self.outcomes = [
            self.outcome("synthetic-001", "2025-01-07T15:00:00Z"),
            self.outcome("synthetic-002", "2025-04-08T15:00:00Z"),
        ]

    @staticmethod
    def outcome(sample_id, label_end):
        return {
            "schema_version": "1",
            "sample_id": sample_id,
            "label_end_timestamp": label_end,
            "return_1d": 0.01,
            "return_5d": 0.02,
            "return_30d": -0.03,
            "return_90d": 0.04,
            "max_drawdown": -0.08,
            "volatility": 0.2,
        }

    def test_valid_separate_outcomes(self):
        validate_outcomes([self.train, self.validation], self.outcomes, self.contracts)

    def test_outcome_schema_rejects_unknown_fields(self):
        self.outcomes[0]["future_feature"] = 1
        with self.assertRaises(ContractError):
            validate_outcomes([self.train, self.validation], self.outcomes, self.contracts)

    def test_outcomes_require_exact_sample_coverage(self):
        with self.assertRaisesRegex(ContractError, "missing outcome"):
            validate_outcomes([self.train, self.validation], self.outcomes[:1], self.contracts)
        unknown = self.outcome("unknown", "2025-01-09T15:00:00Z")
        with self.assertRaisesRegex(ContractError, "unknown sample"):
            validate_outcomes([self.train, self.validation], self.outcomes + [unknown], self.contracts)

    def test_duplicate_outcomes_rejected(self):
        with self.assertRaisesRegex(ContractError, "duplicate outcome"):
            validate_outcomes(
                [self.train, self.validation],
                self.outcomes + [copy.deepcopy(self.outcomes[0])],
                self.contracts,
            )

    def test_label_end_must_follow_cutoff(self):
        self.outcomes[0]["label_end_timestamp"] = self.train["as_of_timestamp"]
        with self.assertRaisesRegex(ContractError, "label end"):
            validate_outcomes([self.train, self.validation], self.outcomes, self.contracts)

    def test_non_finite_outcome_rejected(self):
        self.outcomes[0]["return_1d"] = float("nan")
        with self.assertRaisesRegex(ContractError, "non-finite"):
            validate_outcomes([self.train, self.validation], self.outcomes, self.contracts)

    def test_cross_split_outcome_window_rejected(self):
        self.outcomes[0]["label_end_timestamp"] = "2025-01-09T15:00:00Z"
        with self.assertRaisesRegex(ContractError, "cross split"):
            validate_outcomes([self.train, self.validation], self.outcomes, self.contracts)

    def test_configured_embargo_enforced(self):
        with self.assertRaisesRegex(ContractError, "embargo"):
            validate_outcomes(
                [self.train, self.validation],
                self.outcomes,
                self.contracts,
                embargo=timedelta(days=2),
            )

    def test_negative_embargo_rejected(self):
        with self.assertRaisesRegex(ContractError, "negative"):
            validate_outcomes(
                [self.train, self.validation],
                self.outcomes,
                self.contracts,
                embargo=timedelta(days=-1),
            )


class ToolEvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contracts = Contracts(ROOT / "contracts")

    def setUp(self):
        self.fixture = {
            "schema_version": "1",
            "case_id": "tool-case-1",
            "description": "Synthetic price lookup fixture.",
            "messages": [{"role": "user", "content": "Get SYNTH price history."}],
            "trusted_scope": {
                "symbol": "SYNTH",
                "as_of_timestamp": "2025-01-10T16:00:00Z",
            },
            "allowed_tools": ["get_price_history"],
            "expected_tool_names": ["get_price_history"],
        }
        self.call = {
            "call_id": "call-1",
            "name": "get_price_history",
            "arguments": {
                "symbol": "SYNTH",
                "start_timestamp": "2025-01-02T16:00:00Z",
                "end_timestamp": "2025-01-10T16:00:00Z",
                "interval": "1d",
            },
        }

    def prediction(self, calls=None):
        return {
            "schema_version": "1",
            "case_id": self.fixture["case_id"],
            "tool_calls": copy.deepcopy([self.call] if calls is None else calls),
        }

    def evaluate(self, prediction):
        return evaluate_tool_calls([self.fixture], [prediction], self.contracts)

    def test_valid_tool_call_fixture(self):
        report = self.evaluate(self.prediction([self.call]))
        self.assertEqual(report["correctness_rate"], 1)
        self.assertEqual(report["predicted_calls"], 1)
        self.assertFalse(report["promotion_eligible"])
        self.assertEqual(report["failure_counts"], {name: 0 for name in FAILURE_CATEGORIES})

    def test_missing_prediction_is_counted(self):
        report = evaluate_tool_calls([self.fixture], [], self.contracts)
        self.assertEqual(report["correct_cases"], 0)
        self.assertEqual(report["failure_counts"]["missing_prediction"], 1)

    def test_unauthorized_tool_is_counted(self):
        call = copy.deepcopy(self.call)
        call["name"] = "get_filings"
        call["arguments"] = {"symbol": "SYNTH", "forms": ["10-Q"], "limit": 1}
        report = self.evaluate(self.prediction([call]))
        self.assertEqual(report["failure_counts"]["unauthorized_tool"], 1)
        self.assertEqual(report["failure_counts"]["missing_required_call"], 1)

    def test_unknown_tool_is_unauthorized_not_operational_error(self):
        call = copy.deepcopy(self.call)
        call["name"] = "execute_trade"
        call["arguments"] = {}
        report = self.evaluate(self.prediction([call]))
        self.assertEqual(report["failure_counts"]["unauthorized_tool"], 1)

    def test_tool_arguments_reject_unknown_fields(self):
        call = copy.deepcopy(self.call)
        call["arguments"]["adjusted_return"] = 0.5
        report = self.evaluate(self.prediction([call]))
        self.assertEqual(report["failure_counts"]["invalid_arguments"], 1)

    def test_tool_arguments_require_an_object(self):
        call = copy.deepcopy(self.call)
        call["arguments"] = "not parsed JSON"
        report = self.evaluate(self.prediction([call]))
        self.assertEqual(report["failure_counts"]["invalid_arguments"], 1)

    def test_trusted_symbol_is_enforced(self):
        call = copy.deepcopy(self.call)
        call["arguments"]["symbol"] = "OTHER"
        report = self.evaluate(self.prediction([call]))
        self.assertEqual(report["failure_counts"]["symbol_violation"], 1)

    def test_trusted_as_of_boundary_is_enforced(self):
        call = copy.deepcopy(self.call)
        call["arguments"]["end_timestamp"] = "2025-01-10T16:00:01Z"
        report = self.evaluate(self.prediction([call]))
        self.assertEqual(report["failure_counts"]["timestamp_violation"], 1)

    def test_reversed_time_range_is_enforced(self):
        call = copy.deepcopy(self.call)
        call["arguments"]["start_timestamp"] = "2025-01-10T15:00:00Z"
        call["arguments"]["end_timestamp"] = "2025-01-09T15:00:00Z"
        report = self.evaluate(self.prediction([call]))
        self.assertEqual(report["failure_counts"]["timestamp_violation"], 1)

    def test_unnecessary_call_is_counted(self):
        self.fixture["expected_tool_names"] = []
        report = self.evaluate(self.prediction([self.call]))
        self.assertEqual(report["failure_counts"]["unnecessary_call"], 1)

    def test_wrong_allowlisted_tool_is_counted(self):
        self.fixture["allowed_tools"].append("get_filings")
        call = copy.deepcopy(self.call)
        call["name"] = "get_filings"
        call["arguments"] = {"symbol": "SYNTH", "forms": ["10-Q"], "limit": 1}
        report = self.evaluate(self.prediction([call]))
        self.assertEqual(report["failure_counts"]["incorrect_tool"], 1)
        self.assertEqual(report["failure_counts"]["missing_required_call"], 1)

    def test_extra_duplicate_call_is_unnecessary(self):
        report = self.evaluate(self.prediction([self.call, self.call]))
        self.assertEqual(report["failure_counts"]["unnecessary_call"], 1)

    def test_invalid_prediction_is_counted(self):
        prediction = self.prediction([self.call])
        prediction["unexpected"] = True
        report = self.evaluate(prediction)
        self.assertEqual(report["failure_counts"]["invalid_prediction"], 1)

    def test_invalid_fixture_tool_configuration_is_rejected(self):
        self.fixture["allowed_tools"] = ["execute_trade"]
        self.fixture["expected_tool_names"] = []
        with self.assertRaisesRegex(ContractError, "allows unknown tools"):
            evaluate_tool_calls([self.fixture], [], self.contracts)

    def test_duplicate_and_unknown_predictions_are_rejected(self):
        prediction = self.prediction([self.call])
        with self.assertRaisesRegex(ContractError, "duplicate or unknown"):
            evaluate_tool_calls([self.fixture], [prediction, prediction], self.contracts)
        prediction["case_id"] = "unknown"
        with self.assertRaisesRegex(ContractError, "duplicate or unknown"):
            evaluate_tool_calls([self.fixture], [prediction], self.contracts)


class ManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contracts = Contracts(ROOT / "contracts")

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for name in ("dataset-manifest.json", "samples.jsonl", "outcomes.jsonl"):
            shutil.copy2(ROOT / "examples" / name, self.root / name)
        self.path = self.root / "dataset-manifest.json"

    def manifest(self):
        return json.loads(self.path.read_text())

    def write_manifest(self, manifest):
        self.path.write_text(json.dumps(manifest))

    def test_valid_manifest(self):
        summary = validate_manifest(self.path, self.contracts)
        self.assertEqual(summary, {"dataset_id": "synthetic-fixture-v1", "samples": 1, "outcomes": 1})

    def test_manifest_detects_artifact_tampering(self):
        with (self.root / "samples.jsonl").open("a") as stream:
            stream.write("\n")
        with self.assertRaisesRegex(ContractError, "hash mismatch"):
            validate_manifest(self.path, self.contracts)

    def test_manifest_artifact_cannot_escape_directory(self):
        manifest = self.manifest()
        manifest["samples"]["path"] = "../samples.jsonl"
        self.write_manifest(manifest)
        with self.assertRaisesRegex(ContractError, "escapes"):
            validate_manifest(self.path, self.contracts)

    def test_manifest_split_summary_must_match(self):
        manifest = self.manifest()
        manifest["splits"]["test"]["sample_count"] = 2
        self.write_manifest(manifest)
        with self.assertRaisesRegex(ContractError, "split count mismatch"):
            validate_manifest(self.path, self.contracts)

    def test_reviewed_manifest_requires_provenance(self):
        manifest = self.manifest()
        manifest["review"]["status"] = "reviewed"
        self.write_manifest(manifest)
        with self.assertRaisesRegex(ContractError, "requires reviewer"):
            validate_manifest(self.path, self.contracts)

    def test_manifest_may_exclude_separate_outcomes(self):
        manifest = self.manifest()
        manifest["outcomes"] = None
        manifest["split_policy"]["outcome_window_purged"] = False
        self.write_manifest(manifest)
        summary = validate_manifest(self.path, self.contracts)
        self.assertEqual(summary["outcomes"], 0)


if __name__ == "__main__":
    unittest.main()
