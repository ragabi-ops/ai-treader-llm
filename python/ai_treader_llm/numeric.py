"""Numeric v1 contracts. Offline validation only; no fitting or financial calculation.

Numeric JSON uses string int64 IDs and exact decimal strings. The platform is the
trusted producer of calendars, features, labels, requests and policy definitions.
Validation proves internal consistency, never authenticity or predictive quality.
"""
from __future__ import annotations

import calendar as month_calendar
import hashlib
import json
from datetime import date
from pathlib import Path

from ai_treader_llm.contracts import ContractError, Contracts, timestamp

HASH_FIELDS = {
    'numeric-calendar-v1': 'calendar_sha256',
    'numeric-input-v1': 'input_manifest_sha256',
    'numeric-dataset-v1': 'dataset_manifest_sha256',
    'alpha-forecast-v1': 'forecast_sha256',
}
SCOPE_FIELDS = ('row_id', 'listing_id', 'as_of_timestamp', 'horizon')
ERROR_CODES = (
    'invalid_json', 'schema', 'hash_mismatch', 'calendar', 'coverage',
    'identity_mismatch', 'provenance_mismatch', 'source_availability',
    'source_reference', 'feature_coverage', 'label_maturity', 'split_leakage',
    'artifact_mismatch', 'generation_time',
)


class NumericError(ContractError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f'{code}: {message}')


def fail(code: str, message: str) -> None:
    raise NumericError(code, message)


def canonical_json(value: object) -> bytes:
    """Sorted UTF-8 scalar keys, compact JSON, no floats or unsafe integers.

    Strings are not normalized. Control escapes are lowercase; DEL, non-ASCII,
    U+2028/U+2029 and HTML characters are emitted literally. No BOM/newline.
    """
    def check(node):
        if node is None or type(node) is bool:
            return
        if type(node) is int:
            if abs(node) > 9007199254740991:
                fail('schema', 'JSON integer exceeds the interoperable range; use a string')
        elif isinstance(node, str):
            if any(0xD800 <= ord(char) <= 0xDFFF for char in node):
                fail('schema', 'unpaired Unicode surrogate')
        elif isinstance(node, list):
            for child in node:
                check(child)
        elif isinstance(node, dict):
            for key, child in node.items():
                if not isinstance(key, str):
                    fail('schema', 'object keys must be strings')
                check(key)
                check(child)
        else:
            fail('schema', 'JSON floats and non-JSON types are forbidden')
    check(value)
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode('utf-8')


def loads(text: str) -> object:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                fail('invalid_json', f'duplicate key: {key}')
            result[key] = value
        return result

    def reject(value):
        fail('invalid_json', f'fractional/exponent/non-finite JSON number: {value}')
    try:
        value = json.loads(text, object_pairs_hook=pairs, parse_float=reject, parse_constant=reject)
        canonical_json(value)
        return value
    except (ValueError, UnicodeError, RecursionError) as error:
        if isinstance(error, NumericError):
            raise
        raise NumericError('invalid_json', 'invalid UTF-8 JSON document') from error


def read_json(path: Path) -> object:
    try:
        return loads(path.read_text(encoding='utf-8'))
    except UnicodeError as error:
        raise NumericError('invalid_json', f'{path.name}: invalid UTF-8') from error


def digest(value: dict, field: str) -> str:
    return hashlib.sha256(canonical_json({k: v for k, v in value.items() if k != field})).hexdigest()


def artifact_hash(value: dict) -> str:
    version = value.get('schema_version')
    if version not in HASH_FIELDS:
        fail('schema', 'no self-hash defined for this artifact type')
    return digest(value, HASH_FIELDS[version])


def seal(value: dict) -> dict:
    return {**value, HASH_FIELDS[value['schema_version']]: artifact_hash(value)}


def schema(value: object, version: str, contracts: Contracts) -> None:
    canonical_json(value)
    try:
        contracts.validate(f'{version}.schema.json', value)
    except ContractError as error:
        raise NumericError('schema', str(error)) from error

    def check_ids(node):
        if isinstance(node, dict):
            for key, child in node.items():
                if key in ('listing_id', 'benchmark_listing_id') and int(child) > 9223372036854775807:
                    fail('schema', f'{key} exceeds signed int64')
                check_ids(child)
        elif isinstance(node, list):
            for child in node:
                check_ids(child)
    check_ids(value)


def check_hash(value: dict) -> None:
    if artifact_hash(value) != value[HASH_FIELDS[value['schema_version']]]:
        fail('hash_mismatch', value['schema_version'])


def indexed(rows: list[dict], field: str, code: str = 'coverage') -> dict:
    result = {}
    for row in rows:
        key = row[field]
        if key in result:
            fail(code, f'duplicate {field}: {key}')
        result[key] = row
    return result


def same_keys(actual: dict, expected: dict, code: str = 'coverage') -> None:
    if actual.keys() != expected.keys():
        fail(code, 'missing or extra identifiers')


def validate_calendar(value: dict, contracts: Contracts) -> None:
    schema(value, 'numeric-calendar-v1', contracts)
    check_hash(value)
    if value['coverage_start'] > value['coverage_end']:
        fail('calendar', 'reversed coverage')
    previous = None
    for session in value['sessions']:
        day = session['session']
        if not value['coverage_start'] <= day <= value['coverage_end']:
            fail('calendar', 'session outside coverage')
        if previous is not None and day <= previous:
            fail('calendar', 'sessions must be unique and chronological')
        opening, close = timestamp(session['open_at']), timestamp(session['close_at'])
        if opening.date().isoformat() != day or close.date().isoformat() != day or opening >= close:
            fail('calendar', 'session times must be ordered on their UTC session date')
        previous = day


def validate_horizon(scope: dict, calendar: dict) -> None:
    horizon, cutoff = scope['horizon'], timestamp(scope['as_of_timestamp'])
    if horizon['calendar_sha256'] != calendar['calendar_sha256']:
        fail('calendar', 'horizon calendar hash mismatch')
    if not calendar['coverage_start'] <= cutoff.date().isoformat() <= calendar['coverage_end']:
        fail('calendar', 'cutoff outside calendar coverage')
    sessions = calendar['sessions']
    closed = [s for s in sessions if timestamp(s['close_at']) <= cutoff]
    future = [s for s in sessions if timestamp(s['open_at']) > cutoff]
    if not closed or not future:
        fail('calendar', 'calendar must cover the decision and executable entry')
    decision, entry = closed[-1], future[0]
    start = date.fromisoformat(decision['session'])
    months = {'1m': 1, '3m': 3}[horizon['label']]
    month_index = start.year * 12 + start.month - 1 + months
    year, month = month_index // 12, month_index % 12 + 1
    if year > 9999:
        fail('calendar', 'horizon exceeds supported dates')
    target = date(year, month, min(start.day, month_calendar.monthrange(year, month)[1])).isoformat()
    endings = [s for s in sessions if s['session'] >= target]
    if not endings:
        fail('calendar', 'calendar does not cover the calendar-month horizon')
    end = endings[0]
    expected = {
        'decision_session': decision['session'], 'entry_session': entry['session'],
        'entry_at': entry['open_at'], 'end_session': end['session'], 'end_at': end['close_at'],
    }
    if any(horizon[key] != val for key, val in expected.items()) or timestamp(horizon['end_at']) <= timestamp(horizon['entry_at']):
        fail('calendar', 'horizon differs from pinned calendar-month / next-open policy')


def validate_input(value: dict, calendar: dict, rows: list[dict], contracts: Contracts) -> None:
    schema(value, 'numeric-input-v1', contracts)
    for row in rows:
        schema(row, 'numeric-feature-row-v1', contracts)
    validate_calendar(calendar, contracts)
    check_hash(value)
    if value['calendar']['count'] != len(calendar['sessions']) or value['features']['count'] != len(rows):
        fail('artifact_mismatch', 'declared record count mismatch')
    features = value['feature_schema']
    if features['feature_schema_sha256'] != digest(features, 'feature_schema_sha256'):
        fail('hash_mismatch', 'feature_schema')
    definitions = indexed(features['features'], 'feature_id', 'feature_coverage')
    expected = indexed(value['expected_rows'], 'row_id')
    actual = indexed(rows, 'row_id')
    same_keys(actual, expected)
    scopes = set()
    for scope in value['expected_rows']:
        key = (scope['listing_id'], timestamp(scope['as_of_timestamp']), scope['horizon']['label'], scope['horizon']['calendar_sha256'])
        if key in scopes:
            fail('coverage', 'duplicate listing/cutoff/horizon')
        scopes.add(key)
        if timestamp(scope['as_of_timestamp']) > timestamp(value['created_at']):
            fail('generation_time', 'input created before its cutoff')
        validate_horizon(scope, calendar)
        row = actual[scope['row_id']]
        sources = validate_sources(row['sources'], scope['as_of_timestamp'], value['availability_policy'])
        if any(timestamp(source['ingested_at']) > timestamp(value['created_at']) for source in sources.values()):
            fail('source_availability', 'source ingested after input creation')
        supplied = indexed(row['features'], 'feature_id', 'feature_coverage')
        same_keys(supplied, definitions, 'feature_coverage')
        for feature in row['features']:
            refs = feature['source_ids']
            if not set(refs) <= sources.keys():
                fail('source_reference', 'unknown feature source')
            if feature['value']['status'] == 'available':
                if not refs:
                    fail('source_reference', 'available feature requires source provenance')
                if any(sources[ref]['license']['status'] == 'restricted' for ref in refs):
                    fail('source_reference', 'restricted source cannot support an available feature')


def validate_sources(rows: list[dict], cutoff: str | None = None, policy: str = 'reconstructed') -> dict:
    sources = indexed(rows, 'source_id', 'source_reference')
    for source in rows:
        available, ingested = timestamp(source['available_at']), timestamp(source['ingested_at'])
        if ingested < available:
            fail('source_availability', 'ingestion precedes availability')
        if cutoff is not None:
            if available > timestamp(cutoff):
                fail('source_availability', 'source available after cutoff')
            if policy == 'observed' and ingested > timestamp(cutoff):
                fail('source_availability', 'source not ingested at cutoff')
    return sources


def validate_semantics(value: dict) -> None:
    unit = 'decimal_return' if value['kind'] == 'expected_excess_return' else 'unitless'
    if value['unit'] != unit:
        fail('provenance_mismatch', 'score kind/unit mismatch')


def validate_request(request: dict, inputs: dict, contracts: Contracts) -> None:
    schema(request, 'alpha-request-v1', contracts)
    for field, expected in (
        ('input_manifest_sha256', inputs['input_manifest_sha256']),
        ('feature_schema_sha256', inputs['feature_schema']['feature_schema_sha256']),
    ):
        if request[field] != expected:
            fail('provenance_mismatch', field)
    validate_semantics(request['score_semantics'])
    requested, deadline = timestamp(request['requested_at']), timestamp(request['deadline_at'])
    if requested >= deadline or requested < timestamp(inputs['created_at']):
        fail('generation_time', 'request must follow input creation and precede deadline')


def validate_forecast(value: dict, request: dict, inputs: dict, calendar: dict,
                      rows: list[dict], contracts: Contracts) -> None:
    validate_input(inputs, calendar, rows, contracts)
    validate_request(request, inputs, contracts)
    schema(value, 'alpha-forecast-v1', contracts)
    check_hash(value)
    for field in ('batch_id', 'attempt_id', 'input_manifest_sha256', 'feature_schema_sha256', 'model', 'score_semantics'):
        if value[field] != request[field]:
            fail('provenance_mismatch', field)
    if not timestamp(request['requested_at']) <= timestamp(value['generated_at']) <= timestamp(request['deadline_at']):
        fail('generation_time', 'forecast outside request interval')
    expected = indexed(inputs['expected_rows'], 'row_id')
    actual = indexed(value['results'], 'row_id')
    same_keys(actual, expected)
    for key, row in actual.items():
        if any(row[field] != expected[key][field] for field in SCOPE_FIELDS):
            fail('identity_mismatch', key)


def check_label(label: dict, scope: dict, target_sha256: str, created) -> None:
    if any(label[field] != scope[field] for field in SCOPE_FIELDS):
        fail('identity_mismatch', scope['row_id'])
    if label['target_definition_sha256'] != target_sha256:
        fail('provenance_mismatch', 'label target definition')
    sources = validate_sources(label['sources'])
    availability = timestamp(label['available_at'])
    if availability > created or any(timestamp(s['ingested_at']) > created or timestamp(s['available_at']) > availability for s in sources.values()):
        fail('label_maturity', 'label/source not available at dataset creation')
    if label['label']['status'] == 'available':
        if availability < timestamp(scope['horizon']['end_at']) or not sources:
            fail('label_maturity', 'available label requires matured horizon and sources')
        if any(s['license']['status'] == 'restricted' for s in sources.values()):
            fail('source_reference', 'restricted label source')


def validate_labels(labels: list[dict], inputs: dict, target_sha256: str, created, contracts: Contracts) -> None:
    """Label rules of validate_dataset before any split exists (platform ValidateNumericLabels)."""
    for label in labels:
        schema(label, 'numeric-label-v1', contracts)
    if created < timestamp(inputs['created_at']):
        fail('generation_time', 'labels predate their input manifest')
    expected, actual = indexed(inputs['expected_rows'], 'row_id'), indexed(labels, 'row_id')
    same_keys(actual, expected)
    for key, label in actual.items():
        check_label(label, expected[key], target_sha256, created)


def validate_dataset(value: dict, inputs: dict, calendar: dict, rows: list[dict],
                     labels: list[dict], contracts: Contracts) -> None:
    validate_input(inputs, calendar, rows, contracts)
    schema(value, 'numeric-dataset-v1', contracts)
    for label in labels:
        schema(label, 'numeric-label-v1', contracts)
    check_hash(value)
    if value['input_manifest_sha256'] != inputs['input_manifest_sha256'] or value['dataset_id'] != inputs['dataset_id']:
        fail('provenance_mismatch', 'dataset input identity')
    if value['input_manifest']['count'] != 1 or value['labels']['count'] != len(labels):
        fail('artifact_mismatch', 'dataset record counts')
    created = timestamp(value['created_at'])
    if created < timestamp(inputs['created_at']):
        fail('generation_time', 'dataset predates its input manifest')
    review = value['review']
    if review['status'] == 'reviewed' and (review['reviewer'] is None or review['reviewed_at'] is None):
        fail('schema', 'reviewed data requires reviewer and timestamp')
    if review['reviewed_at'] is not None and timestamp(review['reviewed_at']) > created:
        fail('generation_time', 'review follows dataset creation')
    expected = indexed(inputs['expected_rows'], 'row_id')
    actual, assignments = indexed(labels, 'row_id'), indexed(value['assignments'], 'row_id')
    same_keys(actual, expected)
    same_keys(assignments, expected)
    groups = {}
    splits = {name: [] for name in ('train', 'validation', 'test')}
    for key, label in actual.items():
        scope = expected[key]
        check_label(label, scope, value['target']['definition_sha256'], created)
        state = label['label']
        split = assignments[key]['split']
        if split == 'train' and state['status'] != 'available':
            fail('label_maturity', 'training rows require a matured available label')
        day = scope['horizon']['decision_session']
        if day in groups and groups[day] != split:
            fail('split_leakage', 'decision-date group split across partitions')
        groups[day] = split
        splits[split].append(scope)
    policy, earlier = value['split_policy'], []
    for split, scopes in splits.items():
        boundary = None if split == 'train' else policy['embargoed_starts'][split]
        if split != 'train' and scopes and boundary is None:
            fail('split_leakage', 'nonempty later split requires embargoed start')
        if not scopes:
            if boundary is not None:
                fail('split_leakage', 'empty split requires null embargoed start')
            continue
        first = min(timestamp(s['as_of_timestamp']) for s in scopes)
        if boundary is not None and first < timestamp(boundary):
            fail('split_leakage', 'cutoff precedes embargoed start')
        if earlier:
            latest = max(timestamp(s['horizon']['end_at']) for s in earlier)
            if first <= latest or boundary is None or timestamp(boundary) <= latest:
                fail('split_leakage', 'chronological label windows overlap')
            # Embargo is measured in pinned sessions after the preceding label end.
            following = [s for s in calendar['sessions'] if timestamp(s['close_at']) > latest]
            count = policy['embargo_sessions']
            if count and (len(following) < count or timestamp(boundary) < timestamp(following[count - 1]['close_at'])):
                fail('split_leakage', 'declared embargo is shorter than its session count')
        earlier.extend(scopes)


def artifact_path(manifest: Path, entry: dict) -> Path:
    relative = Path(entry['path'])
    if relative.is_absolute():
        fail('artifact_mismatch', 'artifact path must be relative')
    base = manifest.resolve().parent
    path = (base / relative).resolve()
    if not path.is_relative_to(base):
        fail('artifact_mismatch', 'artifact path escapes manifest directory')
    return path


def read_artifact(manifest: Path, entry: dict, *, jsonl: bool = False):
    path = artifact_path(manifest, entry)
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != entry['sha256']:
        fail('artifact_mismatch', f'raw bytes hash mismatch: {entry["path"]}')
    if not jsonl:
        return read_json(path)
    try:
        lines = data.decode('utf-8').splitlines()
    except UnicodeError as error:
        raise NumericError('invalid_json', 'invalid UTF-8 JSONL') from error
    if any(not line.strip() for line in lines):
        fail('invalid_json', 'blank JSONL records are forbidden')
    return [loads(line) for line in lines]


def load_input(path: Path, contracts: Contracts) -> tuple[dict, dict, list[dict]]:
    value = read_json(path)
    schema(value, 'numeric-input-v1', contracts)
    check_hash(value)
    paths = [artifact_path(path, value[name]) for name in ('calendar', 'features')]
    if len(set(paths + [path.resolve()])) != 3:
        fail('artifact_mismatch', 'input manifest and artifacts must be distinct')
    calendar = read_artifact(path, value['calendar'])
    rows = read_artifact(path, value['features'], jsonl=True)
    validate_input(value, calendar, rows, contracts)
    return value, calendar, rows


def load_dataset(path: Path, contracts: Contracts) -> dict:
    value = read_json(path)
    schema(value, 'numeric-dataset-v1', contracts)
    check_hash(value)
    read_artifact(path, value['input_manifest'])
    input_path = artifact_path(path, value['input_manifest'])
    inputs, calendar, rows = load_input(input_path, contracts)
    paths = [path.resolve(), input_path, artifact_path(input_path, inputs['calendar']),
             artifact_path(input_path, inputs['features']), artifact_path(path, value['labels'])]
    if len(paths) != len(set(paths)):
        fail('artifact_mismatch', 'labels must be a separate artifact from prediction inputs')
    labels = read_artifact(path, value['labels'], jsonl=True)
    validate_dataset(value, inputs, calendar, rows, labels, contracts)
    return {'dataset_id': value['dataset_id'], 'features': len(rows), 'labels': len(labels)}
