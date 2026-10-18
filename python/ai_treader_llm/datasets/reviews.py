"""Validation for real-source review receipts; source data stays outside Git."""
from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path

from ai_treader_llm.contracts import ContractError, Contracts, timestamp


def validate_source_review(
    path: Path, contracts: Contracts, *, source_root: Path | None = None
) -> dict:
    try:
        review = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ContractError(f"{path}: invalid JSON") from error
    if not isinstance(review, dict):
        raise ContractError(f"{path}: expected an object")
    contracts.validate("data-source-review-v1.schema.json", review)

    artifacts = review["artifacts"]
    paths = [artifact["path"] for artifact in artifacts]
    requests = [artifact["request"] for artifact in artifacts]
    if len(paths) != len(set(paths)):
        raise ContractError("duplicate reviewed artifact path")
    if len(requests) != len(set(requests)):
        raise ContractError("duplicate reviewed source request")
    if any(timestamp(artifact["retrieved_at"]) > timestamp(review["access"]["reviewed_at"])
           for artifact in artifacts):
        raise ContractError("source review predates an artifact retrieval")
    if timestamp(review["access"]["reviewed_at"]) > timestamp(review["created_at"]):
        raise ContractError("source review follows receipt creation")

    readiness = review["target_readiness"]
    controls = (
        "platform_listing_ids_pinned",
        "trading_calendar_pinned",
        "chronological_splits_pinned",
        "purge_embargo_pinned",
        "held_out_boundary_pinned",
    )
    ready = all(readiness[field] for field in controls)
    if (readiness["status"] == "ready") != ready:
        raise ContractError("target readiness disagrees with required controls")

    if source_root is not None:
        root = source_root.resolve()
        manifest = _contained(root, review["source"]["capture_manifest_path"])
        manifest_bytes = _check_file(
            manifest,
            review["source"]["capture_manifest_sha256"],
            None,
        )
        _check_capture_manifest(manifest_bytes, artifacts)
        for artifact in artifacts:
            artifact_path = _contained(root, artifact["path"])
            compressed = _check_file(
                artifact_path,
                artifact["compressed_sha256"],
                artifact["compressed_bytes"],
            )
            try:
                content = gzip.decompress(compressed)
            except (OSError, EOFError) as error:
                raise ContractError(f"invalid gzip artifact: {artifact['path']}") from error
            _check_bytes(
                content,
                artifact["content_sha256"],
                artifact["content_bytes"],
                artifact["path"],
            )

    return {
        "review_id": review["review_id"],
        "artifacts": len(artifacts),
        "access_status": review["access"]["status"],
        "survivorship_status": review["universe"]["survivorship_status"],
        "target_status": readiness["status"],
        "bytes_verified": source_root is not None,
    }


def _contained(root: Path, relative_text: str) -> Path:
    relative = Path(relative_text)
    if relative.is_absolute():
        raise ContractError("reviewed artifact path must be relative")
    path = (root / relative).resolve()
    try:
        path.relative_to(root)
    except ValueError as error:
        raise ContractError("reviewed artifact path escapes source root") from error
    return path


def _check_file(path: Path, expected_hash: str, expected_size: int | None) -> bytes:
    try:
        value = path.read_bytes()
    except OSError as error:
        raise ContractError(f"cannot read reviewed artifact: {path.name}") from error
    _check_bytes(value, expected_hash, expected_size, path.name)
    return value


def _check_capture_manifest(value: bytes, artifacts: list[dict]) -> None:
    try:
        manifest = json.loads(value)
        pages = manifest["pages"]
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise ContractError("capture manifest must contain a pages array") from error
    if not isinstance(pages, list):
        raise ContractError("capture manifest pages must be an array")
    expected = {
        artifact["path"]: {
            "file": artifact["path"],
            "request": artifact["request"],
            "retrieved_at": artifact["retrieved_at"],
            "sha256": artifact["content_sha256"],
            "bytes": artifact["content_bytes"],
        }
        for artifact in artifacts
    }
    actual = {}
    for page in pages:
        if not isinstance(page, dict) or not isinstance(page.get("file"), str):
            raise ContractError("capture manifest contains an invalid page")
        if page["file"] in actual:
            raise ContractError("capture manifest contains a duplicate page")
        actual[page["file"]] = {key: page.get(key) for key in expected[next(iter(expected))]}
    if actual != expected:
        raise ContractError("capture manifest and source review disagree")


def _check_bytes(value: bytes, expected_hash: str, expected_size: int | None, name: str) -> None:
    if hashlib.sha256(value).hexdigest() != expected_hash:
        raise ContractError(f"reviewed artifact hash mismatch: {name}")
    if expected_size is not None and len(value) != expected_size:
        raise ContractError(f"reviewed artifact size mismatch: {name}")
