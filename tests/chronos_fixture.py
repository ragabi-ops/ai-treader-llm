"""Synthetic platform-daily-series-v1 export and fake Chronos weights for the ALPHA03 Chronos tests.

Weekday sessions without holidays and random-walk closes; not a real calendar,
dataset, model or performance claim. Listing 6 starts trading late (short context);
listing 5 has one stale decision.
"""
from __future__ import annotations

import random
from datetime import date, datetime, timedelta

from alpha_fixture import CREATED, fridays, month_end, sessions, text, utc
from ai_treader_llm import numeric as n
from ai_treader_llm.chronos import provenance, series, weights
from ai_treader_llm.numeric_fixtures import dump, entry, jsonl, sha

LISTINGS = ('1', '2', '3', '4', '5', '6')
LATE_START = '2020-12-01'


def closes(schedule: list[dict], seed: int) -> dict:
    rng = random.Random(seed)
    out = {}
    for listing in LISTINGS:
        price, path = 100.0, {}
        for session in schedule:
            if listing == '6' and session['session'] < LATE_START:
                continue
            price *= 1 + rng.gauss(0.0004, 0.015)
            path[session['session']] = float(text(price))
        out[listing] = path
    return out


def build(directory, decisions: int = 40, skip: int = 0, seed: int = 11) -> dict:
    """Writes calendar/input/features for `decisions` Fridays after the first `skip`; returns paths and closes."""
    schedule = sessions(date(2020, 1, 1), date(2022, 6, 30))
    calendar = n.seal({'schema_version': 'numeric-calendar-v1', 'calendar_id': 'synthetic-weekdays-v1', 'exchange': 'XNYS',
                       'coverage_start': schedule[0]['session'], 'coverage_end': schedule[-1]['session'], 'sessions': schedule})
    schema = {'version': series.FEATURE_VERSION, 'features': [
        {'feature_id': key, 'unit': 'ratio', 'definition_sha256': sha('synthetic-' + key)} for key in series.FEATURE_IDS]}
    schema['feature_schema_sha256'] = n.digest(schema, 'feature_schema_sha256')
    prices = closes(schedule, seed)
    days = [s for s in fridays(schedule, 200) if s['session'] >= '2021-01-04'][skip:skip + decisions]
    index = {s['session']: i for i, s in enumerate(schedule)}
    scopes, features = [], []
    for d, day in enumerate(days):
        i = index[day['session']]
        follow = schedule[i + 1]
        cutoff = utc(datetime.fromisoformat(follow['open_at'].replace('Z', '+00:00')) - timedelta(seconds=1))
        end = month_end(schedule, day['session'])
        for listing in LISTINGS:
            row_id = f'c{listing}-{day["session"]}'
            scopes.append({'row_id': row_id, 'listing_id': listing, 'as_of_timestamp': cutoff, 'horizon': {
                'label': '1m', 'policy': 'xnys-calendar-months-next-open-v1', 'calendar_sha256': calendar['calendar_sha256'],
                'decision_session': day['session'], 'entry_session': follow['session'], 'entry_at': follow['open_at'],
                'end_session': end['session'], 'end_at': end['close_at']}})
            source = {'source_id': 'prices', 'revision': 'synthetic', 'content_sha256': sha(row_id), 'available_at': day['close_at'],
                      'ingested_at': CREATED, 'license': {'status': 'synthetic_only', 'reference': 'Generated test fixture.'}}
            stale = listing == '5' and skip + d == 4
            path = prices[listing]
            values = []
            for k in range(1, series.LAGS + 1):
                back = schedule[i - k]['session'] if i - k >= 0 else None
                if stale:
                    values.append({'status': 'unavailable', 'reason': 'stale'})
                elif back in path:
                    values.append({'status': 'available', 'value': text(path[back] / path[day['session']])})
                else:
                    values.append({'status': 'unavailable', 'reason': 'not_available_at_cutoff'})
            features.append({'schema_version': 'numeric-feature-row-v1', 'row_id': row_id, 'sources': [source], 'features': [
                {'feature_id': key, 'source_ids': ['prices'] if value['status'] == 'available' else [], 'value': value}
                for key, value in zip(series.FEATURE_IDS, values)]})
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'calendar.json').write_text(dump(calendar), encoding='utf-8')
    (directory / 'features.jsonl').write_text(jsonl(features), encoding='utf-8')
    inputs = n.seal({'schema_version': 'numeric-input-v1', 'dataset_id': f'synthetic-series-{skip}-{decisions}',
                     'created_at': CREATED, 'availability_policy': 'reconstructed',
                     'corporate_action_basis': 'total_return_adjusted', 'action_policy_sha256': sha('synthetic-actions'),
                     'universe': {'snapshot_sha256': sha('synthetic-universe'), 'membership_policy_sha256': sha('synthetic-membership'),
                                  'survivorship': 'survivorship_biased_pilot'},
                     'calendar': entry('calendar.json', dump(calendar), len(schedule)), 'feature_schema': schema,
                     'features': entry('features.jsonl', jsonl(features), len(features)), 'expected_rows': scopes})
    (directory / 'input-manifest.json').write_text(dump(inputs), encoding='utf-8')
    return {'input': directory / 'input-manifest.json', 'decisions': [day['session'] for day in days], 'closes': prices}


def fake_weights(directory) -> None:
    directory.mkdir(parents=True)
    for name, data in (('config.json', b'{"synthetic": true}'), ('model.safetensors', b'not a model')):
        (directory / name).write_bytes(data)
    provenance.write(directory / weights.MANIFEST, {
        'schema_version': weights.MANIFEST_VERSION, 'repository': weights.REPOSITORY, 'revision': '0' * 40,
        'license': weights.LICENSE, 'model_card': 'synthetic',
        'files': [{'path': name, 'bytes': (directory / name).stat().st_size,
                   'sha256': provenance.sha256((directory / name).read_bytes())} for name in weights.FILES]})


LEVELS = [float(level) for level in ('0.01', '0.05', '0.1', '0.15', '0.2', '0.25', '0.3', '0.35', '0.4', '0.45', '0.5',
                                     '0.55', '0.6', '0.65', '0.7', '0.75', '0.8', '0.85', '0.9', '0.95', '0.99')]


class FakeForecaster:
    """Momentum-centred quantiles that widen with the step; raises or returns NaN on named contexts."""

    def __init__(self, fail_lengths=(), nan_lengths=()):
        self.calls = []
        self.fail_lengths, self.nan_lengths = set(fail_lengths), set(nan_lengths)

    def __call__(self, path, step):
        self.calls.append((len(path), step))
        if len(path) in self.fail_lengths:
            raise RuntimeError('synthetic model failure')
        centre = 1 + 0.5 * (1 - path[max(0, len(path) - 21)])
        if len(path) in self.nan_lengths:
            centre = float('nan')
        width = 0.01 * step ** 0.5
        return [centre + width * (level - 0.5) * 4 for level in LEVELS]
