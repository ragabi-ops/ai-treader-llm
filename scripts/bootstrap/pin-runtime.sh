#!/usr/bin/env bash
# Run from repository root. Pulls only; does not start inference.
set -euo pipefail
image='ghcr.io/ggml-org/llama.cpp:server-cuda'
docker pull --platform linux/amd64 "$image"
digest=$(docker image inspect "$image" --format '{{index .RepoDigests 0}}')
if [[ "$digest" != ghcr.io/ggml-org/llama.cpp@sha256:* ]]; then
  printf 'Unexpected image digest: %s\n' "$digest" >&2
  exit 1
fi
mkdir -p configs
printf 'LLAMA_IMAGE=%s\n' "$digest" > configs/runtime.lock.env
printf 'Pinned runtime in configs/runtime.lock.env. Copy this digest into deployment provenance after GPU validation.\n'
