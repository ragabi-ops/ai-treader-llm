#!/usr/bin/env bash
set -euo pipefail
# On Mac use the default SSH-forwarded port. On server pass http://127.0.0.1:8080.
uv run --frozen ai-treader-llm smoke --base-url "${1:-http://127.0.0.1:18080}"
