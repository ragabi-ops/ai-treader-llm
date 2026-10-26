# AI-Treader LLM

CPU numeric research tooling and shared contracts for AI-Treader. The Go platform owns
calculations, orchestration, hosted Claude/OpenAI text analysis, portfolio/risk logic,
persistence and trade execution.

**Boundary (2026-10-27):** CPU only. No GPU, local LLM, Hermes, Kubernetes or
foundation-model training.

## Start here

- [Implementation reference](docs/IMPLEMENTATION_PLAN.md) — architecture and research scope; not task state.
- [Code design](docs/CODE_DESIGN.md) — ownership, APIs, data flow, persistence, and invariants.
- [Development/server runbook](docs/RUNBOOK.md) — setup and numeric job commands.
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

The checks need no Docker daemon. Analysis-sample and numeric
examples are synthetic. The SEC review and target plan contain provenance, IDs,
dates and hashes only; source payloads remain in the platform repository.

```text
contracts/       Versioned JSON Schemas; shared integration boundaries
configs/         Evaluation and numeric parameters
python/          CPU validators, input builder, numeric jobs, evaluator
scripts/         Backlog check
examples/        Synthetic analysis, sample, context, and prediction fixtures
tests/           Leakage, contract, and evaluation regression tests
docker/          CPU jobs image
compose.yaml     Optional CPU jobs container
docs/            Implementation/design references and operating runbooks
tasks/           Authoritative CSV backlog
```

Numeric v1 schemas, Python/Go conformance and platform PIT feature/label export are
implemented, as are the frozen protocol and CPU ridge/LightGBM jobs; Chronos-2 (CPU) and
text evaluation remain unimplemented.
Local general-LLM RAG, QLoRA, adapter export and deployment promotion are outside the
approved architecture.
The offline evaluator measures structural/reference validity. It never certifies
financial quality or authorizes promotion. Schemas and timestamp checks cannot detect misleading source
metadata or future facts hidden in prose; source provenance and reviewed labels
remain essential.

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
