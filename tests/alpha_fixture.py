"""Synthetic platform-shaped numeric export and a small protocol for the ALPHA02 job tests.

Weekday sessions without holidays; not a real calendar, dataset or performance claim.
"""
from __future__ import annotations

import copy
from calendar import monthrange
import json
import random
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from ai_treader_llm import numeric as n
from ai_treader_llm.numeric_fixtures import dump, entry, jsonl, sha

ROOT = Path(__file__).resolve().parents[1]
FEATURES = ('return_1_session', 'return_5_sessions', 'return_20_sessions', 'volatility_20_sessions',
            'volume_ratio_20_sessions', 'trend_sma_20_50')
LISTINGS = ('1', '2', '3', '4', '5', '6')
CREATED = '2026-01-01T00:00:00Z'


def utc(moment: datetime) -> str:
    return moment.isoformat().replace('+00:00', 'Z')


def sessions(first: date, last: date) -> list[dict]:
    out, day = [], first
    while day <= last:
        if day.weekday() < 5:
            base = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
            out.append({'session': day.isoformat(), 'open_at': utc(base + timedelta(hours=14, minutes=30)),
                        'close_at': utc(base + timedelta(hours=21))})
        day += timedelta(days=1)
    return out


def month_end(schedule: list[dict], decision: str) -> dict:
    start = date.fromisoformat(decision)
    year, month = (start.year, start.month + 1) if start.month < 12 else (start.year + 1, 1)
    target = date(year, month, min(start.day, monthrange(year, month)[1])).isoformat()
    return next(s for s in schedule if s['session'] >= target)


def fridays(schedule: list[dict], count: int) -> list[dict]:
    return [s for s in schedule if date.fromisoformat(s['session']).weekday() == 4][:count]


def build(directory: Path, decisions: int = 60, seed: int = 7) -> dict:
    """Writes calendar/input/features/labels; returns paths and the decision sessions."""
    rng = random.Random(seed)
    schedule = sessions(date(2021, 1, 4), date(2022, 6, 30))
    calendar = n.seal({'schema_version': 'numeric-calendar-v1', 'calendar_id': 'synthetic-weekdays-v1', 'exchange': 'XNYS',
                       'coverage_start': schedule[0]['session'], 'coverage_end': schedule[-1]['session'], 'sessions': schedule})
    schema = {'version': 'platform-daily-v1', 'features': [
        {'feature_id': key, 'unit': 'ratio', 'definition_sha256': sha('synthetic-' + key)} for key in FEATURES]}
    schema['feature_schema_sha256'] = n.digest(schema, 'feature_schema_sha256')
    target_sha = sha('synthetic-target-v1')
    scopes, features, labels = [], [], []
    days = fridays(schedule, decisions)
    index = {s['session']: i for i, s in enumerate(schedule)}
    for d, day in enumerate(days):
        follow = schedule[index[day['session']] + 1]
        cutoff = utc(datetime.fromisoformat(follow['open_at'].replace('Z', '+00:00')) - timedelta(seconds=1))
        end = month_end(schedule, day['session'])
        for listing in LISTINGS:
            row_id = f'r{listing}-{day["session"]}'
            scope = {'row_id': row_id, 'listing_id': listing, 'as_of_timestamp': cutoff, 'horizon': {
                'label': '1m', 'policy': 'xnys-calendar-months-next-open-v1', 'calendar_sha256': calendar['calendar_sha256'],
                'decision_session': day['session'], 'entry_session': follow['session'], 'entry_at': follow['open_at'],
                'end_session': end['session'], 'end_at': end['close_at']}}
            scopes.append(scope)
            values = [rng.gauss(0, 0.05) for _ in FEATURES]
            source = {'source_id': 'prices', 'revision': 'synthetic', 'content_sha256': sha(row_id), 'available_at': day['close_at'],
                      'ingested_at': CREATED, 'license': {'status': 'synthetic_only', 'reference': 'Generated test fixture.'}}
            warmup = listing == '6' and d < 3
            features.append({'schema_version': 'numeric-feature-row-v1', 'row_id': row_id, 'sources': [source], 'features': [
                {'feature_id': key, 'source_ids': [] if warmup and key == 'trend_sma_20_50' else ['prices'],
                 'value': {'status': 'unavailable', 'reason': 'not_available_at_cutoff'} if warmup and key == 'trend_sma_20_50'
                 else {'status': 'available', 'value': text(value)}} for key, value in zip(FEATURES, values)]})
            y = 0.6 * values[2] - 0.4 * values[3] + rng.gauss(0, 0.02)
            missing = listing == '5' and d in (10, 11)
            labels.append({'schema_version': 'numeric-label-v1', **copy.deepcopy(scope), 'target_definition_sha256': target_sha,
                           'available_at': CREATED, 'sources': [{**source, 'source_id': 'label-prices', 'available_at': end['close_at']}],
                           'label': {'status': 'unavailable', 'reason': 'provider_error'} if missing
                           else {'status': 'available', 'value': text(y)}})
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'calendar.json').write_text(dump(calendar), encoding='utf-8')
    (directory / 'features.jsonl').write_text(jsonl(features), encoding='utf-8')
    (directory / 'labels.jsonl').write_text(jsonl(labels), encoding='utf-8')
    inputs = n.seal({'schema_version': 'numeric-input-v1', 'dataset_id': f'synthetic-alpha-{decisions}', 'created_at': CREATED,
                     'availability_policy': 'reconstructed', 'corporate_action_basis': 'total_return_adjusted',
                     'action_policy_sha256': sha('synthetic-actions'), 'universe': {
                         'snapshot_sha256': sha('synthetic-universe'), 'membership_policy_sha256': sha('synthetic-membership'),
                         'survivorship': 'survivorship_biased_pilot'},
                     'calendar': entry('calendar.json', dump(calendar), len(schedule)), 'feature_schema': schema,
                     'features': entry('features.jsonl', jsonl(features), len(features)), 'expected_rows': scopes})
    (directory / 'input-manifest.json').write_text(dump(inputs), encoding='utf-8')
    return {'input': directory / 'input-manifest.json', 'labels': directory / 'labels.jsonl',
            'labels_sha256': sha(jsonl(labels)), 'decisions': [day['session'] for day in days],
            'last_end': max(scope['horizon']['end_session'] for scope in scopes)}


def text(value: float) -> str:
    out = f'{value:.12f}'.rstrip('0').rstrip('.')
    return '0' if out in ('-0', '') else out


def protocol(directory: Path, fixture: dict, *, g_grid: dict | None = None) -> tuple[Path, str]:
    """The frozen parameters reshaped to the fixture's dates, with a small trial budget."""
    params = json.loads((ROOT / 'configs/numeric/alpha03-parameters.json').read_text(encoding='utf-8'))
    d = fixture['decisions']

    def span(first, last):
        return {'first': d[first], 'last': d[last], 'decisions': last - first + 1}
    params['universe'] = [{'symbol': f'S{i}'} for i in LISTINGS]
    params['arms']['R'].update(alpha=[1, 100], trials=2)
    grid = g_grid or {'feature_fraction': [0.7, 1], 'lambda_l2': [0, 1], 'learning_rate': [0.1], 'min_data_in_leaf': [5, 10],
                      'n_estimators': [20, 40], 'num_leaves': [3, 7]}
    params['arms']['G'].update(grid=grid, grid_keys=sorted(grid), trials=3)
    params['windows'] = {'embargo_sessions': 5, 'purge': params['windows']['purge'], '1m': {
        'development': span(0, len(d) - 1), 'label_end_before': (date.fromisoformat(fixture['last_end']) + timedelta(days=1)).isoformat(),
        'validation_folds': [{'train': span(0, 19), 'validation': span(27, 38)}, {'train': span(0, 31), 'validation': span(39, 50)}],
        'retrospective_test': {'first': '2099-01-02', 'last': '2099-12-31', 'decisions': 1}}}
    path = directory / 'protocol.json'
    data = json.dumps(params, indent=2).encode('utf-8')
    path.write_bytes(data)
    return path, sha(data.decode('utf-8'))
