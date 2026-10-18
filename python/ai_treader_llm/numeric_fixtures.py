"""Deterministic synthetic numeric v1 fixtures for Python and future Go adoption.

No model or reviewed financial data is produced. Cases share a base bundle and
apply explicit path replacements/removals, avoiding copies of calendar schedules.
"""
from __future__ import annotations

import copy
import hashlib
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from ai_treader_llm import numeric as n

DIRECTORY = Path('contracts/fixtures/numeric-v1')
EXAMPLES = Path('examples/numeric-v1')


def sha(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def dump(value: object) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False) + '\n'


def jsonl(rows: list[dict]) -> str:
    return ''.join(n.canonical_json(row).decode('utf-8') + '\n' for row in rows)


def entry(path: str, text: str, count: int) -> dict:
    return {'path': path, 'sha256': sha(text), 'count': count}


def base() -> dict:
    # A bounded fixture schedule transcribed from platform calendar/xnys.go;
    # not an independently verified calendar or a real-data availability claim.
    sessions, day = [], date(2025, 1, 2)
    closed = {'2025-01-09', '2025-01-20', '2025-02-17'}
    zone = ZoneInfo('America/New_York')
    while day <= date(2025, 4, 11):
        if day.weekday() < 5 and day.isoformat() not in closed:
            def utc(hour, minute):
                return datetime(day.year, day.month, day.day, hour, minute, tzinfo=zone).astimezone(ZoneInfo('UTC')).isoformat().replace('+00:00', 'Z')
            sessions.append({'session': day.isoformat(), 'open_at': utc(9, 30), 'close_at': utc(16, 0)})
        day += timedelta(days=1)
    calendar = n.seal({'schema_version': 'numeric-calendar-v1', 'calendar_id': 'synthetic-xnys-2025-q1',
                      'exchange': 'XNYS', 'coverage_start': '2025-01-02', 'coverage_end': '2025-04-11', 'sessions': sessions})
    definitions = {'version': 'synthetic-daily-v1', 'features': [
        {'feature_id': 'return_5_sessions', 'unit': 'decimal_return', 'definition_sha256': sha('synthetic-five-session-return-v1')},
        {'feature_id': 'volume_ratio', 'unit': 'ratio', 'definition_sha256': sha('synthetic-volume-ratio-v1')},
    ]}
    definitions['feature_schema_sha256'] = n.digest(definitions, 'feature_schema_sha256')
    scopes, features, labels = [], [], []
    target = {'kind': 'benchmark_excess_return', 'unit': 'decimal_return', 'benchmark_listing_id': '9007199254740995',
              'entry_policy': 'next_session_open', 'exit_policy': 'horizon_close',
              'price_basis': 'total_return_adjusted', 'definition_sha256': sha('synthetic-excess-total-return-next-open-close-v1')}
    for prefix, cutoff, entry_day, end, entry_at, end_at in (
        ('jan', '2025-01-03T21:00:00Z', '2025-01-06', '2025-02-03', '2025-01-06T14:30:00Z', '2025-02-03T21:00:00Z'),
        ('mar', '2025-03-07T21:00:00Z', '2025-03-10', '2025-04-07', '2025-03-10T13:30:00Z', '2025-04-07T20:00:00Z'),
    ):
        for index, listing in enumerate(('101', '9007199254740993')):
            row_id = f'{prefix}-{index}'
            scope = {'row_id': row_id, 'listing_id': listing, 'as_of_timestamp': cutoff,
                     'horizon': {'label': '1m', 'policy': 'xnys-calendar-months-next-open-v1',
                                 'calendar_sha256': calendar['calendar_sha256'], 'decision_session': cutoff[:10],
                                 'entry_session': entry_day, 'entry_at': entry_at, 'end_session': end, 'end_at': end_at}}
            scopes.append(scope)
            def source(source_id, at):
                return {'source_id': source_id, 'revision': 'synthetic-revision-1', 'content_sha256': sha(row_id + source_id),
                        'available_at': at, 'ingested_at': at,
                        'license': {'status': 'synthetic_only', 'reference': 'Generated fixture; no real source or training use.'}}
            features.append({'schema_version': 'numeric-feature-row-v1', 'row_id': row_id,
                             'sources': [source('prices', cutoff)], 'features': [
                                 {'feature_id': 'return_5_sessions', 'value': {'status': 'available', 'value': '0.012345678901234567'}, 'source_ids': ['prices']},
                                 {'feature_id': 'volume_ratio', 'value': {'status': 'unavailable', 'reason': 'not_collected'}, 'source_ids': []},
                             ]})
            labels.append({'schema_version': 'numeric-label-v1', **copy.deepcopy(scope),
                           'target_definition_sha256': target['definition_sha256'], 'available_at': end_at,
                           'sources': [source('label-prices', end_at)],
                           'label': {'status': 'available', 'value': '0' if index == 0 else '-0.025'}})
    inputs = n.seal({'schema_version': 'numeric-input-v1', 'dataset_id': 'synthetic-numeric-v1',
                    'created_at': '2025-03-07T21:00:01Z', 'availability_policy': 'observed',
                    'corporate_action_basis': 'total_return_adjusted', 'action_policy_sha256': sha('synthetic-pit-actions-v1'),
                    'universe': {'snapshot_sha256': sha('synthetic-membership'), 'membership_policy_sha256': sha('synthetic-membership-v1'), 'survivorship': 'survivorship_biased_pilot'},
                    'calendar': entry('calendar.json', dump(calendar), len(sessions)), 'feature_schema': definitions,
                    'features': entry('features.jsonl', jsonl(features), len(features)), 'expected_rows': scopes})
    request = {'schema_version': 'alpha-request-v1', 'batch_id': 'synthetic-batch-1', 'attempt_id': 'synthetic-attempt-1',
               'input_manifest_sha256': inputs['input_manifest_sha256'], 'feature_schema_sha256': definitions['feature_schema_sha256'],
               'requested_at': '2025-03-07T21:00:02Z', 'deadline_at': '2025-03-07T21:01:02Z',
               'model': {key: sha('synthetic-' + key) for key in ('artifact_sha256', 'training_manifest_sha256', 'config_sha256', 'code_sha256', 'runtime_sha256')},
               'score_semantics': {'kind': 'expected_excess_return', 'unit': 'decimal_return', 'direction': 'higher_is_better', 'target': target}}
    request['model']['seed'] = 0
    forecast = n.seal({'schema_version': 'alpha-forecast-v1', **{k: copy.deepcopy(v) for k, v in request.items() if k not in ('schema_version', 'requested_at', 'deadline_at')},
                       'generated_at': '2025-03-07T21:00:03Z', 'results': [
                           {**copy.deepcopy(scope), 'score': {'status': 'available', 'value': '0'} if index % 2 == 0 else {'status': 'unavailable', 'reason': 'missing_features'}}
                           for index, scope in enumerate(scopes)]})
    dataset = n.seal({'schema_version': 'numeric-dataset-v1', 'dataset_id': inputs['dataset_id'], 'created_at': '2025-04-08T21:00:00Z',
                      'input_manifest': entry('input-manifest.json', dump(inputs), 1), 'input_manifest_sha256': inputs['input_manifest_sha256'],
                      'labels': entry('labels.jsonl', jsonl(labels), len(labels)), 'target': target,
                      'assignments': [{'row_id': scope['row_id'], 'split': 'train' if scope['row_id'].startswith('jan') else 'validation'} for scope in scopes],
                      'split_policy': {'date_grouped': True, 'label_window_purged': True, 'embargo_sessions': 1,
                                       'embargoed_starts': {'validation': '2025-02-04T21:00:00Z', 'test': None}},
                      'review': {'status': 'synthetic_only', 'reviewer': None, 'reviewed_at': None, 'notes': 'Synthetic contract fixtures only; not reviewed training data.'}})
    return {'calendar': calendar, 'inputs': inputs, 'features': features, 'request': request, 'forecast': forecast, 'dataset': dataset, 'labels': labels}


def differences(before, after, path=()):
    if isinstance(before, dict) and isinstance(after, dict):
        changes = []
        for key in sorted(before.keys() | after.keys()):
            if key not in after:
                changes.append({'path': list(path + (key,)), 'remove': True})
            elif key not in before:
                changes.append({'path': list(path + (key,)), 'value': after[key]})
            else:
                changes.extend(differences(before[key], after[key], path + (key,)))
        return changes
    if isinstance(before, list) and isinstance(after, list) and len(before) == len(after):
        return [change for index, (a, b) in enumerate(zip(before, after)) for change in differences(a, b, path + (index,))]
    return [] if before == after and type(before) is type(after) else [{'path': list(path), 'value': after}]


def apply_changes(base_documents: dict, changes: list[dict]) -> dict:
    documents = copy.deepcopy(base_documents)
    for change in changes:
        *parents, key = change['path']
        node = documents
        for part in parents:
            node = node[part]
        if change.get('remove'):
            del node[key]
        else:
            node[key] = copy.deepcopy(change['value'])
    return documents


def run_case(operation: str, documents: dict, contracts) -> None:
    d = documents
    args = d['inputs'], d['calendar'], d['features'], contracts
    if operation == 'input':
        n.validate_input(*args)
    elif operation == 'forecast':
        n.validate_forecast(d['forecast'], d['request'], *args)
    elif operation == 'dataset':
        n.validate_dataset(d['dataset'], d['inputs'], d['calendar'], d['features'], d['labels'], contracts)
    else:
        raise ValueError(f'unknown fixture operation: {operation}')


def suite() -> dict:
    documents = base()
    cases = []

    def case(name, operation, expect='valid', edits=(), reseal=()):
        changed = apply_changes(documents, [{'path': list(path), 'value': value} for path, value in edits])
        for key in reseal:
            changed[key] = n.seal(changed[key])
        cases.append({'name': name, 'operation': operation, 'expect': expect, 'changes': differences(documents, changed)})

    case('mixed-success-and-unavailable', 'forecast')
    case('separate-labels-and-date-grouped-splits', 'dataset')
    case('reconstructed-late-ingestion', 'input', edits=[(('inputs','availability_policy'),'reconstructed'), (('features',0,'sources',0,'ingested_at'),'2025-03-07T21:00:00Z')], reseal=['inputs'])
    case('observed-late-ingestion', 'input', 'source_availability', [(('features',0,'sources',0,'ingested_at'),'2025-01-03T21:00:00.000001Z')])
    case('future-source-one-microsecond', 'input', 'source_availability', [(('features',0,'sources',0,'available_at'),'2025-01-03T21:00:00.000001Z'), (('features',0,'sources',0,'ingested_at'),'2025-01-03T21:00:00.000001Z')])
    case('ingestion-before-availability', 'input', 'source_availability', [(('features',0,'sources',0,'ingested_at'),'2025-01-03T20:59:59Z')])
    case('unknown-feature-reference', 'input', 'source_reference', [(('features',0,'features',0,'source_ids'),['invented'])])
    case('available-feature-without-source', 'input', 'source_reference', [(('features',0,'features',0,'source_ids'),[])])
    case('duplicate-feature', 'input', 'feature_coverage', [(('features',0,'features',1,'feature_id'),'return_5_sessions')])
    case('missing-feature', 'input', 'feature_coverage', [(('features',0,'features'),documents['features'][0]['features'][:1])])
    case('extra-feature', 'input', 'feature_coverage', [(('features',0,'features',1,'feature_id'),'future_return')])
    case('restricted-source', 'input', 'source_reference', [(('features',0,'sources',0,'license','status'),'restricted')])
    case('feature-definition-hash-changed', 'input', 'hash_mismatch', [(('inputs','feature_schema','features',0,'definition_sha256'),'0'*64)], ['inputs'])
    case('input-hash-changed', 'input', 'hash_mismatch', [(('inputs','universe','survivorship'),'unknown')])
    case('calendar-hash-changed', 'input', 'hash_mismatch', [(('calendar','sessions',0,'open_at'),'2025-01-02T14:31:00Z')])
    case('thirty-days-is-not-one-calendar-month', 'input', 'calendar', [(('inputs','expected_rows',0,'horizon','end_session'),'2025-02-02')], ['inputs'])
    case('cutoff-close-is-not-executable-entry', 'input', 'calendar', [(('inputs','expected_rows',0,'horizon','entry_at'),'2025-01-03T21:00:00Z')], ['inputs'])
    case('dst-entry-offset', 'input', 'calendar', [(('inputs','expected_rows',2,'horizon','entry_at'),'2025-03-10T14:30:00Z')], ['inputs'])
    case('label-in-feature-row', 'input', 'schema', [(('features',0,'label'),{'status':'available','value':'0.2'})])
    case('unknown-horizon-field', 'input', 'schema', [(('inputs','expected_rows',0,'horizon','return'),'0.2')], ['inputs'])
    case('json-number-listing-id', 'input', 'schema', [(('inputs','expected_rows',0,'listing_id'),101)], ['inputs'])
    case('int64-overflow', 'input', 'schema', [(('inputs','expected_rows',0,'listing_id'),'9223372036854775808')], ['inputs'])
    case('float-feature', 'input', 'schema', [(('features',0,'features',0,'value','value'),0.25)])
    case('unavailable-feature-has-value', 'input', 'schema', [(('features',0,'features',1,'value','value'),'0')])
    case('invalid-utc', 'input', 'schema', [(('inputs','expected_rows',0,'as_of_timestamp'),'2025-01-03T21:00:00+00:00')], ['inputs'])
    for bad in ('-0','01','0.10','1e-3','NaN','1.0000000000000000001'):
        case('noncanonical-decimal-'+bad, 'forecast', 'schema', [(('forecast','results',0,'score','value'),bad)], ['forecast'])
    for field, val in (('listing_id','9007199254740992'),('as_of_timestamp','2025-01-03T20:59:59Z')):
        case('changed-'+field, 'forecast', 'identity_mismatch', [(('forecast','results',1,field),val)], ['forecast'])
    case('forecast-horizon-mismatch', 'forecast', 'identity_mismatch', [(('forecast','results',0,'horizon','label'),'3m')], ['forecast'])
    for name, result in (('missing-result',documents['forecast']['results'][:-1]), ('duplicate-result',documents['forecast']['results']+[documents['forecast']['results'][0]]), ('unknown-result',documents['forecast']['results']+[{**documents['forecast']['results'][0],'row_id':'unknown'}])):
        case(name,'forecast','coverage',[(('forecast','results'),result)],['forecast'])
    for field in ('artifact_sha256','training_manifest_sha256','config_sha256','code_sha256','runtime_sha256'):
        case('wrong-model-'+field,'forecast','provenance_mismatch',[(('forecast','model',field),'0'*64)],['forecast'])
    for field in ('batch_id','attempt_id','input_manifest_sha256','feature_schema_sha256'):
        case('wrong-'+field,'forecast','provenance_mismatch',[(('forecast',field),'0'*64)],['forecast'])
    case('unavailable-score-has-zero','forecast','schema',[(('forecast','results',1,'score','value'),'0')],['forecast'])
    case('rank-labelled-as-probability','forecast','schema',[(('request','score_semantics','kind'),'probability')])
    case('rank-wrong-unit','forecast','provenance_mismatch',[(('request','score_semantics','kind'),'ranking_score')])
    case('deadline-exceeded-by-microsecond','forecast','generation_time',[(('forecast','generated_at'),'2025-03-07T21:01:02.000001Z')],['forecast'])
    case('before-request','forecast','generation_time',[(('forecast','generated_at'),'2025-03-07T21:00:01Z')],['forecast'])
    case('forecast-hash-tampering','forecast','hash_mismatch',[(('forecast','results',0,'score','value'),'0.1')])
    case('missing-label','dataset','coverage',[(('labels',),documents['labels'][:-1]),(('dataset','labels','count'),3)],['dataset'])
    case('wrong-label-identity','dataset','identity_mismatch',[(('labels',0,'listing_id'),'102')])
    case('wrong-label-target','dataset','provenance_mismatch',[(('labels',0,'target_definition_sha256'),'0'*64)])
    case('unmatured-available-label','dataset','label_maturity',[(('labels',0,'available_at'),'2025-02-03T20:59:59Z')])
    case('unavailable-training-label','dataset','label_maturity',[(('labels',0,'label'),{'status':'unavailable','reason':'not_matured'})])
    case('label-source-after-dataset','dataset','label_maturity',[(('labels',0,'sources',0,'ingested_at'),'2025-04-09T00:00:00Z')])
    case('same-decision-date-in-two-splits','dataset','split_leakage',[(('dataset','assignments',0,'split'),'validation')],['dataset'])
    case('embargo-start-after-first-cutoff','dataset','split_leakage',[(('dataset','split_policy','embargoed_starts','validation'),'2025-03-07T21:00:00.000001Z')],['dataset'])
    case('embargo-before-earlier-label-end','dataset','split_leakage',[(('dataset','split_policy','embargoed_starts','validation'),'2025-02-03T21:00:00Z')],['dataset'])
    case('session-embargo-too-short','dataset','split_leakage',[(('dataset','split_policy','embargo_sessions'),2)],['dataset'])
    case('disable-purge','dataset','schema',[(('dataset','split_policy','label_window_purged'),False)],['dataset'])
    case('review-without-reviewer','dataset','schema',[(('dataset','review','status'),'reviewed')],['dataset'])
    return {'fixture_version':'1','base':documents,'cases':cases}


def hash_vectors() -> dict:
    values = [
        {'name':'exact-id-and-decimal','value':{'listing_id':'9007199254740993','value':'-0.012345678901234567','zero':'0','seed':0}},
        {'name':'unicode-escapes','value':{'z':'quote " backslash \\ newline\n tab\t ctl\x01 del\x7f separator\u2028 clef\U0001d11e <&>','a':[True,None,'é']}},
    ]
    for vector in values:
        raw = n.canonical_json(vector['value'])
        vector.update(canonical_utf8=raw.decode('utf-8'),sha256=hashlib.sha256(raw).hexdigest())
    return {'fixture_version':'1','vectors':values}


def build() -> dict[Path,str]:
    documents = base()
    names = {'calendar':'calendar.json','inputs':'input-manifest.json','request':'request.json','forecast':'forecast.json','dataset':'dataset-manifest.json'}
    files = {EXAMPLES / name: dump(documents[key]) for key,name in names.items()}
    files.update({EXAMPLES/'features.jsonl':jsonl(documents['features']),EXAMPLES/'labels.jsonl':jsonl(documents['labels'])})
    files[DIRECTORY/'cases.json'] = dump(suite())
    files[DIRECTORY/'hash-vectors.json'] = dump(hash_vectors())
    return files


if __name__ == '__main__':
    for path,text in build().items():
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(text,encoding='utf-8')
