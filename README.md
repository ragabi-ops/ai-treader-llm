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
# real SEC review; optional roots verify source bytes and platform identity/calendar files
uv run --frozen ai-treader-llm validate-source-review examples/data-review-v1/sec-edgar-r11.json
uv run --frozen ai-treader-llm validate-data-targets \
  examples/data-review-v1/sec-edgar-r11-analysis-targets.json
# numeric v1 (shared fixtures for platform ALPHA01)
uv run --frozen ai-treader-llm validate-numeric-input examples/numeric-v1/input-manifest.json
uv run --frozen ai-treader-llm validate-numeric-dataset examples/numeric-v1/dataset-manifest.json
uv run --frozen ai-treader-llm validate-alpha examples/numeric-v1/forecast.json \
  --request examples/numeric-v1/request.json \
  --input examples/numeric-v1/input-manifest.json
```

The CPU checks need no NVIDIA GPU or Docker daemon. Analysis-sample and numeric
examples are synthetic. The SEC review and target plan contain provenance, IDs,
dates and hashes only; source payloads remain in the platform repository.

Run the versioned endpoint benchmark through the private SSH tunnel; generated reports
stay in the ignored `artifacts/` directory:

```bash
uv run --frozen ai-treader-llm benchmark-endpoint \
  configs/benchmarks/endpoint-v1.json \
  --output artifacts/benchmarks/endpoint-v1.json
# disruptive: restarts only the named inference container, then verifies recovery
uv run --frozen ai-treader-llm benchmark-recovery \
  --output artifacts/benchmarks/recovery-v1.json
```

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

Numeric v1 schemas and Python validation are implemented; Go conformance, feature
export, model fitting, training, RAG, export, and promotion remain unimplemented.
The offline evaluators measure structural/reference validity and
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

Real-source review receipts keep provider data out of Git while pinning its capture
revision, manifest, compressed and decoded hashes, access-policy review, and universe
limitations. `validate-source-review --source-root DIR` verifies the receipt against
the external bundle. The linked R11 target plan pins the current platform listing-ID
snapshot, XNYS one-month horizons, three date-grouped chronological splits, exact
21-session embargo evidence and the held-out test boundary. `--platform-root DIR`
also verifies its identity/calendar source-file hashes. It is a reviewed curation
plan, not a completed sample dataset: expected analyses and outcomes are absent,
historical availability is reconstructed, the universe is survivorship-biased,
and it is ineligible for training or performance claims. Outcome labels stay separate.

Numeric v1 uses exact decimal strings and string-encoded positive int64 listing IDs.
The input manifest pins a calendar, feature definitions, universe policy, source
availability, corporate-action basis, and every expected output row. Prediction
requests and forecasts bind the input, model/training/config/code/runtime hashes,
score meaning, deadline, and complete result coverage. Labels live in a separate
artifact and are checked for maturity, date-grouped chronological splits, purged
label windows, and session embargoes. These checks establish contract consistency;
they do not establish the truth of supplied provenance or forecast quality.
