from __future__ import annotations

import math
from datetime import datetime, timedelta

from ai_treader_llm.contracts import ContractError, Contracts, timestamp
from ai_treader_llm.datasets.samples import is_v2, validate_dataset


OUTCOME_FIELDS = (
    "return_1d",
    "return_5d",
    "return_30d",
    "return_90d",
    "max_drawdown",
    "volatility",
)
MEASURES_V2 = ("return", "max_drawdown", "volatility")
SPLITS = ("train", "validation", "test")


def validate_outcomes(
    samples: list[dict],
    outcomes: list[dict],
    contracts: Contracts,
    *,
    embargo: timedelta = timedelta(0),
    embargoed_starts: dict | None = None,
) -> None:
    """Validate separately stored labels and purge overlapping split windows.

    v1 embargoes are calendar days. v2 embargoes are sessions, which only the
    platform's calendar can count, so a v2 dataset states each later split's
    embargoed start as a timestamp and this checks the samples respect it.
    """
    validate_dataset(samples, contracts)
    if embargo < timedelta(0):
        raise ContractError("embargo must not be negative")
    if not outcomes:
        raise ContractError("empty outcome dataset")
    v2 = is_v2(samples[0])
    if v2 and embargo:
        raise ContractError("v2 embargo is stated as embargoed starts, not days")
    if not v2 and embargoed_starts is not None:
        raise ContractError("embargoed starts require v2 samples")

    samples_by_id = {sample["sample_id"]: sample for sample in samples}
    outcomes_by_id = {}
    for outcome in outcomes:
        if v2:
            _validate_outcome_v2(outcome, samples_by_id, contracts)
        else:
            _validate_outcome_v1(outcome, samples_by_id, contracts)
        sample_id = outcome["sample_id"]
        if sample_id in outcomes_by_id:
            raise ContractError(f"duplicate outcome: {sample_id}")
        outcomes_by_id[sample_id] = outcome

    missing = samples_by_id.keys() - outcomes_by_id.keys()
    if missing:
        raise ContractError(f"missing outcome: {min(missing)}")

    windows = {split: [] for split in SPLITS}
    for sample_id, sample in samples_by_id.items():
        windows[sample["split"]].append(
            (timestamp(sample["as_of_timestamp"]), label_end(sample, outcomes_by_id[sample_id]))
        )
    check_split_windows(windows, embargo=embargo, embargoed_starts=embargoed_starts)


def label_end(sample: dict, outcome: dict | None) -> datetime:
    """A v2 sample knows its label end; a v1 sample needs its outcome record."""
    if is_v2(sample):
        return timestamp(sample["horizon"]["end_close"])
    if outcome is None:
        raise ContractError(f"v1 label end requires an outcome: {sample['sample_id']}")
    return timestamp(outcome["label_end_timestamp"])


def check_split_windows(
    windows: dict, *, embargo: timedelta = timedelta(0), embargoed_starts: dict | None = None
) -> None:
    present = [split for split in SPLITS if windows[split]]
    for earlier, later in zip(present, present[1:]):
        latest_label_end = max(end for _, end in windows[earlier])
        earliest_later_cutoff = min(cutoff for cutoff, _ in windows[later])
        if latest_label_end + embargo > earliest_later_cutoff:
            raise ContractError("outcome windows cross split boundary or embargo")
        if embargoed_starts is None:
            continue
        stated = embargoed_starts.get(later)
        if stated is None:
            raise ContractError(f"missing embargoed start: {later}")
        stated = timestamp(stated)
        if stated < latest_label_end:
            raise ContractError(f"embargoed start precedes the earlier labels: {later}")
        if earliest_later_cutoff < stated:
            raise ContractError(f"sample precedes the embargoed start: {later}")


def _validate_outcome_v1(outcome: dict, samples_by_id: dict, contracts: Contracts) -> None:
    contracts.validate("outcome-record.schema.json", outcome)
    sample_id = outcome["sample_id"]
    if sample_id not in samples_by_id:
        raise ContractError(f"outcome for unknown sample: {sample_id}")
    if any(not math.isfinite(outcome[field]) for field in OUTCOME_FIELDS):
        raise ContractError(f"non-finite outcome value: {sample_id}")
    if timestamp(outcome["label_end_timestamp"]) <= timestamp(
        samples_by_id[sample_id]["as_of_timestamp"]
    ):
        raise ContractError(f"label end must follow sample cutoff: {sample_id}")


def _validate_outcome_v2(outcome: dict, samples_by_id: dict, contracts: Contracts) -> None:
    contracts.validate("outcome-record-v2.schema.json", outcome)
    sample_id = outcome["sample_id"]
    if sample_id not in samples_by_id:
        raise ContractError(f"outcome for unknown sample: {sample_id}")
    if outcome["horizon"] != samples_by_id[sample_id]["horizon"]:
        raise ContractError(f"outcome horizon differs from its sample: {sample_id}")
    for measure in MEASURES_V2:
        value = outcome[measure]["value"]
        if value is not None and not math.isfinite(value):
            raise ContractError(f"non-finite outcome value: {sample_id}")
    volatility = outcome["volatility"]["value"]
    if volatility is not None and volatility < 0:
        raise ContractError(f"negative volatility: {sample_id}")
