"""Feature-only batch prediction: frozen challenger + numeric-input-v1 -> alpha-forecast-v1.

No label artifact is read. The request must name the challenger's exact model pins,
and the job refuses to run when its own code or runtime hash differs from the
frozen ones. A row with any unavailable feature gets a typed unavailable score.
"""
from __future__ import annotations

import copy
import math
from datetime import datetime
from pathlib import Path

import numpy as np

from ai_treader_llm import numeric
from ai_treader_llm.alpha import models, provenance
from ai_treader_llm.alpha.data import Export
from ai_treader_llm.contracts import Contracts
from ai_treader_llm.numeric import fail


def utc(moment: datetime) -> str:
    return moment.isoformat(timespec='microseconds').replace('+00:00', 'Z')


def decimal_text(value: float) -> str | None:
    """Canonical decimal with at most 15 fractional digits; None when not representable."""
    if not math.isfinite(value) or abs(value) >= 1e20:
        return None
    text = f'{value:.15f}'.rstrip('0').rstrip('.')
    return '0' if text in ('-0', '') else text


def load_challenger(path: Path, arm: str) -> tuple[dict, dict, dict]:
    challengers = numeric.read_json(path)
    if challengers.get('schema_version') != 'alpha-challengers-v1' or arm not in challengers.get('arms', {}):
        fail('schema', f'not an alpha-challengers-v1 file with arm {arm}')
    entry = challengers['arms'][arm]
    data = numeric.artifact_path(path, {'path': entry['artifact_path']}).read_bytes()
    if provenance.sha256(data) != entry['model']['artifact_sha256']:
        fail('artifact_mismatch', f'{arm} artifact bytes differ from the frozen sha256')
    return challengers, entry, numeric.loads(data.decode('utf-8'))


def build_request(challengers: dict, entry: dict, export: Export, batch_id: str, attempt_id: str,
                  requested_at: datetime, deadline_at: datetime) -> dict:
    """A request naming the frozen pins, for local runs; the platform builds its own (ALPHA04)."""
    return {'schema_version': 'alpha-request-v1', 'batch_id': batch_id, 'attempt_id': attempt_id,
            'input_manifest_sha256': export.inputs['input_manifest_sha256'],
            'feature_schema_sha256': export.inputs['feature_schema']['feature_schema_sha256'],
            'requested_at': utc(requested_at), 'deadline_at': utc(deadline_at),
            'model': copy.deepcopy(entry['model']), 'score_semantics': copy.deepcopy(challengers['score_semantics'])}


def predict(challengers: dict, entry: dict, artifact: dict, export: Export, request: dict,
            generated_at: datetime, contracts: Contracts) -> dict:
    inputs = export.inputs
    numeric.validate_request(request, inputs, contracts)
    if request['model'] != entry['model'] or request['score_semantics'] != challengers['score_semantics']:
        fail('provenance_mismatch', 'request does not name the frozen challenger pins and score semantics')
    if inputs['feature_schema']['feature_schema_sha256'] != challengers['feature_schema_sha256'] \
            or list(export.feature_ids) != artifact['features']:
        fail('provenance_mismatch', 'input feature schema differs from the challenger')
    if any(scope['horizon']['label'] != challengers['horizon'] for scope in inputs['expected_rows']):
        fail('identity_mismatch', f'input horizon is not the challenger horizon {challengers["horizon"]}')
    for name, current in (('code', provenance.code()['sha256']), ('runtime', provenance.runtime()['sha256'])):
        if current != entry['model'][f'{name}_sha256']:
            fail('provenance_mismatch', f'{name} sha256 {current} differs from the frozen challenger')
    scored = [row for row in export.rows if row.x is not None]
    values = models.predict(artifact, np.array([row.x for row in scored], dtype=np.float64)) if scored else []
    scores = {row.row_id: decimal_text(float(value)) for row, value in zip(scored, values)}
    results = []
    for scope in inputs['expected_rows']:
        key = scope['row_id']
        if key not in scores:
            score = {'status': 'unavailable', 'reason': 'missing_features'}
        elif scores[key] is None:
            score = {'status': 'unavailable', 'reason': 'non_finite_output'}
        else:
            score = {'status': 'available', 'value': scores[key]}
        results.append({**{field: copy.deepcopy(scope[field]) for field in numeric.SCOPE_FIELDS}, 'score': score})
    forecast = numeric.seal({'schema_version': 'alpha-forecast-v1',
                             **{key: copy.deepcopy(request[key]) for key in ('batch_id', 'attempt_id', 'input_manifest_sha256',
                                                                             'feature_schema_sha256', 'model', 'score_semantics')},
                             'generated_at': utc(generated_at), 'results': results})
    feature_rows = numeric.read_artifact(export.path, inputs['features'], jsonl=True)
    numeric.validate_forecast(forecast, request, inputs, export.calendar, feature_rows, contracts)
    return forecast
