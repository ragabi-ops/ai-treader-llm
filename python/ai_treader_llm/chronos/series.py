"""platform-daily-series-v1 rows as Chronos contexts, forecast steps and realized ratios.

A row's features are close_ratio_lag_k = close[t-k]/close[t] (k = 1..256) on one
point-in-time view, so the path is scale-free and ends at 1 on the decision close t.
The context is the contiguous available run k = 1..m, oldest first, then 1.0.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ai_treader_llm import numeric
from ai_treader_llm.contracts import Contracts
from ai_treader_llm.numeric import fail

FEATURE_VERSION = 'platform-daily-series-v1'
LAGS = 256
FEATURE_IDS = tuple(f'close_ratio_lag_{k:03d}' for k in range(1, LAGS + 1))


@dataclass(frozen=True)
class Row:
    row_id: str
    listing_id: str
    decision: str
    end_session: str
    steps: int                 # XNYS sessions after the decision session through end_session
    lags: tuple                # lag_1..lag_256 as floats, None where unavailable
    first_missing: str | None  # reason of the first unavailable lag, if any


@dataclass(frozen=True)
class Export:
    path: Path
    inputs: dict
    calendar: dict
    rows: tuple


def load(path: Path, contracts: Contracts) -> Export:
    inputs, calendar, feature_rows = numeric.load_input(path, contracts)
    schema = inputs['feature_schema']
    if schema['version'] != FEATURE_VERSION or tuple(item['feature_id'] for item in schema['features']) != FEATURE_IDS:
        fail('provenance_mismatch', f'input is not a {FEATURE_VERSION} export with lags 1..{LAGS}')
    index = {session['session']: i for i, session in enumerate(calendar['sessions'])}
    by_row = {row['row_id']: row for row in feature_rows}
    rows = []
    for scope in inputs['expected_rows']:
        values = {item['feature_id']: item['value'] for item in by_row[scope['row_id']]['features']}
        lags = tuple(float(values[key]['value']) if values[key]['status'] == 'available' else None for key in FEATURE_IDS)
        first = next((values[key]['reason'] for key in FEATURE_IDS if values[key]['status'] != 'available'), None)
        horizon = scope['horizon']
        rows.append(Row(scope['row_id'], scope['listing_id'], horizon['decision_session'], horizon['end_session'],
                        index[horizon['end_session']] - index[horizon['decision_session']], lags, first))
    return Export(path, inputs, calendar, tuple(rows))


def available_lags(row: Row) -> int:
    """m: the length of the contiguous available run lag_1..lag_m."""
    m = 0
    while m < LAGS and row.lags[m] is not None:
        m += 1
    return m


def context(row: Row, min_lags: int) -> tuple[list[float] | None, str | None]:
    """The oldest-first ratio path ending at 1.0, or None with an unavailable reason."""
    m = available_lags(row)
    if m < min_lags:
        return None, 'missing_features'
    path = [row.lags[k] for k in range(m - 1, -1, -1)] + [1.0]
    if any(not value > 0 or value == float('inf') for value in path):
        return None, 'out_of_domain'
    return path, None


def realized(rows, calendar: dict) -> dict:
    """row_id -> realized close[end]/close[decision] read from a later row of the same listing.

    The later row is the listing's first row whose decision session is at or after
    end_session and whose view holds both closes; both lags come from that one view,
    so a later corporate-action adjustment cancels. Rows without one are absent.
    """
    index = {session['session']: i for i, session in enumerate(calendar['sessions'])}
    by_listing = {}
    for row in sorted(rows, key=lambda item: item.decision):
        by_listing.setdefault(row.listing_id, []).append(row)
    out = {}
    for row in rows:
        for later in by_listing[row.listing_id]:
            if later.decision < row.end_session:
                continue
            k_end = index[later.decision] - index[row.end_session]
            k_start = index[later.decision] - index[row.decision]
            if k_start > LAGS:
                break
            end = 1.0 if k_end == 0 else later.lags[k_end - 1]
            start = later.lags[k_start - 1]
            if end is not None and start is not None:
                out[row.row_id] = end / start
                break
    return out
