"""Hashes that pin a numeric job: canonical JSON, code files and the runtime."""
from __future__ import annotations

import hashlib
import math
import os
import platform
from importlib import metadata
from pathlib import Path

from ai_treader_llm import numeric

PACKAGE = Path(__file__).resolve().parents[1]
ROOT = PACKAGE.parents[1]
CODE_FILES = ('alpha/__init__.py', 'alpha/data.py', 'alpha/models.py', 'alpha/predict.py', 'alpha/protocol.py',
              'alpha/provenance.py', 'alpha/train.py', 'contracts.py', 'numeric.py')


def plain(value):
    """JSON-safe copy: floats become their repr strings (canonical JSON forbids floats)."""
    if isinstance(value, float):
        return repr(value) if math.isfinite(value) else str(value)
    if isinstance(value, dict):
        return {key: plain(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(child) for child in value]
    return value


def canonical(value) -> bytes:
    return numeric.canonical_json(plain(value))


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def code() -> dict:
    files = [{'path': f'python/ai_treader_llm/{name}', 'sha256': sha256((PACKAGE / name).read_bytes())} for name in CODE_FILES]
    return {'files': files, 'sha256': sha256(canonical(files))}


def runtime() -> dict:
    lock = ROOT / 'uv.lock'
    detail = {
        'python': platform.python_version(), 'implementation': platform.python_implementation(),
        'system': platform.system(), 'machine': platform.machine(),
        'packages': {name: metadata.version(name) for name in ('numpy', 'scipy', 'lightgbm')},
        'uv_lock_sha256': sha256(lock.read_bytes()) if lock.exists() else 'absent',
        'threads': {name: os.environ.get(name, '') for name in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS')},
    }
    return {'detail': detail, 'sha256': sha256(canonical(detail))}
