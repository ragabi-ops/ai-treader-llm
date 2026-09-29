# Delivery status

## Implemented

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
- Read-only operations dashboard with a same-origin status API, two-second polling,
  host/GPU/Docker/llama.cpp/deployment telemetry, five-minute browser-side resource
  history, state-change events, and strict allowlisted pipeline/training status files.
  It never exposes prompts, responses, environment variables, arbitrary files, or
  Docker logs.

## Not yet implemented or fully validated

- RAM module topology, sustained cooling/load behavior, PSU capacity, and permitted
  `/dev/sda` health. The Windows-owned NVMe devices are outside this deployment and
  must remain untouched.
- Representative latency/throughput/load benchmarks, sustained inference behavior,
  full tool-template suite capture, QLoRA fit, and training behavior.
- Go client/orchestrator, platform migrations, and Postgres registry integration.
- Real dataset collection, licensing, reviewed analysis targets, trading-calendar
  label construction, survivorship controls, and prospective financial evaluation.
- Reviewed tool-call suite population and model/template response capture.
- RAG ingestion/search, trainer, GPU scheduling lock, adapter export, or promotion.
- Semantic grounding (v2 grounding is structural; numeric claims are not checked
  against values), actual tool execution, performance, and financial evaluation
  metrics.

## Verified locally

- `make check`: 96 regression tests and all nine fixture commands passed (2026-09-29).
- Compose configuration and shell script syntax validation passed.
- Dashboard JavaScript syntax, monitoring Python compilation, service payload tests,
  Compose rendering with the pinned image, and `git diff --check` passed.
- CPU job image built on the Mac's Linux ARM64 Docker engine; the evaluation job
  completed successfully through Compose as a non-root, read-only, offline container.
- Input construction, Python compilation, and local documentation link checks passed.

Both offline evaluators always return `promotion_eligible: false`. Tool-call fixture
success checks proposed calls but does not execute a tool or prove financial quality.
No live platform integration or model promotion was performed.

## Verified on the target host

Verified on 2026-09-29 and 2026-09-30:

- The dedicated Mac SSH alias and key reach the host over wired LAN; DNS and NTP
  work. UFW is active and the operator installed the subnet-scoped TCP 8090 dashboard
  rule. The dashboard is reachable from the Mac over the LAN while inference remains
  bound only to server loopback.
- Ubuntu 26.04.1 boots kernel `7.0.0-34-generic` on a Ryzen 9 5900X with 32 GiB RAM.
- The NVIDIA kernel module and userspace both report `580.178.04`; `nvidia-smi`
  identifies an RTX 3080 with 10,240 MiB VRAM. The pinned CUDA container sees the
  GPU, and llama.cpp offloads the deployed model to it.
- The operator-approved interim layout uses only `/dev/sda`: `/dev/sda3` for `/`
  and `/dev/sda1` for `/data`. Both NVMe devices belong to Windows and are excluded.
  `/data` now mounts persistently by UUID and its artifact directories are owned by
  `ai-treader-llm`.
- Docker Engine 29.8.1, Compose 5.5.1, and NVIDIA Container Toolkit 1.20.1 are
  installed; Docker and containerd are enabled and active, the NVIDIA runtime is
  configured, and the GPU-container smoke passed.
- The operator explicitly accepted root-equivalent Docker-group membership for the
  dedicated `ai-treader-llm` account. Membership is active in fresh SSH sessions.
- The GitHub host key was pinned to GitHub's published Ed25519 key, the dedicated
  repository key authenticates successfully, and SSH file modes are restricted.
- The checkout is at `9d41f1c`. Qwen3-8B Q4_K_M is pinned to Hugging Face revision
  `7c41481f57cb95916b40956ab2f0b139b296d974` and verified SHA-256
  `d98cdcbd03e17ce47681435b5150e34c1417f50b5c0019dd560e4882c5745785`.
- Digest-pinned llama.cpp inference is healthy on host loopback port 8080. A first
  completion, strict-schema response, and forced tool-call parsing passed. The tiny
  warm smoke observed roughly 101 generated tokens/second, but that is not a
  representative benchmark or a production performance claim.
- The inference and dashboard systemd units are enabled and active. SSH socket
  activation and UFW are also enabled and active. The live dashboard reports the
  GPU, VRAM, inference, model/runtime provenance, host, and `/data` storage, and
  correctly reports degraded while no platform pipeline producer exists.
- A per-user Mac `launchd` agent maintains localhost forwards for private inference
  on port 18080 and the dashboard on port 18090. A controlled termination test on
  2026-09-30 restored both healthy endpoints automatically in two seconds. The direct
  LAN dashboard remains available at `http://192.168.50.182:8090/`.

## Deployment decision

Accepted 2026-09-29: retain digest-pinned Docker inference on the interim host, use
containers on demand for future training/evaluation, and run the read-only dashboard
as a restricted native service. Reassess native llama.cpp when the dedicated host is
commissioned, or earlier only for a repeated container-specific reliability or GPU
compatibility blocker. Preserve the HTTP contract and require an evidence-backed
latency/throughput/VRAM/startup/recovery comparison before changing runtimes.
