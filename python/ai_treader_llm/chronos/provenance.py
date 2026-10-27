"""Hashes that pin the Chronos job: canonical JSON, its code files and its isolated runtime."""
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
LOCK = ROOT / 'runtimes' / 'chronos' / 'uv.lock'
CODE_FILES = ('chronos/__init__.py', 'chronos/challenger.py', 'chronos/model.py', 'chronos/predict.py',
              'chronos/provenance.py', 'chronos/series.py', 'chronos/weights.py', 'contracts.py', 'numeric.py')
PACKAGES = ('chronos-forecasting', 'torch', 'transformers', 'accelerate', 'einops', 'numpy', 'pandas',
            'safetensors', 'huggingface-hub')


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


def write(path: Path, value) -> str:
    data = canonical(value)
    path.write_bytes(data)
    return sha256(data)


def code() -> dict:
    files = [{'path': f'python/ai_treader_llm/{name}', 'sha256': sha256((PACKAGE / name).read_bytes())} for name in CODE_FILES]
    return {'files': files, 'sha256': sha256(canonical(files))}


def runtime(threads: int) -> dict:
    """The runtime pin; threads is the frozen torch intra-op count the job sets."""
    def version(name):
        try:
            return metadata.version(name)
        except metadata.PackageNotFoundError:
            return 'absent'
    detail = {
        'python': platform.python_version(), 'implementation': platform.python_implementation(),
        'system': platform.system(), 'machine': platform.machine(),
        'packages': {name: version(name) for name in PACKAGES},
        'uv_lock_sha256': sha256(LOCK.read_bytes()) if LOCK.exists() else 'absent',
        'torch_threads': threads,
        'threads': {name: os.environ.get(name, '') for name in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS')},
    }
    return {'detail': detail, 'sha256': sha256(canonical(detail))}
