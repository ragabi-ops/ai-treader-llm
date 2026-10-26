"""Downloaded Chronos-2 weights and their immutable manifest (repository, revision, license, hashes)."""
from __future__ import annotations

import re
import shutil
from pathlib import Path

from ai_treader_llm import numeric
from ai_treader_llm.chronos import provenance
from ai_treader_llm.numeric import fail

MANIFEST = 'weights-manifest.json'
MANIFEST_VERSION = 'chronos-weights-manifest-v1'
REPOSITORY = 'amazon/chronos-2'
LICENSE = 'apache-2.0'
FILES = ('config.json', 'model.safetensors')


def fetch(revision: str, out: Path) -> dict:
    """Download the pinned files at an exact commit and write the manifest; refuses an existing directory."""
    from huggingface_hub import HfApi, hf_hub_download

    if not re.fullmatch(r'[0-9a-f]{40}', revision):
        fail('provenance_mismatch', 'revision must be a full 40-character commit sha')
    info = HfApi().model_info(REPOSITORY, revision=revision)
    if info.sha != revision:
        fail('provenance_mismatch', f'hub resolved {info.sha}, not {revision}')
    licenses = sorted(tag.split(':', 1)[1] for tag in info.tags or [] if tag.startswith('license:'))
    if licenses != [LICENSE]:
        fail('provenance_mismatch', f'license tags {licenses} are not [{LICENSE}]')
    out.mkdir(parents=True, exist_ok=False)
    for name in FILES:
        hf_hub_download(REPOSITORY, name, revision=revision, local_dir=out)
    shutil.rmtree(out / '.cache', ignore_errors=True)   # the hub's download bookkeeping, not model content
    manifest = {'schema_version': MANIFEST_VERSION, 'repository': REPOSITORY, 'revision': revision, 'license': LICENSE,
                'model_card': f'https://huggingface.co/{REPOSITORY}/blob/{revision}/README.md',
                'files': [{'path': name, 'bytes': (out / name).stat().st_size,
                           'sha256': provenance.sha256((out / name).read_bytes())} for name in FILES]}
    provenance.write(out / MANIFEST, manifest)
    return manifest


def verify(directory: Path) -> tuple[dict, str]:
    """The manifest and its sha256, after every pinned file's bytes are re-hashed."""
    path = directory / MANIFEST
    data = path.read_bytes()
    manifest = numeric.loads(data.decode('utf-8'))
    if manifest.get('schema_version') != MANIFEST_VERSION or manifest.get('repository') != REPOSITORY:
        fail('schema', f'{path} is not a {MANIFEST_VERSION} manifest for {REPOSITORY}')
    if [item['path'] for item in manifest['files']] != list(FILES):
        fail('artifact_mismatch', 'weights manifest does not list exactly the pinned files')
    for item in manifest['files']:
        if provenance.sha256((directory / item['path']).read_bytes()) != item['sha256']:
            fail('artifact_mismatch', f'{item["path"]} bytes differ from the weights manifest')
    return manifest, provenance.sha256(data)
