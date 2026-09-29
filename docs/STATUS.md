# Delivery status

## Implemented in the skeleton

- Complete infrastructure-to-training plan and code/integration design.
- GPU inference Compose definition with loopback binding and isolated network.
- Immutable model downloader with LFS hash verification and image-digest pinning.
- Mount-aware systemd startup template and deployment runbook.
- Strict analysis, trusted context, sample, and initial tool argument schemas.
- CPU CLI: validate analysis/datasets, construct inputs, score saved predictions,
  and smoke-test an inference endpoint.
- Offline tool-call fixture evaluator for allowlisted names, strict arguments,
  trusted symbol/time boundaries, required/unnecessary calls, and categorized
  failure accounting.
- Dataset checks for availability/ingestion cutoffs, content hashes, unique IDs,
  chronological split order, and target exclusion from constructed inputs.
- Strict, separately stored outcome records with exact sample coverage, finite
  values, label-window split purging, and configurable calendar-day embargo.
- Deterministic cross-split normalized exact and high-similarity sample-input checks.
- Immutable dataset-manifest validation for contained artifact paths, hashes, row
  counts, split summaries, horizons, purge policy, licensing, and review metadata.
- Contract v2 (platform L03a): listing-ID envelope with explicit XNYS horizon
  sessions, replay mode, typed source metadata, typed unavailable inputs and a
  canonical context hash; structural claim-to-source grounding with shared error
  codes; outcome records that admit typed unavailable measures; v2 samples and
  manifests with platform-stated session embargoes; `validate-manifest
  --evaluation-boundary`; shared valid/invalid fixtures the platform's Go
  validator also passes. v1 remains readable.
- Synthetic analysis, dataset, outcome, and tool-call fixtures; dependency locks;
  CPU job image; regression tests; and CI.
- Explicit configuration/module boundaries for later QLoRA, retrieval, export,
  evaluation expansion, and promotion.

## Not yet implemented or validated on hardware

- Ubuntu installation and physical server checks.
- RTX 3080 runtime fit, generation throughput, tool-template behavior, and QLoRA fit.
- Go client/orchestrator, platform migrations, and Postgres registry integration.
- Real dataset collection, licensing, reviewed analysis targets, trading-calendar
  label construction, survivorship controls, and prospective financial evaluation.
- Reviewed tool-call suite population and model/template response capture.
- RAG ingestion/search, trainer, GPU scheduling lock, adapter export, or promotion.
- Semantic grounding (v2 grounding is structural; numeric claims are not checked
  against values), actual tool execution, performance, and financial evaluation
  metrics.

## Verified locally during scaffolding

- `make check`: 88 regression tests and all nine fixture commands passed (2026-09-29).
- Compose configuration and shell script syntax validation passed.
- CPU job image built on the Mac's Linux ARM64 Docker engine; the evaluation job
  completed successfully through Compose as a non-root, read-only, offline container.
- Input construction, Python compilation, and local documentation link checks passed.

Both offline evaluators always return `promotion_eligible: false`. Tool-call fixture
success checks proposed calls but does not execute a tool or prove model/template
behavior. Hardware checklist items stay open until executed on the target machine.
No GPU inference, model download, host provisioning, or live platform integration
was performed.
