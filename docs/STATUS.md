# Delivery status

## Implemented in the skeleton

- Complete infrastructure-to-training plan and code/integration design.
- GPU inference Compose definition with loopback binding and isolated network.
- Immutable model downloader with LFS hash verification and image-digest pinning.
- Mount-aware systemd startup template and deployment runbook.
- Strict analysis, trusted context, sample, and initial tool argument schemas.
- CPU CLI: validate analysis/datasets, construct inputs, score saved predictions,
  and smoke-test an inference endpoint.
- Dataset checks for availability/ingestion cutoffs, content hashes, unique IDs,
  chronological split order, and target exclusion from constructed inputs.
- Synthetic fixtures, dependency locks, CPU job image, regression tests, and CI.
- Explicit configuration/module boundaries for later QLoRA, retrieval, export,
  evaluation expansion, and promotion.

## Not yet implemented or validated on hardware

- Ubuntu installation and physical server checks.
- RTX 3080 runtime fit, generation throughput, tool-template behavior, and QLoRA fit.
- Go client/orchestrator, platform migrations, and Postgres registry integration.
- Real dataset collection, licensing, reviewed analysis targets, temporal purge/
  embargo, near-duplicate checks, and prospective financial evaluation.
- RAG ingestion/search, trainer, GPU scheduling lock, adapter export, or promotion.
- Semantic grounding, tool execution, performance, and financial evaluation metrics.

## Verified locally during scaffolding

- `make check`: 22 regression tests and all three fixture commands passed.
- Compose configuration and shell script syntax validation passed.
- CPU job image built on the Mac's Linux ARM64 Docker engine; the evaluation job
  completed successfully through Compose as a non-root, read-only, offline container.
- Input construction, Python compilation, and local documentation link checks passed.

The structural evaluator always returns `promotion_eligible: false`. Hardware
checklist items stay open until executed on the target machine. No GPU inference,
model download, host provisioning, or live platform integration was performed.
