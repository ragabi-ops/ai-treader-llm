"""Feature-only Chronos batch: frozen challenger + series export -> alpha-forecast-v1 and quantiles.

No label artifact is read. The request must name the frozen pins, and the job refuses
to run when its code, runtime or weights differ from them. Every expected row gets a
result: a score, or a typed reason (missing_features, out_of_domain, model_error,
non_finite_output, timeout). quantiles.jsonl keeps each scored row's h-step quantiles
for calibration; run.json holds wall-clock, latency and peak memory, outside every hash.
"""
from __future__ import annotations

import copy
import math
import platform
import resource
import sys
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ai_treader_llm import numeric
from ai_treader_llm.chronos import provenance, series, weights
from ai_treader_llm.contracts import Contracts, timestamp
from ai_treader_llm.numeric import fail

QUANTILES_VERSION = 'chronos-quantiles-v1'
DEADLINE_RESERVE = timedelta(seconds=30)   # stop scoring this long before the deadline so the forecast still lands inside it


def utc(moment: datetime) -> str:
    return moment.isoformat(timespec='microseconds').replace('+00:00', 'Z')


def decimal_text(value: float) -> str | None:
    """Canonical decimal with at most 15 fractional digits; None when not representable."""
    if not math.isfinite(value) or abs(value) >= 1e20:
        return None
    text = f'{value:.15f}'.rstrip('0').rstrip('.')
    return '0' if text in ('-0', '') else text


def build_request(challenger: dict, entry: dict, export: series.Export, batch_id: str, attempt_id: str,
                  requested_at: datetime, deadline_at: datetime) -> dict:
    """A request naming the frozen pins, for local runs; the platform builds its own."""
    return {'schema_version': 'alpha-request-v1', 'batch_id': batch_id, 'attempt_id': attempt_id,
            'input_manifest_sha256': export.inputs['input_manifest_sha256'],
            'feature_schema_sha256': export.inputs['feature_schema']['feature_schema_sha256'],
            'requested_at': utc(requested_at), 'deadline_at': utc(deadline_at),
            'model': copy.deepcopy(entry['model']), 'score_semantics': copy.deepcopy(challenger['score_semantics'])}


def check(challenger: dict, entry: dict, export: series.Export, request: dict, contracts: Contracts) -> None:
    inputs, config = export.inputs, entry['config']
    numeric.validate_request(request, inputs, contracts)
    if request['model'] != entry['model'] or request['score_semantics'] != challenger['score_semantics']:
        fail('provenance_mismatch', 'request does not name the frozen challenger pins and score semantics')
    if inputs['feature_schema']['feature_schema_sha256'] != challenger['feature_schema_sha256']:
        fail('provenance_mismatch', 'input feature schema differs from the challenger')
    if any(scope['horizon']['label'] != challenger['horizon'] for scope in inputs['expected_rows']):
        fail('identity_mismatch', f'input horizon is not the challenger horizon {challenger["horizon"]}')
    current = {'code': provenance.code()['sha256'], 'runtime': provenance.runtime(config['torch_threads'])['sha256']}
    for name, value in current.items():
        if value != entry['model'][f'{name}_sha256']:
            fail('provenance_mismatch', f'{name} sha256 {value} differs from the frozen challenger')
    _, manifest_sha = weights.verify(Path(challenger['weights_path']))
    if manifest_sha != entry['model']['artifact_sha256']:
        fail('provenance_mismatch', 'weights manifest differs from the frozen artifact pin')


def peak_rss_bytes() -> int:
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak if sys.platform == 'darwin' else peak * 1024


def cpu_model() -> str:
    try:
        for line in Path('/proc/cpuinfo').read_text(encoding='utf-8').splitlines():
            if line.startswith('model name'):
                return line.split(':', 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or 'unknown'


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, math.ceil(q * len(ordered)) - 1))]


def run(challenger: dict, entry: dict, export: series.Export, request: dict, forecaster, out: Path,
        contracts: Contracts, *, load_seconds: float = 0.0, clock=lambda: datetime.now(timezone.utc)) -> dict:
    """Score every expected row with `forecaster(path, step) -> quantiles` and write the three outputs."""
    check(challenger, entry, export, request, contracts)
    config = entry['config']
    levels = config['quantile_levels']
    median = levels.index('0.5')
    deadline = timestamp(request['deadline_at'])
    stop = deadline - DEADLINE_RESERVE
    started, began = clock(), time.monotonic()
    scores, records, latencies = {}, [], []
    timed_out = False
    for row in export.rows:
        path, reason = series.context(row, config['min_context_lags'])
        if path is not None and not 1 <= row.steps <= config['prediction_length']:
            path, reason = None, 'out_of_domain'
        if path is not None and (timed_out or clock() >= stop):
            timed_out, path, reason = True, None, 'timeout'
        if path is None:
            scores[row.row_id] = {'status': 'unavailable', 'reason': reason}
            continue
        tick = time.monotonic()
        try:
            quantiles = forecaster(path, row.steps)
            texts = [decimal_text(value) for value in quantiles]
            score = decimal_text(quantiles[median] - 1)
            if score is None or None in texts:
                raise ArithmeticError('non_finite_output')
        except ArithmeticError:
            scores[row.row_id] = {'status': 'unavailable', 'reason': 'non_finite_output'}
            continue
        except Exception as error:  # every model failure is a typed, counted result
            print(f'{row.row_id}: model_error {type(error).__name__}: {error}', file=sys.stderr, flush=True)
            scores[row.row_id] = {'status': 'unavailable', 'reason': 'model_error'}
            continue
        finally:
            latencies.append(time.monotonic() - tick)
        scores[row.row_id] = {'status': 'available', 'value': score}
        records.append({'schema_version': QUANTILES_VERSION, 'row_id': row.row_id, 'listing_id': row.listing_id,
                        'decision_session': row.decision, 'end_session': row.end_session, 'step': row.steps,
                        'context_points': len(path), 'quantile_levels': levels, 'ratio_quantiles': texts})
    generated = clock()
    if generated > deadline:
        fail('generation_time', 'the batch finished after its deadline; rerun as a new attempt')
    inputs = export.inputs
    results = [{**{field: copy.deepcopy(scope[field]) for field in numeric.SCOPE_FIELDS}, 'score': scores[scope['row_id']]}
               for scope in inputs['expected_rows']]
    forecast = numeric.seal({'schema_version': 'alpha-forecast-v1',
                             **{key: copy.deepcopy(request[key]) for key in ('batch_id', 'attempt_id', 'input_manifest_sha256',
                                                                             'feature_schema_sha256', 'model', 'score_semantics')},
                             'generated_at': utc(generated), 'results': results})
    feature_rows = numeric.read_artifact(export.path, inputs['features'], jsonl=True)
    numeric.validate_forecast(forecast, request, inputs, export.calendar, feature_rows, contracts)

    out.mkdir(parents=True, exist_ok=False)
    forecast_sha = provenance.write(out / 'forecast.json', forecast)
    quantiles_data = ''.join(provenance.canonical(record).decode('utf-8') + '\n' for record in records).encode('utf-8')
    (out / 'quantiles.jsonl').write_bytes(quantiles_data)
    statuses = Counter(score['status'] if score['status'] == 'available' else score['reason'] for score in scores.values())
    summary = {'batch_id': request['batch_id'], 'attempt_id': request['attempt_id'], 'horizon': challenger['horizon'],
               'input_manifest_sha256': inputs['input_manifest_sha256'], 'dataset_id': inputs['dataset_id'],
               'forecast_sha256': forecast['forecast_sha256'], 'forecast_file_sha256': forecast_sha,
               'quantiles_sha256': provenance.sha256(quantiles_data), 'rows': len(results),
               'results': dict(sorted(statuses.items()))}
    resources = {'started_at': utc(started), 'finished_at': utc(generated),
                 'elapsed_seconds': round(time.monotonic() - began, 3), 'model_load_seconds': round(load_seconds, 3),
                 'forecast_calls': len(latencies),
                 'latency_seconds': {name: None if value is None else round(value, 4) for name, value in (
                     ('mean', sum(latencies) / len(latencies) if latencies else None), ('p50', percentile(latencies, 0.5)),
                     ('p95', percentile(latencies, 0.95)), ('max', max(latencies) if latencies else None))},
                 'peak_rss_bytes': peak_rss_bytes(), 'torch_threads': config['torch_threads'],
                 'host': {'machine': platform.machine(), 'cpu': cpu_model(), 'system': platform.system()}}
    provenance.write(out / 'run.json', {'summary': summary, 'resources': resources})
    return provenance.plain({**summary, 'resources': resources})
