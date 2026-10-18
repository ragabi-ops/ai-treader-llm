# STATUS

Updated 2026-10-19. [tasks/BACKLOG.csv](tasks/BACKLOG.csv) is the task-state,
execution-order and cross-repository dependency authority. Run
`python3 scripts/backlog.py` before selecting work.

**Next task: DATA01 — build reviewed real-data manifests and analysis targets (LLM project).**

HARD01 remains in progress, with existing edits preserved. Hosted-agent planning
AGENT00 is complete and extends the approved ALPHA00 scope; no runtime is switched.
See [architecture.md](architecture.md) for the cross-repository component and flow overview (ARCH01).

## Current state

- Contract v1/v2, CPU validation/evaluation tooling, private pinned inference,
  target-host endpoint validation, representative endpoint benchmarks and the
  read-only dashboard are delivered.
- The target host runs Qwen3-8B Q4_K_M through digest-pinned llama.cpp on an RTX 3080.
  Strict-schema output, forced tool-call parsing, GPU offload and tunnel recovery passed.
- Platform L03a/shared contract integration and platform L03b (XPLAT02: Go client,
  persisted run/attempt provenance, one same-evidence repair) are done; a live run
  against this endpoint returned a strict-schema reply that passed the v2 validator.
- Platform L03c revision 4 is frozen (XPLAT03 done); L03d is in progress and
  L03e not started (XPLAT04 in progress). Revision 5 requires separate approval.
- The host 8192/2048 candidate and existing uncommitted configuration edits are
  distinct from the earlier BENCH01 deployment; CTX01 qualifies the new configuration.
- Numeric v1 schemas, Python validators and synthetic shared fixtures are delivered.
  Numeric models, batch forecasting and text-attribute extraction remain planned;
  no numeric model or real reviewed dataset exists. Training, RAG, export and
  promotion are not implemented.
  Offline structural checks
  do not establish semantic grounding, model quality, trading performance or authority.

## Next work

DATA01 is the next eligible local task. CPU ALPHA02 follows only after DATA01 and
the external platform numeric export/protocol gates close. Hosted Codex/Claude
calls, strategy research and concise per-listing
records belong to the platform's AGENT tasks. This repository owns numeric jobs
and offline evaluation. TEXT01 evaluates provider-neutral captures from platform
AGENT04. HARD01 remains a prerequisite for GPU experiments; CTX01/TOOLS01 and
RAG/QLoRA/export remain lower-priority local-model work. Qwen is retained as an
optional comparator and for the separate L03 experiment, never a silent fallback.
No new task depends on L03e. Local personal operation may use hosted inference;
only explicitly permitted evidence may cross that provider boundary.

## Known limits

The benchmark measured endpoint behavior, not semantic truth or trading quality.
The host still lacks complete RAM topology, cooling, PSU and permitted-disk
qualification. Real reviewed datasets, survivorship/licensing controls,
model/template captures and prospective evaluation are also outstanding.

## Hosted-agent planning validation (2026-10-07)

AGENT00 is complete: LLM `make check` (102 tests plus contract fixtures), platform
`./scripts/validate.sh --package`, both `git diff --check` checks, combined dependency
DAG/mirror checks and Markdown relative-link/fence checks passed. Diagrams were not
independently rendered. New hosted task types and research-summary storage remain
planned; no provider call, database migration or target-host validation was performed.

## Numeric contract validation (2026-10-19)

ALPHA01 is complete in the LLM project: `make check` passed 110 tests, 12 fixture
commands and shell syntax. Strict numeric schemas, Python validation, synthetic
cross-language cases and canonical hash vectors are published. Platform Go
conformance remains XLLM02/platform ALPHA01; real data and model work remain open.
