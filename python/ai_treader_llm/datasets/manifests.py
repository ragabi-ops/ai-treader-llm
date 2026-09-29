from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path

from ai_treader_llm.contracts import ContractError, Contracts, timestamp
from ai_treader_llm.datasets.outcomes import check_split_windows, label_end, validate_outcomes
from ai_treader_llm.datasets.samples import is_v2, read_jsonl, validate_dataset


SPLITS = ("train", "validation", "test")


def validate_manifest(
    path: Path, contracts: Contracts, *, evaluation_boundary: datetime | None = None
) -> dict:
    """Validate a dataset manifest and, given one, its evaluation fence.

    evaluation_boundary is the platform's embargoed boundary (L03 §3.8): every
    sample's cutoff and every label interval must end before it, so nothing in
    the dataset can have seen the evaluation window.
    """
    try:
        manifest = json.loads(path.read_text())
    except json.JSONDecodeError as error:
        raise ContractError(f"{path}: invalid JSON") from error
    if not isinstance(manifest, dict):
        raise ContractError(f"{path}: expected an object")
    v2 = manifest.get("schema_version") == "2"
    contracts.validate("dataset-manifest-v2.schema.json" if v2 else "dataset-manifest.schema.json", manifest)

    sample_path = _artifact_path(path, manifest["samples"])
    samples = read_jsonl(sample_path)
    _validate_artifact(sample_path, manifest["samples"], len(samples))
    if any(is_v2(sample) != v2 for sample in samples):
        raise ContractError("sample schema version differs from the manifest")

    policy = manifest["split_policy"]
    embargoed_starts = policy["embargoed_starts"] if v2 else None
    embargo = timedelta(0) if v2 else timedelta(days=policy["embargo_days"])
    if v2 and not policy["outcome_window_purged"]:
        raise ContractError("v2 label windows are known and always purged")

    outcome_entry = manifest["outcomes"]
    outcomes_by_id = {}
    if outcome_entry is None:
        validate_dataset(samples, contracts)
        if v2:
            check_split_windows(_windows(samples, {}), embargoed_starts=embargoed_starts)
        else:
            if policy["outcome_window_purged"]:
                raise ContractError("outcome_window_purged requires an outcome artifact")
            if policy["embargo_days"] != 0:
                raise ContractError("embargo requires an outcome artifact")
        outcome_count = 0
    else:
        outcome_path = _artifact_path(path, outcome_entry)
        outcomes = read_jsonl(outcome_path)
        _validate_artifact(outcome_path, outcome_entry, len(outcomes))
        if not policy["outcome_window_purged"]:
            raise ContractError("outcome artifact requires outcome_window_purged")
        validate_outcomes(
            samples, outcomes, contracts, embargo=embargo, embargoed_starts=embargoed_starts
        )
        outcomes_by_id = {outcome["sample_id"]: outcome for outcome in outcomes}
        outcome_count = len(outcomes)

    _validate_splits(samples, manifest["splits"])
    if v2:
        actual_horizons = {sample["horizon"]["label"] for sample in samples}
    else:
        actual_horizons = {sample["expected_analysis"]["horizon"] for sample in samples}
    if actual_horizons != set(manifest["analysis_horizons"]):
        raise ContractError("analysis_horizons do not match samples")
    if manifest["review"]["status"] == "reviewed" and (
        not manifest["review"]["reviewer"] or not manifest["review"]["reviewed_at"]
    ):
        raise ContractError("reviewed dataset requires reviewer and reviewed_at")
    if evaluation_boundary is not None:
        _check_boundary(samples, outcomes_by_id, evaluation_boundary)

    summary = {
        "dataset_id": manifest["dataset_id"],
        "samples": len(samples),
        "outcomes": outcome_count,
    }
    if evaluation_boundary is not None:
        summary["evaluation_boundary"] = evaluation_boundary.isoformat().replace("+00:00", "Z")
    return summary


def _windows(samples: list[dict], outcomes_by_id: dict) -> dict:
    windows = {split: [] for split in SPLITS}
    for sample in samples:
        windows[sample["split"]].append(
            (timestamp(sample["as_of_timestamp"]), label_end(sample, outcomes_by_id.get(sample["sample_id"])))
        )
    return windows


def _check_boundary(samples: list[dict], outcomes_by_id: dict, boundary: datetime) -> None:
    if boundary.tzinfo is None:
        raise ContractError("evaluation boundary must include a timezone")
    for sample in samples:
        sample_id = sample["sample_id"]
        if timestamp(sample["as_of_timestamp"]) >= boundary:
            raise ContractError(f"sample cutoff is not before the evaluation boundary: {sample_id}")
        # A v1 dataset without outcomes cannot show where its labels end.
        if label_end(sample, outcomes_by_id.get(sample_id)) >= boundary:
            raise ContractError(f"label interval crosses the evaluation boundary: {sample_id}")


def _artifact_path(manifest_path: Path, entry: dict) -> Path:
    relative = Path(entry["path"])
    if relative.is_absolute():
        raise ContractError("artifact path must be relative to the manifest")
    base = manifest_path.resolve().parent
    artifact = (base / relative).resolve()
    try:
        artifact.relative_to(base)
    except ValueError as error:
        raise ContractError("artifact path escapes the manifest directory") from error
    return artifact


def _validate_artifact(path: Path, entry: dict, actual_count: int) -> None:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != entry["sha256"]:
        raise ContractError(f"artifact hash mismatch: {entry['path']}")
    if actual_count != entry["count"]:
        raise ContractError(f"artifact count mismatch: {entry['path']}")


def _validate_splits(samples: list[dict], declared: dict) -> None:
    by_split = {split: [] for split in SPLITS}
    for sample in samples:
        by_split[sample["split"]].append(timestamp(sample["as_of_timestamp"]))
    for split, cutoffs in by_split.items():
        summary = declared[split]
        if summary["sample_count"] != len(cutoffs):
            raise ContractError(f"split count mismatch: {split}")
        if not cutoffs:
            if summary["as_of_start"] is not None or summary["as_of_end"] is not None:
                raise ContractError(f"empty split must have null boundaries: {split}")
            continue
        if summary["as_of_start"] is None or summary["as_of_end"] is None:
            raise ContractError(f"non-empty split requires boundaries: {split}")
        if timestamp(summary["as_of_start"]) != min(cutoffs):
            raise ContractError(f"split start mismatch: {split}")
        if timestamp(summary["as_of_end"]) != max(cutoffs):
            raise ContractError(f"split end mismatch: {split}")
