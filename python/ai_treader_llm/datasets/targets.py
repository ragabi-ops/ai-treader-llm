"""Validation for reviewed real-data analysis target plans."""
from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

from ai_treader_llm.contracts import ContractError, Contracts, timestamp

SPLITS = ("train", "validation", "test")
IDENTITY_FIELDS = ("listing_id", "cik", "symbol", "exchange", "security_label")


def validate_data_targets(
    path: Path, contracts: Contracts, *, platform_root: Path | None = None
) -> dict:
    value = _read_object(path)
    contracts.validate("data-analysis-targets-v1.schema.json", value)

    listings = value["universe"]["listings"]
    by_id = _unique(listings, "listing_id", "listing")
    _require_unique(listings, "cik", "listing CIK")
    _require_unique(listings, "symbol", "listing symbol")
    canonical_mapping = [
        {field: listing[field] for field in IDENTITY_FIELDS}
        for listing in sorted(listings, key=lambda item: item["listing_id"])
    ]
    mapping_hash = hashlib.sha256(
        json.dumps(
            canonical_mapping,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    if mapping_hash != value["platform"]["identity_snapshot"]["mapping_sha256"]:
        raise ContractError("identity mapping hash mismatch")

    targets = value["targets"]
    _unique(targets, "target_id", "target")
    tuples = set()
    cutoff_splits: dict[str, str] = {}
    split_targets = {split: [] for split in SPLITS}
    calendar = value["platform"]["calendar"]
    for target in targets:
        listing = by_id.get(target["listing_id"])
        if listing is None:
            raise ContractError(f"unknown target listing: {target['listing_id']}")
        if any(target[field] != listing[field] for field in ("cik", "symbol")):
            raise ContractError(f"target identity mismatch: {target['target_id']}")
        if target["replay_mode"] != value["availability"]["replay_mode"]:
            raise ContractError(f"target replay mode mismatch: {target['target_id']}")
        horizon = target["horizon"]
        if horizon["calendar"] != calendar["version"]:
            raise ContractError(f"target calendar mismatch: {target['target_id']}")
        if horizon["policy"] != calendar["horizon_policy"]:
            raise ContractError(f"target horizon policy mismatch: {target['target_id']}")
        if target["as_of_timestamp"][:10] != horizon["start_session"]:
            raise ContractError(f"target cutoff is not its start-session close: {target['target_id']}")
        if horizon["end_close"][:10] != horizon["end_session"]:
            raise ContractError(f"target end close is not on its end session: {target['target_id']}")
        if timestamp(horizon["end_close"]) <= timestamp(target["as_of_timestamp"]):
            raise ContractError(f"target horizon does not follow cutoff: {target['target_id']}")
        key = (target["listing_id"], target["as_of_timestamp"], horizon["label"])
        if key in tuples:
            raise ContractError("duplicate listing/cutoff/horizon target")
        tuples.add(key)
        prior = cutoff_splits.setdefault(target["as_of_timestamp"], target["split"])
        if prior != target["split"]:
            raise ContractError("one cutoff group appears in multiple splits")
        split_targets[target["split"]].append(target)

    if any(not split_targets[split] for split in SPLITS):
        raise ContractError("train, validation and test targets must all be present")
    for earlier, later in zip(SPLITS, SPLITS[1:]):
        if _latest_cutoff(split_targets[earlier]) >= _earliest_cutoff(split_targets[later]):
            raise ContractError("chronological target splits overlap")

    policy = value["split_policy"]
    evidence = _unique(policy["embargo_evidence"], "after_split", "embargo evidence")
    accumulated = []
    for index, split in enumerate(SPLITS):
        current = split_targets[split]
        if index:
            previous = SPLITS[index - 1]
            item = evidence.get(previous)
            if item is None:
                raise ContractError(f"missing embargo evidence after {previous}")
            latest_label_end = max(
                timestamp(target["horizon"]["end_close"]) for target in accumulated
            )
            if timestamp(item["latest_label_end"]) != latest_label_end:
                raise ContractError(f"latest label end mismatch after {previous}")
            boundary = timestamp(policy["embargoed_starts"][split])
            if timestamp(item["embargoed_start"]) != boundary:
                raise ContractError(f"embargoed start mismatch for {split}")
            if boundary <= latest_label_end or _earliest_cutoff(current) < boundary:
                raise ContractError(f"invalid purge/embargo boundary for {split}")
            sessions = [date.fromisoformat(session) for session in item["sessions_after_label_end"]]
            if len(sessions) != policy["embargo_sessions"]:
                raise ContractError(f"embargo session count mismatch after {previous}")
            if sessions != sorted(sessions) or len(sessions) != len(set(sessions)):
                raise ContractError(f"embargo sessions are not strictly ordered after {previous}")
            if sessions[0] <= latest_label_end.date() or sessions[-1] > boundary.date():
                raise ContractError(f"embargo session range mismatch after {previous}")
        accumulated.extend(current)
    if set(evidence) != {"train", "validation"}:
        raise ContractError("embargo evidence must cover train and validation boundaries")

    held_out = timestamp(policy["held_out_boundary"])
    if held_out != timestamp(policy["embargoed_starts"]["test"]):
        raise ContractError("held-out boundary must equal the protected test start")
    if _earliest_cutoff(split_targets["test"]) < held_out:
        raise ContractError("test target precedes held-out boundary")
    if any(
        timestamp(target["horizon"]["end_close"]) >= held_out
        for split in ("train", "validation")
        for target in split_targets[split]
    ):
        raise ContractError("selection label window reaches the held-out boundary")

    files_verified = False
    if platform_root is not None:
        root = platform_root.resolve()
        artifacts = [value["platform"]["identity_snapshot"]["source_fixture"]]
        artifacts.extend(value["platform"]["calendar"]["source_files"])
        for artifact in artifacts:
            artifact_path = _contained(root, artifact["path"])
            try:
                raw = artifact_path.read_bytes()
            except OSError as error:
                raise ContractError(f"cannot read platform artifact: {artifact['path']}") from error
            if hashlib.sha256(raw).hexdigest() != artifact["sha256"]:
                raise ContractError(f"platform artifact hash mismatch: {artifact['path']}")
        files_verified = True

    return {
        "target_set_id": value["target_set_id"],
        "targets": len(targets),
        "listings": len(listings),
        "splits": {split: len(split_targets[split]) for split in SPLITS},
        "held_out_boundary": policy["held_out_boundary"],
        "labels_included": value["labels"]["included"],
        "platform_files_verified": files_verified,
    }


def validate_target_source_link(
    target_path: Path,
    review: dict,
    contracts: Contracts,
    *,
    platform_root: Path | None = None,
) -> dict:
    value = _read_object(target_path)
    summary = validate_data_targets(target_path, contracts, platform_root=platform_root)
    if value["source_review_id"] != review["review_id"]:
        raise ContractError("target manifest and source review disagree")
    reviewed_paths = {artifact["path"] for artifact in review["artifacts"]}
    target_paths = {
        path
        for listing in value["universe"]["listings"]
        for path in listing["artifact_paths"]
    }
    if target_paths != reviewed_paths:
        raise ContractError("target manifest does not cover exactly the reviewed source artifacts")
    return summary


def _read_object(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ContractError(f"{path}: invalid JSON") from error
    if not isinstance(value, dict):
        raise ContractError(f"{path}: expected an object")
    return value


def _unique(rows: list[dict], field: str, label: str) -> dict:
    values = {}
    for row in rows:
        key = row[field]
        if key in values:
            raise ContractError(f"duplicate {label}: {key}")
        values[key] = row
    return values


def _require_unique(rows: list[dict], field: str, label: str) -> None:
    values = [row[field] for row in rows]
    if len(values) != len(set(values)):
        raise ContractError(f"duplicate {label}")


def _latest_cutoff(targets: list[dict]):
    return max(timestamp(target["as_of_timestamp"]) for target in targets)


def _earliest_cutoff(targets: list[dict]):
    return min(timestamp(target["as_of_timestamp"]) for target in targets)


def _contained(root: Path, relative_text: str) -> Path:
    relative = Path(relative_text)
    if relative.is_absolute():
        raise ContractError("platform artifact path must be relative")
    path = (root / relative).resolve()
    try:
        path.relative_to(root)
    except ValueError as error:
        raise ContractError("platform artifact path escapes platform root") from error
    return path
