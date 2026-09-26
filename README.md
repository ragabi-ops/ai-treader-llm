# AI-Treader LLM

Local inference and future model-adaptation tooling for AI-Treader. The existing
Go platform owns tools, calculations, portfolio/risk logic, and trade execution.
This component supplies analysis through a private OpenAI-compatible endpoint.

**Initial target:** Ubuntu Server, RTX 3080 10 GB, 64 GB RAM, llama.cpp, and
Qwen3-8B Q4_K_M. No Hermes, Kubernetes, or foundation-model training.

## Start here

- [Complete implementation plan](docs/IMPLEMENTATION_PLAN.md) — hardware through integration and upgrades.
- [Code design](docs/CODE_DESIGN.md) — ownership, APIs, data flow, persistence, and invariants.
- [Development/server runbook](docs/RUNBOOK.md) — exact setup and first endpoint commands.
- [Delivery status](docs/STATUS.md) — implemented versus pending work.

## Local development on the Mac

With `uv` installed, from the repository root:

```bash
uv sync --frozen --python 3.12
make check
uv run --frozen ai-treader-llm build-inputs examples/samples.jsonl
```

The CPU checks need no NVIDIA GPU or Docker daemon. Example data is synthetic.

```text
contracts/       Versioned JSON Schemas; shared integration boundaries
configs/         Inference, proposed QLoRA, and evaluation settings
python/          CPU validators, input builder, evaluator, HTTP smoke client
scripts/         Model/runtime bootstrap and deployment helpers
manifests/       Artifact provenance conventions
prompts/         Prompt ownership and versioning
examples/        Synthetic analysis, sample, context, and prediction fixtures
tests/           Leakage, contract, and evaluation regression tests
docker/          CPU jobs image
compose.yaml     Private GPU inference and optional CPU jobs
docs/            Plan, design, runbook, and delivery status
```

Training, RAG, export, promotion, and Go integration are designed but not yet
implemented. The current evaluator measures structural/reference validity only.
It never certifies financial quality or authorizes promotion. Schemas and timestamp
checks cannot detect misleading source metadata or future facts hidden in prose;
source provenance and reviewed labels remain essential.
