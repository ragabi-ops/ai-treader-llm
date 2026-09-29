"""Builds the shared contract v2 fixtures in contracts/fixtures/v2.

The platform vendors these files and runs its Go validator over them; this
repository runs the Python validator over the same files. Each invalid case
breaks exactly one rule, so both sides must agree on the code, not only on the
refusal. Regenerate with `python -m ai_treader_llm.contract_fixtures`; the tests
fail when the committed files drift from this builder.
"""
from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path

from ai_treader_llm.contracts_v2 import context_hash

FIXTURE_DIR = Path("contracts/fixtures/v2")
EXAMPLE_DIR = Path("examples/v2")
CASES_FILE = "analysis-cases.json"
VECTORS_FILE = "context-hash-vectors.json"

CONTENT = {
    "px-1": "Synthetic fixture: EXAMPLE closed at 101.25 on 2025-01-03.",
    "filing-1": "Synthetic fixture: quarterly revenue 1,200 (prior year 1,000).",
    "news-1": "Synthetic fixture: EXAMPLE scheduled an investor call.",
}


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _source(evidence_id, kind, event_at, available_at, ingested_at, revision, metric_ids):
    return {
        "evidence_id": evidence_id,
        "kind": kind,
        "event_at": event_at,
        "available_at": available_at,
        "ingested_at": ingested_at,
        "revision": revision,
        "content_sha256": _sha(CONTENT[evidence_id]),
        "metric_ids": metric_ids,
    }


def base_context() -> dict:
    return {
        "schema_version": "2",
        "listing_id": 101,
        "symbol": "EXAMPLE",
        "as_of_timestamp": "2025-01-03T21:00:00Z",
        "replay_mode": "platform_replay",
        # 2025-01-03 plus one calendar month is Monday 2025-02-03, a session.
        "horizon": {
            "label": "1m",
            "policy": "xnys-calendar-months-v1",
            "calendar": "xnys-2021-2027-v1",
            "start_session": "2025-01-03",
            "end_session": "2025-02-03",
            "end_close": "2025-02-03T21:00:00Z",
        },
        "sources": [
            _source("px-1", "price", "2025-01-03T21:00:00Z", "2025-01-03T21:00:00Z",
                    "2025-01-03T21:00:00Z", "tiingo-eod-1", ["px-1.close"]),
            _source("filing-1", "filing", "2024-11-01T12:00:00Z", "2024-11-01T12:05:00Z",
                    "2024-11-01T12:10:00Z", "0000000000-24-000001", ["filing-1.revenue"]),
            _source("news-1", "news", "2025-01-02T13:00:00Z", "2025-01-02T14:00:00Z",
                    "2025-01-02T14:01:00Z", "original", []),
        ],
        "unavailable": [{"kind": "earnings", "reason": "not_collected"}],
    }


def _claim(text, evidence_ids, metric_refs=()):
    return {"text": text, "evidence_ids": list(evidence_ids), "metric_refs": list(metric_refs)}


def base_analysis() -> dict:
    return {
        "schema_version": "2",
        "listing_id": 101,
        "symbol": "EXAMPLE",
        "timestamp": "2025-01-03T21:05:00Z",
        "as_of_timestamp": "2025-01-03T21:00:00Z",
        "horizon": "1m",
        "thesis": _claim("Revenue grew in the latest filing while price held.",
                         ["filing-1", "px-1"], ["filing-1.revenue"]),
        "bull_case": [_claim("Quarterly revenue rose year over year.", ["filing-1"], ["filing-1.revenue"])],
        "bear_case": [_claim("Coverage is thin: one news item.", ["news-1"])],
        "catalysts": [],
        "risks": [_claim("The scheduled call may reset expectations.", ["news-1"])],
        "fundamentals": _claim("Revenue increased versus the prior year.", ["filing-1"], ["filing-1.revenue"]),
        "technicals": _claim("The last close is the only price supplied.", ["px-1"], ["px-1.close"]),
        "sentiment": _claim("News flow is neutral.", ["news-1"]),
        "market_context": None,
        "confidence": "medium",
        "unavailable": [{"kind": "earnings", "reason": "not_collected"}],
        "suggested_signal_state": "neutral",
    }


def _sealed(context: dict) -> dict:
    context = {key: value for key, value in context.items() if key != "context_sha256"}
    return {"schema_version": context["schema_version"], "context_sha256": context_hash(context),
            **{key: value for key, value in context.items() if key != "schema_version"}}


def _case(name, description, expect, context_edit=None, analysis_edit=None, seal=True):
    context, analysis = base_context(), base_analysis()
    if context_edit:
        context_edit(context)
    if seal:
        context = _sealed(context)
    if analysis_edit:
        analysis_edit(analysis)
    return {"name": name, "description": description, "expect": expect,
            "context": context, "analysis": analysis}


def _abstain(a):
    a.update(thesis=None, bull_case=[], bear_case=[], catalysts=[], risks=[], fundamentals=None,
             technicals=None, sentiment=None, market_context=None, confidence="low",
             suggested_signal_state="insufficient_evidence")


def _set(path, value):
    def edit(node):
        *parents, last = path
        for part in parents:
            node = node[part]
        node[last] = value
    return edit


def cases() -> list[dict]:
    def late(c):
        c["replay_mode"] = "public_information"
        c["sources"][2]["ingested_at"] = "2026-09-26T12:00:00Z"

    def duplicate_evidence(c):
        c["sources"][2]["evidence_id"] = "filing-1"

    def duplicate_metric(c):
        c["sources"][0]["metric_ids"] = ["filing-1.revenue"]

    def hash_mismatch(c):
        c["context_sha256"] = "0" * 64

    return [
        _case("valid-full", "Every claim cites a known source; sections cite a kind that can support them.", "valid"),
        _case("valid-abstention", "No thesis and insufficient_evidence: the honest answer to thin evidence.",
              "valid", analysis_edit=_abstain),
        _case("valid-public-information-late-ingestion",
              "Public-information replay may collect a source after the cutoff; it was public before it.",
              "valid", context_edit=late),
        _case("invalid-context-unknown-field", "Envelopes reject unknown fields.", "schema",
              context_edit=_set(["returns"], "0.25")),
        _case("invalid-analysis-unknown-field", "Outputs reject unknown fields.", "schema",
              analysis_edit=_set(["price_target"], "120")),
        _case("invalid-uncited-claim", "A claim with no source is not grounded.", "schema",
              analysis_edit=_set(["bear_case", 0, "evidence_ids"], [])),
        _case("invalid-missing-data-strings", "v2 replaces free-text missing_data with typed unavailable.",
              "schema", analysis_edit=_set(["unavailable"], ["earnings"])),
        _case("invalid-timestamp-grammar", "Seconds are required: one grammar for both validators.", "schema",
              context_edit=_set(["as_of_timestamp"], "2025-01-03T21:00Z")),
        _case("invalid-session-date", "A date that matches the pattern but does not exist.", "schema",
              context_edit=_set(["horizon", "start_session"], "2025-02-30")),
        _case("invalid-fractional-listing", "Listing IDs are integers; the envelope carries no fractions.",
              "schema", context_edit=lambda c: c.update(listing_id=101.5, context_sha256="0" * 64), seal=False),
        _case("invalid-context-hash", "The envelope hash must cover exactly the envelope.",
              "context_hash_mismatch", context_edit=hash_mismatch, seal=False),
        _case("invalid-duplicate-evidence", "Evidence IDs are unique.", "duplicate_evidence",
              context_edit=duplicate_evidence),
        _case("invalid-duplicate-metric", "Metric IDs are unique across sources.", "duplicate_metric",
              context_edit=duplicate_metric),
        _case("invalid-future-source", "A source available after the cutoff cannot enter.", "future_source",
              context_edit=_set(["sources", 2, "available_at"], "2025-01-03T21:00:01Z")),
        _case("invalid-ingestion-precedes-availability", "Nothing is collected before it exists.",
              "ingestion_precedes_availability",
              context_edit=_set(["sources", 2, "ingested_at"], "2025-01-02T13:59:59Z")),
        _case("invalid-source-not-ingested", "Platform replay only sees what the platform held at the cutoff.",
              "source_not_ingested", context_edit=_set(["sources", 2, "ingested_at"], "2025-01-04T00:00:00Z")),
        _case("invalid-duplicate-unavailable-kind", "One reason per unavailable kind.",
              "duplicate_unavailable_kind",
              context_edit=_set(["unavailable"], [{"kind": "earnings", "reason": "not_collected"},
                                                  {"kind": "earnings", "reason": "stale"}])),
        _case("invalid-unavailable-kind-has-sources", "A kind cannot be both supplied and unavailable.",
              "unavailable_kind_has_sources",
              context_edit=_set(["unavailable"], [{"kind": "news", "reason": "stale"}])),
        _case("invalid-horizon-order", "The horizon ends after it starts.", "horizon_order",
              context_edit=_set(["horizon", "end_session"], "2025-01-02")),
        _case("invalid-listing-mismatch", "The output names the listing it was asked about.",
              "trusted_field_mismatch", analysis_edit=_set(["listing_id"], 102)),
        _case("invalid-horizon-mismatch", "3m is not the 1m horizon requested.", "trusted_field_mismatch",
              analysis_edit=_set(["horizon"], "3m")),
        _case("invalid-generation-precedes-cutoff", "An analysis cannot predate its evidence cutoff.",
              "generation_precedes_cutoff", analysis_edit=_set(["timestamp"], "2025-01-03T20:59:59Z")),
        _case("invalid-unknown-evidence", "A fabricated citation.", "unknown_evidence",
              analysis_edit=_set(["risks", 0, "evidence_ids"], ["news-9"])),
        _case("invalid-unknown-metric", "A fabricated metric.", "unknown_metric",
              analysis_edit=_set(["fundamentals", "metric_refs"], ["filing-1.margin"])),
        _case("invalid-metric-source-not-cited", "A metric's source must be among the claim's citations.",
              "metric_source_not_cited",
              analysis_edit=_set(["bull_case", 0, "metric_refs"], ["px-1.close"])),
        _case("invalid-section-kind", "Technicals supported only by news.", "section_kind_mismatch",
              analysis_edit=_set(["technicals"], _claim("Momentum is strong.", ["news-1"]))),
        _case("invalid-signal-without-thesis", "A directional or neutral signal needs a thesis.",
              "abstention_state_mismatch", analysis_edit=_set(["thesis"], None)),
        _case("invalid-unavailable-not-declared", "The output must acknowledge what it was not given.",
              "unavailable_not_declared", analysis_edit=_set(["unavailable"], [])),
        _case("invalid-unavailable-contradicts-context", "News was supplied; it cannot be unavailable.",
              "unavailable_contradicts_context",
              analysis_edit=_set(["unavailable"], [{"kind": "earnings", "reason": "not_collected"},
                                                   {"kind": "news", "reason": "stale"}])),
    ]


def hash_vectors() -> list[dict]:
    """Exact canonical-JSON hashes, including escapes both languages must agree on."""
    escapes = base_context()
    escapes["symbol"] = "EXAMPLE.é"
    escapes["sources"][2]["revision"] = 'quote " backslash \\ newline \n tab \t ctl \x01 del \x7f ls   clef \U0001d11e <&>'
    return [
        {"name": "base", "context": _sealed(base_context())},
        {"name": "escapes", "context": _sealed(escapes)},
    ]


TEST_CONTENT = {
    "px-1": "Synthetic fixture: EXAMPLE closed at 96.40 on 2025-03-07 after a weak week.",
    "filing-1": "Synthetic fixture: annual report restates segment margins; no revenue change.",
    "news-1": "Synthetic fixture: EXAMPLE named a new chief financial officer.",
}


def _sample(sample_id, split, context, analysis, content=CONTENT) -> dict:
    return {
        "schema_version": "2",
        "sample_id": sample_id,
        "listing_id": context["listing_id"],
        "symbol": context["symbol"],
        "as_of_timestamp": context["as_of_timestamp"],
        "replay_mode": context["replay_mode"],
        "horizon": context["horizon"],
        "split": split,
        "sources": [
            {**source, "content": content[source["evidence_id"]],
             "content_sha256": _sha(content[source["evidence_id"]])}
            for source in context["sources"]
        ],
        "unavailable": context["unavailable"],
        "task": "financial_analysis",
        "expected_analysis": analysis,
    }


def _measure(value=None, reason=None) -> dict:
    if reason is None:
        return {"status": "available", "value": value, "reason": None}
    return {"status": "unavailable", "value": None, "reason": reason}


def examples() -> dict[str, str]:
    """A two-sample v2 dataset whose test cutoff respects a 21-session embargo.

    The train label ends at the 2025-02-03 close; 21 XNYS sessions later
    (2025-02-17 is a holiday) is the 2025-03-05 close, the embargoed start. The
    test sample's 1m label is still pending, so its outcome is unavailable.
    """
    train_context = base_context()
    test_context = base_context()
    test_context.update(as_of_timestamp="2025-03-07T21:00:00Z")
    test_context["sources"][0].update(event_at="2025-03-07T21:00:00Z", available_at="2025-03-07T21:00:00Z",
                                      ingested_at="2025-03-07T21:00:00Z")
    test_context["horizon"].update(start_session="2025-03-07", end_session="2025-04-07",
                                   end_close="2025-04-07T20:00:00Z")
    test_analysis = base_analysis()
    test_analysis.update(as_of_timestamp="2025-03-07T21:00:00Z", timestamp="2025-03-07T21:05:00Z")
    samples = [
        _sample("synthetic-v2-001", "train", train_context, base_analysis()),
        _sample("synthetic-v2-002", "test", test_context, test_analysis, TEST_CONTENT),
    ]
    outcomes = [
        {"schema_version": "2", "sample_id": "synthetic-v2-001", "horizon": train_context["horizon"],
         "return": _measure(0.012), "max_drawdown": _measure(-0.031), "volatility": _measure(0.18)},
        {"schema_version": "2", "sample_id": "synthetic-v2-002", "horizon": test_context["horizon"],
         "return": _measure(reason="pending"), "max_drawdown": _measure(reason="pending"),
         "volatility": _measure(reason="pending")},
    ]

    def jsonl(rows):
        return "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)

    samples_text, outcomes_text = jsonl(samples), jsonl(outcomes)
    manifest = {
        "schema_version": "2",
        "dataset_id": "synthetic-fixture-v2",
        "created_at": "2026-09-29T00:00:00Z",
        "samples": {"path": "samples.jsonl", "sha256": _sha(samples_text), "count": 2},
        "outcomes": {"path": "outcomes.jsonl", "sha256": _sha(outcomes_text), "count": 2},
        "splits": {
            "train": {"sample_count": 1, "as_of_start": "2025-01-03T21:00:00Z",
                      "as_of_end": "2025-01-03T21:00:00Z"},
            "validation": {"sample_count": 0, "as_of_start": None, "as_of_end": None},
            "test": {"sample_count": 1, "as_of_start": "2025-03-07T21:00:00Z",
                     "as_of_end": "2025-03-07T21:00:00Z"},
        },
        "analysis_horizons": ["1m"],
        "split_policy": {
            "chronological": True,
            "outcome_window_purged": True,
            "calendar": "xnys-2021-2027-v1",
            "embargo_sessions": 21,
            "embargoed_starts": {"validation": None, "test": "2025-03-05T21:00:00Z"},
        },
        "licensing": {"status": "synthetic_only",
                      "notes": "Generated repository fixture; not financial training data."},
        "review": {"status": "synthetic_only", "reviewer": None, "reviewed_at": None},
    }
    return {
        "samples.jsonl": samples_text,
        "outcomes.jsonl": outcomes_text,
        "dataset-manifest.json": json.dumps(manifest, indent=2) + "\n",
        "context.json": json.dumps(_sealed(base_context()), indent=2) + "\n",
        "analysis.json": json.dumps(base_analysis(), indent=2) + "\n",
    }


def build() -> dict[Path, str]:
    def dump(value):
        return json.dumps(value, indent=2, ensure_ascii=False) + "\n"

    files = {
        FIXTURE_DIR / CASES_FILE: dump({"fixture_version": "1", "cases": cases()}),
        FIXTURE_DIR / VECTORS_FILE: dump({"fixture_version": "1", "vectors": hash_vectors()}),
    }
    files.update({EXAMPLE_DIR / name: text for name, text in examples().items()})
    return files


def main(root: Path = Path(".")) -> int:
    for path, text in build().items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(text)
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")))
