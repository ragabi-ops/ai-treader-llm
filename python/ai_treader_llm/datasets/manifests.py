from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from pathlib import Path

from ai_treader_llm.contracts import ContractError, Contracts, timestamp
from ai_treader_llm.datasets.outcomes import validate_outcomes
from ai_treader_llm.datasets.samples import read_jsonl, validate_dataset


SPLITS = ("train", "validation", "test")


def validate_manifest(path: Path, contracts: Contracts) -> dict:
    try:
        manifest = json.loads(path.read_text())
    except json.JSONDecodeError as error:
        raise ContractError(f"{path}: invalid JSON") from error
    if not isinstance(manifest, dict):
        raise ContractError(f"{path}: expected an object")
    contracts.validate("dataset-manifest.schema.json", manifest)

    sample_path = _artifact_path(path, manifest["samples"])
    samples = read_jsonl(sample_path)
    _validate_artifact(sample_path, manifest["samples"], len(samples))

    outcome_entry = manifest["outcomes"]
    if outcome_entry is None:
        validate_dataset(samples, contracts)
        if manifest["split_policy"]["outcome_window_purged"]:
            raise ContractError("outcome_window_purged requires an outcome artifact")
        if manifest["split_policy"]["embargo_days"] != 0:
            raise ContractError("embargo requires an outcome artifact")
        outcome_count = 0
    else:
        outcome_path = _artifact_path(path, outcome_entry)
        outcomes = read_jsonl(outcome_path)
        _validate_artifact(outcome_path, outcome_entry, len(outcomes))
        if not manifest["split_policy"]["outcome_window_purged"]:
            raise ContractError("outcome artifact requires outcome_window_purged")
        validate_outcomes(
            samples,
            outcomes,
            contracts,
            embargo=timedelta(days=manifest["split_policy"]["embargo_days"]),
        )
        outcome_count = len(outcomes)

    _validate_splits(samples, manifest["splits"])
    actual_horizons = {sample["expected_analysis"]["horizon"] for sample in samples}
    if actual_horizons != set(manifest["analysis_horizons"]):
        raise ContractError("analysis_horizons do not match samples")
    if manifest["review"]["status"] == "reviewed" and (
        not manifest["review"]["reviewer"] or not manifest["review"]["reviewed_at"]
    ):
        raise ContractError("reviewed dataset requires reviewer and reviewed_at")

    return {
        "dataset_id": manifest["dataset_id"],
        "samples": len(samples),
        "outcomes": outcome_count,
    }


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
