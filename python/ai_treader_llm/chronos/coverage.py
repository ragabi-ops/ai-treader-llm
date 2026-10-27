"""Quantile coverage of Chronos forecasts on ALPHA03 development decisions only.

The realized close[end]/close[decision] comes from later rows of the same feature
exports (series.realized), so no label artifact is read. Rows outside the development
window, or whose horizon ends at or past the protocol fence, are refused: the 2025
retrospective window stays unread until platform ALPHA06 scores the frozen version.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from ai_treader_llm import numeric
from ai_treader_llm.chronos import provenance, series
from ai_treader_llm.numeric import fail

COVERAGE_VERSION = 'chronos-coverage-v1'
INTERVALS = (('0.25', '0.75'), ('0.1', '0.9'), ('0.05', '0.95'), ('0.01', '0.99'))


def load_quantiles(run_dir: Path, export: series.Export) -> list[dict]:
    forecast = numeric.read_json(run_dir / 'forecast.json')
    if forecast['input_manifest_sha256'] != export.inputs['input_manifest_sha256']:
        fail('provenance_mismatch', f'{run_dir} forecast was not made from this export')
    lines = (run_dir / 'quantiles.jsonl').read_text(encoding='utf-8').splitlines()
    records = [numeric.loads(line) for line in lines]
    available = {item['row_id'] for item in forecast['results'] if item['score']['status'] == 'available'}
    if {record['row_id'] for record in records} != available:
        fail('coverage', f'{run_dir} quantiles do not match the forecast\'s available rows')
    return records


def pinball(levels: list[float], quantiles: list[float], actual: float) -> float:
    return sum(max(q * (actual - value), (q - 1) * (actual - value)) for q, value in zip(levels, quantiles)) / len(levels)


def rate(hits: int, total: int) -> float | None:
    return round(hits / total, 6) if total else None


def merged_calendar(exports: list[series.Export]) -> dict:
    """One session list across exports whose calendar windows overlap and agree session by session."""
    calendars = sorted((export.calendar for export in exports), key=lambda item: item['coverage_start'])
    if len({(item['calendar_id'], item['exchange']) for item in calendars}) != 1:
        fail('calendar', 'exports name different calendars')
    sessions = {}
    for previous, current in zip(calendars, calendars[1:]):
        if current['coverage_start'] > previous['coverage_end']:
            fail('calendar', 'export calendar windows leave a gap')
    for item in calendars:
        for session in item['sessions']:
            if sessions.setdefault(session['session'], session) != session:
                fail('calendar', f'export calendars disagree on {session["session"]}')
    return {'sessions': [sessions[day] for day in sorted(sessions)]}


def evaluate(exports: list[series.Export], runs: list[list[dict]], params: dict, horizon: str) -> dict:
    windows = params['windows'][horizon]
    development, fence = windows['development'], windows['label_end_before']
    calendar = merged_calendar(exports)
    rows = [row for export in exports for row in export.rows]
    if len({row.row_id for row in rows}) != len(rows):
        fail('coverage', 'exports overlap')
    for row in rows:
        if not development['first'] <= row.decision <= development['last'] or row.end_session >= fence:
            fail('split_leakage', f'{row.row_id} is outside the {horizon} development window or past the fence {fence}')
    realized = series.realized(rows, calendar)
    records = [record for run in runs for record in run]
    levels = records[0]['quantile_levels'] if records else []
    level_values = [float(level) for level in levels]
    below = defaultdict(int)
    inside = {f'{low}-{high}': 0 for low, high in INTERVALS}
    yearly = defaultdict(lambda: [0, 0])
    losses, scored = [], 0
    for record in records:
        actual = realized.get(record['row_id'])
        if actual is None:
            continue
        scored += 1
        quantiles = [float(value) for value in record['ratio_quantiles']]
        by_level = dict(zip(levels, quantiles))
        for level, value in by_level.items():
            below[level] += actual <= value
        for low, high in INTERVALS:
            inside[f'{low}-{high}'] += by_level[low] <= actual <= by_level[high]
        year = yearly[record['decision_session'][:4]]
        year[0] += 1
        year[1] += by_level['0.1'] <= actual <= by_level['0.9']
        losses.append(pinball(level_values, quantiles, actual))
    return {
        'schema_version': COVERAGE_VERSION, 'horizon': horizon,
        'window': {'development': development, 'label_end_before': fence},
        'exports': [{'dataset_id': export.inputs['dataset_id'], 'input_manifest_sha256': export.inputs['input_manifest_sha256']}
                    for export in exports],
        'realized_source': 'later feature rows of the same exports; no label artifact read',
        'rows': {'expected': len(rows), 'forecast': len(records), 'realized': scored,
                 'forecast_without_realized': len(records) - scored},
        'intervals': {name: {'nominal': round(float(name.split('-')[1]) - float(name.split('-')[0]), 6),
                             'empirical': rate(hits, scored)} for name, hits in inside.items()},
        'quantile_hit_rates': {level: rate(below[level], scored) for level in levels},
        'mean_pinball_loss_ratio': round(sum(losses) / len(losses), 8) if losses else None,
        'interval_0.1-0.9_by_decision_year': {year: {'rows': n, 'empirical': rate(hits, n)}
                                              for year, (n, hits) in sorted(yearly.items())},
    }


def run(input_paths: list[Path], run_dirs: list[Path], params: dict, horizon: str, out: Path, contracts) -> dict:
    if len(input_paths) != len(run_dirs) or not input_paths:
        fail('coverage', 'pass one forecast run directory per input export')
    exports = [series.load(path, contracts) for path in input_paths]
    runs = [load_quantiles(run_dir, export) for run_dir, export in zip(run_dirs, exports)]
    report = evaluate(exports, runs, params, horizon)
    if out.exists():
        fail('artifact_mismatch', f'{out} exists; outputs are immutable')
    provenance.write(out, report)
    return report

