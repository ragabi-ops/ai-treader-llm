# AI-Treader LLM

Local inference and future model-adaptation tooling for AI-Treader. The existing
Go platform owns tools, calculations, portfolio/risk logic, and trade execution.
This component supplies analysis through a private OpenAI-compatible endpoint.

**Initial target:** Ubuntu Server, RTX 3080 10 GB, 64 GB RAM, llama.cpp, and
Qwen3-8B Q4_K_M. No Hermes, Kubernetes, or foundation-model training.

## Start here

- [Implementation reference](docs/IMPLEMENTATION_PLAN.md) — hardware, deployment and future integration design; not task state.
- [Code design](docs/CODE_DESIGN.md) — ownership, APIs, data flow, persistence, and invariants.
- [Development/server runbook](docs/RUNBOOK.md) — exact setup and first endpoint commands.
- [Operations dashboard](docs/OBSERVABILITY.md) — live sources and the sanitized pipeline/training status contract.
- [STATUS.md](STATUS.md) — concise handoff.
- [tasks/BACKLOG.csv](tasks/BACKLOG.csv) — authoritative local/external task state and order.

## Local development on the Mac

With `uv` installed, from the repository root:

```bash
uv sync --frozen --python 3.12
make check
uv run --frozen ai-treader-llm build-inputs examples/samples.jsonl
uv run --frozen ai-treader-llm validate-outcomes \
  examples/samples.jsonl examples/outcomes.jsonl --embargo-days 0
uv run --frozen ai-treader-llm validate-manifest examples/dataset-manifest.json
uv run --frozen ai-treader-llm evaluate-tools \
  examples/tool-call-fixtures.jsonl examples/tool-call-predictions.jsonl
# contract v2 (shared with the platform)
uv run --frozen ai-treader-llm validate-analysis examples/v2/analysis.json --context examples/v2/context.json
uv run --frozen ai-treader-llm validate-manifest examples/v2/dataset-manifest.json \
  --evaluation-boundary 2025-06-01T00:00:00Z
```

The CPU checks need no NVIDIA GPU or Docker daemon. Example data is synthetic.

```text
contracts/       Versioned JSON Schemas; shared integration boundaries
configs/         Inference, proposed QLoRA, and evaluation settings
python/          CPU validators, input builder, evaluator, HTTP smoke client
scripts/         Model/runtime bootstrap and deployment helpers
dashboard/       Read-only near-real-time host, inference, and pipeline UI
examples/        Synthetic analysis, sample, context, and prediction fixtures
tests/           Leakage, contract, and evaluation regression tests
docker/          CPU jobs image
compose.yaml     Private GPU inference and optional CPU jobs
docs/            Implementation/design references and operating runbooks
tasks/           Authoritative CSV backlog
```

Training, RAG, export, promotion, and Go integration are designed but not yet
implemented. The offline evaluators measure structural/reference validity and
fixture-based tool-call correctness. They never certify financial quality or
authorize promotion. Schemas and timestamp checks cannot detect misleading source
metadata or future facts hidden in prose; source provenance and reviewed labels
remain essential.

`evaluate-tools` checks saved calls against per-case allowlists, the strict schemas
in `contracts/tools/`, expected call names, and trusted symbol/as-of boundaries. It
counts missing, malformed, unauthorized, incorrect, unnecessary, schema-invalid,
and boundary-violating outputs explicitly. The included cases are synthetic and do
not execute tools or demonstrate that a deployed model/template emits valid calls.

Outcome records are validated from a separate JSONL file and are never accepted by
the sample schema or input builder. `validate-outcomes` requires exact sample
coverage and rejects label windows that cross chronological split boundaries. Use
`--embargo-days` to require an additional gap after the earlier split's latest
label end. This is dataset-integrity validation, not financial scoring.

Dataset manifests pin sample and optional outcome files by SHA-256 and row count.
Validation resolves only paths contained by the manifest directory, re-runs all
dataset checks, verifies split boundaries and analysis horizons, and requires
explicit licensing/reviewer status. The included manifest is synthetic-only.
