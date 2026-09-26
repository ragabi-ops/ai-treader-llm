from __future__ import annotations

import math
from datetime import timedelta

from ai_treader_llm.contracts import ContractError, Contracts, timestamp
from ai_treader_llm.datasets.samples import validate_dataset


OUTCOME_FIELDS = (
    "return_1d",
    "return_5d",
    "return_30d",
    "return_90d",
    "max_drawdown",
    "volatility",
)


def validate_outcomes(
    samples: list[dict],
    outcomes: list[dict],
    contracts: Contracts,
    *,
    embargo: timedelta = timedelta(0),
) -> None:
    """Validate separately stored labels and purge overlapping split windows."""
    validate_dataset(samples, contracts)
    if embargo < timedelta(0):
        raise ContractError("embargo must not be negative")
    if not outcomes:
        raise ContractError("empty outcome dataset")

    samples_by_id = {sample["sample_id"]: sample for sample in samples}
    outcomes_by_id = {}
    for outcome in outcomes:
        contracts.validate("outcome-record.schema.json", outcome)
        sample_id = outcome["sample_id"]
        if sample_id in outcomes_by_id:
            raise ContractError(f"duplicate outcome: {sample_id}")
        if sample_id not in samples_by_id:
            raise ContractError(f"outcome for unknown sample: {sample_id}")
        if any(not math.isfinite(outcome[field]) for field in OUTCOME_FIELDS):
            raise ContractError(f"non-finite outcome value: {sample_id}")
        if timestamp(outcome["label_end_timestamp"]) <= timestamp(
            samples_by_id[sample_id]["as_of_timestamp"]
        ):
            raise ContractError(f"label end must follow sample cutoff: {sample_id}")
        outcomes_by_id[sample_id] = outcome

    missing = samples_by_id.keys() - outcomes_by_id.keys()
    if missing:
        raise ContractError(f"missing outcome: {min(missing)}")

    windows = {split: [] for split in ("train", "validation", "test")}
    for sample_id, sample in samples_by_id.items():
        windows[sample["split"]].append(
            (
                timestamp(sample["as_of_timestamp"]),
                timestamp(outcomes_by_id[sample_id]["label_end_timestamp"]),
            )
        )

    ordered = [values for values in windows.values() if values]
    for earlier, later in zip(ordered, ordered[1:]):
        latest_label_end = max(label_end for _, label_end in earlier)
        earliest_later_cutoff = min(cutoff for cutoff, _ in later)
        if latest_label_end + embargo > earliest_later_cutoff:
            raise ContractError("outcome windows cross split boundary or embargo")
