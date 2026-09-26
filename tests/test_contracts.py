import copy
import json
import unittest
from pathlib import Path

from ai_treader_llm.contracts import ContractError, Contracts
from ai_treader_llm.datasets.samples import build_messages, context_for, read_jsonl, validate_dataset, validate_sample
from ai_treader_llm.evaluation.runner import evaluate

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


if __name__ == "__main__":
    unittest.main()
