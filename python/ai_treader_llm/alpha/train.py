"""ALPHA03 §3.4–§3.6 supervised fit: folds, the fixed trial family, selection and final fit.

Windows, purge, embargo, grids, seed and selection come from the frozen parameters.
Only development decisions are accepted, so no test-window label can enter a fit.
Every trial is drawn and written before the first fit; a failed trial stays counted.
The training manifest holds no wall-clock time, so a rerun on the same runtime
reproduces it byte for byte; run.json records timing separately.
"""
from __future__ import annotations

import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from ai_treader_llm.alpha import models, protocol, provenance
from ai_treader_llm.alpha.data import Export, Row
from ai_treader_llm.contracts import timestamp
from ai_treader_llm.numeric import NumericError, fail

MANIFEST_VERSION = 'alpha-training-manifest-v1'
CHALLENGERS_VERSION = 'alpha-challengers-v1'
TARGET_TRANSFORM = 'label demeaned across the usable rows of each decision date, inside the job'
PREPROCESSING = 'train-only standardization: mean and population standard deviation (zero deviation -> 1)'
MOMENTUM_FEATURE = 'return_20_sessions'


class TrialFailure(Exception):
    pass


def ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=values.__getitem__)
    out = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            out[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return out


def spearman(a: list[float], b: list[float]) -> float | None:
    """Rank correlation with average ranks; None when undefined (fewer than 2 rows or a constant side)."""
    if len(a) < 2:
        return None
    ra, rb = np.array(ranks(a)), np.array(ranks(b))
    ra, rb = ra - ra.mean(), rb - rb.mean()
    denominator = float(np.sqrt((ra * ra).sum() * (rb * rb).sum()))
    return None if denominator == 0 else float((ra * rb).sum()) / denominator


def decisions(rows) -> list[str]:
    return sorted({row.decision for row in rows})


def window(rows, spec: dict, name: str) -> list[Row]:
    out = [row for row in rows if spec['first'] <= row.decision <= spec['last']]
    found = len(decisions(out))
    if found != spec['decisions']:
        fail('coverage', f'{name}: export holds {found} decisions, protocol fixes {spec["decisions"]}')
    return out


def usable(rows) -> list[Row]:
    return [row for row in rows if row.x is not None and row.y is not None]


def demeaned(rows) -> np.ndarray:
    groups = defaultdict(list)
    for row in rows:
        groups[row.decision].append(row.y)
    means = {day: sum(values) / len(values) for day, values in groups.items()}
    return np.array([row.y - means[row.decision] for row in rows], dtype=np.float64)


def matrix(rows) -> np.ndarray:
    return np.array([row.x for row in rows], dtype=np.float64)


def fold(rows, spec: dict, calendar: dict, embargo: int, name: str) -> dict:
    """Train rows purged on label end and embargo-verified against the validation start."""
    train, validation = window(rows, spec['train'], f'{name} train'), window(rows, spec['validation'], f'{name} validation')
    start = min(row.cutoff for row in validation)
    candidates = usable(train)
    kept = [row for row in candidates if row.end_at < start]
    if not kept:
        fail('split_leakage', f'{name}: no training row survives the purge')
    latest = max(row.end_at for row in kept)
    following = [s for s in calendar['sessions'] if timestamp(s['close_at']) > latest]
    if embargo and (len(following) < embargo or start < timestamp(following[embargo - 1]['close_at'])):
        fail('split_leakage', f'{name}: fewer than {embargo} sessions between the last kept label end and validation')
    return {'name': name, 'train': kept, 'validation': validation, 'summary': {
        'fold': name,
        'train': {**spec['train'], 'rows_in_window': len(train), 'rows_usable': len(candidates),
                  'rows_purged': len(candidates) - len(kept), 'last_label_end': latest.isoformat().replace('+00:00', 'Z')},
        'validation': {**spec['validation'], 'rows': len(validation),
                       'rows_scored': sum(row.x is not None for row in validation),
                       'rows_labelled': len(usable(validation)), 'start': start.isoformat().replace('+00:00', 'Z')},
        'embargo_sessions': embargo, 'embargo_verified': True}}


def date_ics(rows, scores) -> dict:
    groups = defaultdict(lambda: ([], []))
    for row, score in zip(rows, scores):
        if row.y is not None:
            groups[row.decision][0].append(float(score))
            groups[row.decision][1].append(row.y)
    ics = {day: spearman(*groups[day]) for day in sorted(groups)}
    defined = [value for value in ics.values() if value is not None]
    if not defined:
        raise TrialFailure('no validation date has a defined rank correlation')
    return {'dates': len(ics), 'dates_undefined': len(ics) - len(defined), 'mean_ic': sum(defined) / len(defined)}


def score_folds(folds, scorer) -> dict:
    results = []
    for item in folds:
        scored = [row for row in item['validation'] if row.x is not None]
        scores = scorer(item, scored)
        if not np.all(np.isfinite(scores)):
            raise TrialFailure('non_finite_output')
        results.append({'fold': item['name'], **date_ics(scored, scores)})
    return {'folds': results, 'mean_fold_ic': sum(r['mean_ic'] for r in results) / len(results)}


def config_record(arm: str, config: dict, export: Export, horizon: str, seed: int) -> dict:
    record = {'arm': arm, 'config': config, 'features': list(export.feature_ids), 'horizon': horizon,
              'feature_schema_sha256': export.inputs['feature_schema']['feature_schema_sha256'],
              'preprocessing': PREPROCESSING, 'target_transform': TARGET_TRANSFORM, 'seed': seed}
    if arm == 'G':
        record['lightgbm_params'] = models.lightgbm_params(config, seed)
    return record


def selection_key(trial: dict):
    config = trial['config']
    if trial['arm'] == 'R':
        return (-trial['mean_fold_ic'], -config['alpha'], trial['trial'])
    return (-trial['mean_fold_ic'], config['num_leaves'], config['n_estimators'], trial['trial'])


def write(path: Path, value) -> str:
    data = provenance.canonical(value)
    path.write_bytes(data)
    return provenance.sha256(data)


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def run(export: Export, params: dict, parameters_sha256: str, horizon: str, benchmark_listing_id: str, out: Path) -> dict:
    started = datetime.now(timezone.utc)
    clock = time.monotonic()
    inputs, rows = export.inputs, export.rows
    if inputs['feature_schema']['version'] != params['feature_version']:
        fail('provenance_mismatch', 'feature schema version is not the protocol feature version')
    if inputs['availability_policy'] != 'reconstructed':
        fail('source_availability', 'historical development exports use reconstruction availability (protocol §2)')
    if any(scope['horizon']['label'] != horizon for scope in inputs['expected_rows']):
        fail('identity_mismatch', f'export horizon is not {horizon}')
    listings = sorted({row.listing_id for row in rows}, key=int)
    if len(listings) != len(params['universe']):
        fail('coverage', f'export holds {len(listings)} listings, protocol universe has {len(params["universe"])}')
    if benchmark_listing_id not in listings:
        fail('identity_mismatch', 'benchmark listing is not in the export universe')
    windows = params['windows'][horizon]
    development = window(rows, windows['development'], 'development')
    if len(development) != len(rows):
        fail('split_leakage', 'export holds rows outside the development window')
    if any(row.y is not None and row.end_session >= windows['label_end_before'] for row in rows):
        fail('split_leakage', f'a label ends on or after the fence {windows["label_end_before"]}')
    embargo = params['windows']['embargo_sessions']
    folds = [fold(rows, spec, export.calendar, embargo, f'V{i + 1}') for i, spec in enumerate(windows['validation_folds'])]
    seed = params['arms']['G']['fixed']['seed']

    out.mkdir(parents=True, exist_ok=False)
    (out / 'artifacts').mkdir()
    draw = protocol.trials(params)
    draw_record = {'protocol_parameters_sha256': parameters_sha256, 'horizon': horizon, 'method': protocol.DRAW_METHOD,
                   'seed': params['arms']['G']['seed'], 'trials': draw}
    draw_sha = write(out / 'trial-draw.json', draw_record)
    log(f'{horizon}: {len(draw)} trials drawn; folds {[f["summary"]["train"]["rows_usable"] for f in folds]} train rows')

    results = []
    with (out / 'trials.jsonl').open('w', encoding='utf-8') as journal:
        for trial in draw:
            record = {**trial}
            try:
                record.update(status='ok', **score_folds(folds, lambda item, scored: models.predict(
                    models.fit(trial['arm'], trial['config'], export.feature_ids, matrix(item['train']),
                               demeaned(item['train']), seed), matrix(scored))))
            except (TrialFailure, ValueError, ArithmeticError, np.linalg.LinAlgError, models.lightgbm.basic.LightGBMError) as error:
                record.update(status='failed', reason=f'{type(error).__name__}: {error}')
            results.append(record)
            journal.write(provenance.canonical(record).decode('utf-8') + '\n')
            journal.flush()
            log(f'trial {trial["trial"]:>2} {trial["arm"]} {record["status"]} {provenance.plain(record.get("mean_fold_ic", record.get("reason")))}')

    momentum = export.feature_ids.index(MOMENTUM_FEATURE)
    reference = score_folds(folds, lambda item, scored: matrix(scored)[:, momentum])

    final_rows = usable(rows)
    code, runtime = provenance.code(), provenance.runtime()
    selected, final = {}, {}
    for arm in ('R', 'G'):
        ok = [trial for trial in results if trial['arm'] == arm and trial['status'] == 'ok']
        if not ok:
            raise NumericError('coverage', f'no {arm} trial completed; nothing to freeze')
        best = min(ok, key=selection_key)
        selected[arm] = best['trial']
        artifact = models.fit(arm, best['config'], export.feature_ids, matrix(final_rows), demeaned(final_rows), seed)
        artifact_sha = write(out / 'artifacts' / f'{arm}.json', artifact)
        config = config_record(arm, best['config'], export, horizon, seed)
        final[arm] = {'trial': best['trial'], 'config': config, 'config_sha256': provenance.sha256(provenance.canonical(config)),
                      'artifact_path': f'artifacts/{arm}.json', 'artifact_sha256': artifact_sha, 'rows': len(final_rows),
                      'decisions': len(decisions(final_rows))}

    missing_features = Counter(row.missing for row in rows if row.missing)
    missing_labels = Counter(row.label_reason for row in rows if row.y is None)
    failed = sum(trial['status'] == 'failed' for trial in results)
    target = {'kind': 'benchmark_excess_return', 'unit': 'decimal_return', 'benchmark_listing_id': benchmark_listing_id,
              'entry_policy': 'next_session_open', 'exit_policy': 'horizon_close',
              'price_basis': inputs['corporate_action_basis'], 'definition_sha256': export.target_definition_sha256}
    semantics = {'kind': 'ranking_score', 'unit': 'unitless', 'direction': 'higher_is_better', 'target': target}
    manifest = {
        'schema_version': MANIFEST_VERSION,
        'protocol': {'name': params['preregistration'], 'revision': params['revision'], 'parameters_sha256': parameters_sha256,
                     'feature_version': params['feature_version'], 'label_version': params['label_version'],
                     'horizon_policy': params['horizon_policy'], 'mapping_version': params['mapping_version']},
        'horizon': horizon,
        'export': {'dataset_id': inputs['dataset_id'], 'input_manifest_sha256': inputs['input_manifest_sha256'],
                   'input_manifest_file_sha256': export.input_file_sha256, 'features_sha256': inputs['features']['sha256'],
                   'calendar_sha256': inputs['calendar']['sha256'], 'labels_file_sha256': export.labels_file_sha256,
                   'feature_schema_sha256': inputs['feature_schema']['feature_schema_sha256'],
                   'feature_ids': list(export.feature_ids), 'target_definition_sha256': export.target_definition_sha256,
                   'availability_policy': inputs['availability_policy'], 'survivorship': inputs['universe']['survivorship'],
                   'listing_ids': listings, 'benchmark_listing_id': benchmark_listing_id},
        'rows': {'expected': len(rows), 'decisions': len(decisions(rows)), 'usable': len(final_rows),
                 'excluded_missing_features': dict(sorted(missing_features.items())),
                 'excluded_missing_labels': dict(sorted(missing_labels.items()))},
        'folds': [item['summary'] for item in folds],
        'draw': {'sha256': draw_sha, 'method': protocol.DRAW_METHOD, 'seed': params['arms']['G']['seed']},
        'trials': results,
        'trial_family': {'fitted': len(results), 'failed': failed, 'protocol_family': params['trial_family']},
        'selection': {'criterion': params['selection']['criterion'], 'ties': params['selection']['ties'],
                      'aggregation': 'mean over folds of each fold\'s mean per-date rank correlation; undefined dates excluded and counted',
                      'selected_trials': selected},
        'reference': {'arm': 'M', 'rule': params['arms']['M']['rule'], 'feature': MOMENTUM_FEATURE,
                      'note': 'reported on the same validation rows; never used for selection', **reference},
        'final_fit': {'decisions': windows['development'], 'label_end_before': windows['label_end_before'], 'arms': final},
        'preprocessing': PREPROCESSING, 'target_transform': TARGET_TRANSFORM, 'score_semantics': semantics,
        'seed': seed, 'code': code, 'runtime': runtime,
    }
    manifest_sha = write(out / 'training-manifest.json', manifest)
    challengers = {'schema_version': CHALLENGERS_VERSION, 'training_manifest_sha256': manifest_sha, 'horizon': horizon,
                   'protocol_parameters_sha256': parameters_sha256,
                   'feature_schema_sha256': inputs['feature_schema']['feature_schema_sha256'],
                   'feature_version': params['feature_version'], 'score_semantics': semantics, 'arms': {
                       arm: {'trial': item['trial'], 'artifact_path': item['artifact_path'], 'config': item['config'],
                             'model': {'artifact_sha256': item['artifact_sha256'], 'training_manifest_sha256': manifest_sha,
                                       'config_sha256': item['config_sha256'], 'code_sha256': code['sha256'],
                                       'runtime_sha256': runtime['sha256'], 'seed': seed}}
                       for arm, item in final.items()}}
    challengers_sha = write(out / 'challengers.json', challengers)
    summary = {'horizon': horizon, 'training_manifest_sha256': manifest_sha, 'challengers_sha256': challengers_sha,
               'trials': len(results), 'failed': failed, 'selected': selected,
               'mean_fold_ic': {arm: next(t['mean_fold_ic'] for t in results if t['trial'] == selected[arm]) for arm in selected},
               'reference_mean_fold_ic': reference['mean_fold_ic'],
               'artifacts': {arm: item['artifact_sha256'] for arm, item in final.items()}}
    write(out / 'run.json', {'started_at': started.isoformat().replace('+00:00', 'Z'),
                             'finished_at': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
                             'elapsed_seconds': round(time.monotonic() - clock, 3), 'summary': summary})
    return provenance.plain(summary)
