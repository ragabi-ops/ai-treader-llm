"""Contract v2: the trusted context envelope and structural claim grounding.

The platform (Go) implements the same checks in the same order and reports the
same codes; the shared fixtures in contracts/fixtures/v2 hold both to that. A
valid analysis is structurally grounded, not verified: its prose can still be
wrong about the sources it cites.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date

from ai_treader_llm.contracts import ContractError, Contracts
from ai_treader_llm.contracts import timestamp as _timestamp

CONTEXT_SCHEMA = "analysis-context-v2.schema.json"
ANALYSIS_SCHEMA = "analysis-v2.schema.json"

# Codes shared with the platform. Order of checks is part of the contract.
SCHEMA = "schema"
CONTEXT_HASH_MISMATCH = "context_hash_mismatch"
DUPLICATE_EVIDENCE = "duplicate_evidence"
DUPLICATE_METRIC = "duplicate_metric"
FUTURE_SOURCE = "future_source"
INGESTION_PRECEDES_AVAILABILITY = "ingestion_precedes_availability"
SOURCE_NOT_INGESTED = "source_not_ingested"
DUPLICATE_UNAVAILABLE_KIND = "duplicate_unavailable_kind"
UNAVAILABLE_KIND_HAS_SOURCES = "unavailable_kind_has_sources"
HORIZON_ORDER = "horizon_order"
TRUSTED_FIELD_MISMATCH = "trusted_field_mismatch"
GENERATION_PRECEDES_CUTOFF = "generation_precedes_cutoff"
UNKNOWN_EVIDENCE = "unknown_evidence"
UNKNOWN_METRIC = "unknown_metric"
METRIC_SOURCE_NOT_CITED = "metric_source_not_cited"
SECTION_KIND_MISMATCH = "section_kind_mismatch"
ABSTENTION_STATE_MISMATCH = "abstention_state_mismatch"
UNAVAILABLE_NOT_DECLARED = "unavailable_not_declared"
UNAVAILABLE_CONTRADICTS_CONTEXT = "unavailable_contradicts_context"

# A section must cite at least one source of a kind that can support it.
SECTION_KINDS = {
    "fundamentals": {"fundamentals", "filing", "earnings"},
    "technicals": {"price", "technicals"},
    "sentiment": {"news", "research"},
    "market_context": {"market_context", "price", "news"},
}
CLAIM_LISTS = ("bull_case", "bear_case", "catalysts", "risks")


class V2Error(ContractError):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code


def timestamp(value: str):
    try:
        return _timestamp(value)
    except ValueError as error:
        raise V2Error(SCHEMA, f"unparseable timestamp: {value}") from error


def session_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise V2Error(SCHEMA, f"unparseable session date: {value}") from error


def canonical_json(value: object) -> bytes:
    """Sorted keys, no whitespace, UTF-8, integers only.

    Floats are refused: their text form differs across languages, and nothing
    in the envelope needs one.
    """
    def check(node):
        if isinstance(node, float):
            raise V2Error(SCHEMA, "canonical JSON admits no fractional numbers")
        if isinstance(node, dict):
            for child in node.values():
                check(child)
        elif isinstance(node, list):
            for child in node:
                check(child)

    check(value)
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def context_hash(context: dict) -> str:
    body = {key: value for key, value in context.items() if key != "context_sha256"}
    return hashlib.sha256(canonical_json(body)).hexdigest()


def validate_schema(contracts: Contracts, name: str, value: object) -> None:
    try:
        contracts.validate(name, value)
    except V2Error:
        raise
    except ContractError as error:
        raise V2Error(SCHEMA, str(error)) from error


def validate_context(context: dict, contracts: Contracts) -> None:
    validate_schema(contracts, CONTEXT_SCHEMA, context)
    if context_hash(context) != context["context_sha256"]:
        raise V2Error(CONTEXT_HASH_MISMATCH, "context_sha256 does not match the envelope")
    validate_sources(context, context["sources"])


def validate_sources(envelope: dict, sources: list[dict]) -> None:
    """Checks shared by the envelope and a dataset sample carrying content."""
    cutoff = timestamp(envelope["as_of_timestamp"])
    evidence, metrics, kinds = set(), set(), set()
    for source in sources:
        evidence_id = source["evidence_id"]
        if evidence_id in evidence:
            raise V2Error(DUPLICATE_EVIDENCE, evidence_id)
        evidence.add(evidence_id)
        for metric in source["metric_ids"]:
            if metric in metrics:
                raise V2Error(DUPLICATE_METRIC, metric)
            metrics.add(metric)
        if timestamp(source["available_at"]) > cutoff:
            raise V2Error(FUTURE_SOURCE, evidence_id)
        if timestamp(source["ingested_at"]) < timestamp(source["available_at"]):
            raise V2Error(INGESTION_PRECEDES_AVAILABILITY, evidence_id)
        if envelope["replay_mode"] == "platform_replay" and timestamp(source["ingested_at"]) > cutoff:
            raise V2Error(SOURCE_NOT_INGESTED, evidence_id)
        kinds.add(source["kind"])
    unique_kinds(envelope["unavailable"])
    for item in envelope["unavailable"]:
        if item["kind"] in kinds:
            raise V2Error(UNAVAILABLE_KIND_HAS_SOURCES, item["kind"])
    horizon = envelope["horizon"]
    start = session_date(horizon["start_session"])
    end = session_date(horizon["end_session"])
    if not start < end:
        raise V2Error(HORIZON_ORDER, "end_session must follow start_session")
    if start > cutoff.date():
        raise V2Error(HORIZON_ORDER, "start_session follows the cutoff")
    if not timestamp(horizon["end_close"]) > cutoff:
        raise V2Error(HORIZON_ORDER, "end_close must follow the cutoff")
    if timestamp(horizon["end_close"]).date() != end:
        raise V2Error(HORIZON_ORDER, "end_close is not on end_session")


def unique_kinds(unavailable: list[dict]) -> None:
    seen = set()
    for item in unavailable:
        if item["kind"] in seen:
            raise V2Error(DUPLICATE_UNAVAILABLE_KIND, item["kind"])
        seen.add(item["kind"])


def validate_analysis(value: dict, context: dict, contracts: Contracts) -> None:
    validate_context(context, contracts)
    check_analysis(value, context, contracts)


def check_analysis(value: dict, context: dict, contracts: Contracts) -> None:
    """The analysis against an envelope already known to be valid."""
    validate_schema(contracts, ANALYSIS_SCHEMA, value)
    for field in ("listing_id", "symbol"):
        if value[field] != context[field]:
            raise V2Error(TRUSTED_FIELD_MISMATCH, field)
    if timestamp(value["as_of_timestamp"]) != timestamp(context["as_of_timestamp"]):
        raise V2Error(TRUSTED_FIELD_MISMATCH, "as_of_timestamp")
    if value["horizon"] != context["horizon"]["label"]:
        raise V2Error(TRUSTED_FIELD_MISMATCH, "horizon")
    if timestamp(value["timestamp"]) < timestamp(value["as_of_timestamp"]):
        raise V2Error(GENERATION_PRECEDES_CUTOFF, "timestamp")

    kind_of = {source["evidence_id"]: source["kind"] for source in context["sources"]}
    source_of = {
        metric: source["evidence_id"]
        for source in context["sources"]
        for metric in source["metric_ids"]
    }

    def claim(node: dict | None, where: str, section: str | None = None) -> None:
        if node is None:
            return
        for evidence_id in node["evidence_ids"]:
            if evidence_id not in kind_of:
                raise V2Error(UNKNOWN_EVIDENCE, f"{where}: {evidence_id}")
        for metric in node["metric_refs"]:
            if metric not in source_of:
                raise V2Error(UNKNOWN_METRIC, f"{where}: {metric}")
            if source_of[metric] not in node["evidence_ids"]:
                raise V2Error(METRIC_SOURCE_NOT_CITED, f"{where}: {metric}")
        if section and not {kind_of[e] for e in node["evidence_ids"]} & SECTION_KINDS[section]:
            raise V2Error(SECTION_KIND_MISMATCH, where)

    claim(value["thesis"], "thesis")
    for name in CLAIM_LISTS:
        for index, node in enumerate(value[name]):
            claim(node, f"{name}.{index}")
    for name in SECTION_KINDS:
        claim(value[name], name, section=name)

    if value["thesis"] is None and value["suggested_signal_state"] != "insufficient_evidence":
        raise V2Error(ABSTENTION_STATE_MISMATCH, "a signal without a thesis")

    unique_kinds(value["unavailable"])
    declared = {item["kind"] for item in value["unavailable"]}
    for item in context["unavailable"]:
        if item["kind"] not in declared:
            raise V2Error(UNAVAILABLE_NOT_DECLARED, item["kind"])
    present = set(kind_of.values())
    for item in value["unavailable"]:
        if item["kind"] in present:
            raise V2Error(UNAVAILABLE_CONTRADICTS_CONTEXT, item["kind"])
