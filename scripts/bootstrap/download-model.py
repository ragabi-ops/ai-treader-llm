#!/usr/bin/env python3
"""Resolve an immutable HF revision and verify LFS SHA-256 before publishing a model."""
import argparse
import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
from urllib.request import urlopen

REPO = "Qwen/Qwen3-8B-GGUF"
FILENAME = "Qwen3-8B-Q4_K_M.gguf"


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, default=Path("/data/models"))
    parser.add_argument("--revision", default="main", help="Resolved once to a full commit SHA")
    args = parser.parse_args()
    api = f"https://huggingface.co/api/models/{REPO}/revision/{quote(args.revision, safe='')}?blobs=true"
    with urlopen(api, timeout=60) as response:
        metadata = json.load(response)
    revision = metadata["sha"]
    if not re.fullmatch(r"[a-f0-9]{40}", revision):
        raise ValueError("Hugging Face did not return an immutable commit SHA")
    record = next(item for item in metadata["siblings"] if item["rfilename"] == FILENAME)
    expected = record["lfs"]["sha256"]
    if not re.fullmatch(r"[a-f0-9]{64}", expected):
        raise ValueError("missing trusted LFS SHA-256")
    args.destination.mkdir(parents=True, exist_ok=True)
    target = args.destination / FILENAME
    if target.exists():
        if sha256(target) != expected:
            raise ValueError("existing model differs; use a new versioned destination")
    else:
        descriptor, temporary = tempfile.mkstemp(prefix=".model-", suffix=".part", dir=args.destination)
        try:
            with os.fdopen(descriptor, "wb") as output:
                with urlopen(f"https://huggingface.co/{REPO}/resolve/{revision}/{FILENAME}", timeout=120) as response:
                    for chunk in iter(lambda: response.read(8 * 1024 * 1024), b""):
                        output.write(chunk)
            if sha256(Path(temporary)) != expected:
                raise ValueError("downloaded model failed SHA-256 verification")
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    # mkstemp intentionally creates mode 0600. The inference container runs with
    # its image user and mounts this directory read-only, so publish verified model
    # bytes as world-readable without granting write access to anyone but the owner.
    target.chmod(0o644)
    receipt = {"repository": REPO, "revision": revision, "filename": FILENAME,
               "sha256": expected, "bytes": target.stat().st_size,
               "verified_at": datetime.now(timezone.utc).isoformat()}
    manifest = target.with_suffix(".manifest.json")
    manifest.write_text(json.dumps(receipt, indent=2) + "\n")
    manifest.chmod(0o644)
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
