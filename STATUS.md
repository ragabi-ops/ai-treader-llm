# STATUS

Updated 2026-10-19. [tasks/BACKLOG.csv](tasks/BACKLOG.csv) is the task-state,
execution-order and cross-repository dependency authority. Run
`python3 scripts/backlog.py` before selecting work.

**Next task: HARD01 — finish permitted target-host hardware qualification (LLM project; in progress).**

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
  no numeric model or completed real sample dataset exists. DATA01 is complete:
  the hash-verified SEC EDGAR R11 receipt now links a reviewed nine-target plan
  with pinned platform identity/calendar provenance, one-month horizons, three
  chronological cutoff groups, 21-session embargo evidence and a protected test
  boundary. The plan is explicitly survivorship-biased historical reconstruction;
  expected analyses and outcomes are absent and labels remain separate. Training,
  RAG, export and promotion are not implemented.
  Offline structural checks
  do not establish semantic grounding, model quality, trading performance or authority.

## Next work

HARD01 is the next eligible local task and remains in progress. CPU ALPHA02 is
blocked until the external platform conformance, numeric export and protocol gates
XPLAT05/XPLAT06/XPLAT07 close. Hosted Codex/Claude
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
qualification. A completed reviewed sample dataset, point-in-time universe controls,
model/template captures and prospective evaluation are also outstanding; DATA01's
small R11 target plan is not training or performance evidence.

## Reviewed data-target validation (2026-10-19)

DATA01 is complete: `make check` passed 117 tests, 14 fixture commands and shell
syntax; `git diff --check` passed. The linked source/target validation also verified
all ten compressed and decoded SEC artifacts plus the pinned platform identity and
calendar files. The target plan contains nine rows across AAPL, GE and COST, with
three date-grouped splits and no labels. Platform listing IDs are snapshot-local
and must be re-exported after a database rebuild; historical ingestion was not
observed, so the plan uses public-information reconstruction and makes no model,
semantic, universe or trading-performance claim.

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
