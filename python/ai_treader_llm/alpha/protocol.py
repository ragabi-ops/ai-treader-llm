"""The frozen ALPHA03 parameters (platform preregistrations id 2) and the trial draw."""
from __future__ import annotations

import hashlib
import itertools
import json
from pathlib import Path

import numpy as np

from ai_treader_llm.numeric import fail

# Raw sha256 of platform tasks/evidence/ALPHA03-parameters.json at the 2026-10-23 freeze;
# configs/numeric/alpha03-parameters.json is a byte-identical copy.
PARAMETERS_SHA256 = '5cba481a9204dbc66fe6c7771c4a82e808ae068303c78c2e95cd3d196afacac5'
DRAW_METHOD = 'numpy.random.Generator(PCG64(seed)).choice(grid size, trials, replace=False) over itertools.product of grid_keys'


def load(path: Path, expected_sha256: str = PARAMETERS_SHA256) -> tuple[dict, str]:
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != expected_sha256:
        fail('provenance_mismatch', f'protocol parameters sha256 {digest} is not the frozen {expected_sha256}')
    return json.loads(data), digest


def trials(params: dict) -> list[dict]:
    """Every fitted trial, numbered before any fit: ridge alphas, then the seeded LightGBM draw."""
    ridge, boost = params['arms']['R'], params['arms']['G']
    out = [{'trial': i + 1, 'arm': 'R', 'config': {'alpha': alpha}} for i, alpha in enumerate(ridge['alpha'])]
    if len(out) != ridge['trials']:
        fail('schema', 'ridge grid size differs from its trial budget')
    keys = boost['grid_keys']
    grid = list(itertools.product(*(boost['grid'][key] for key in keys)))
    picks = np.random.Generator(np.random.PCG64(boost['seed'])).choice(len(grid), size=boost['trials'], replace=False)
    for pick in picks.tolist():
        out.append({'trial': len(out) + 1, 'arm': 'G', 'grid_index': pick, 'config': dict(zip(keys, grid[pick]))})
    return out
