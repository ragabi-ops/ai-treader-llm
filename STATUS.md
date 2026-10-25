# STATUS

Updated 2026-10-26. [tasks/BACKLOG.csv](tasks/BACKLOG.csv) is the task-state,
execution-order and cross-repository dependency authority. Run
`python3 scripts/backlog.py` before selecting work.

**Next task: HARD01 — finish permitted target-host hardware qualification (LLM project; in progress).**

HARD01 remains in progress, with existing edits preserved. The architecture now
keeps local Qwen only for the existing L03 experiment; speculative local tool-suite,
RAG, QLoRA, GGUF-export and deployment-promotion tasks have been removed.
Their dead evaluator/config/package scaffolding and 15 subsystem-only tests are also
removed; the retained suite protects active contract, data, runtime and monitoring boundaries.
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
  distinct from the earlier BENCH01 deployment; CTX01 qualifies the new configuration
  only if the separate L03 revision-5 path proceeds.
- Numeric v1 schemas, Python/Go validators and synthetic shared conformance fixtures are delivered.
- ALPHA02 is complete: locked CPU ridge/LightGBM training under the frozen ALPHA03
  protocol and feature-only batch prediction (`alpha-train`, `alpha-predict`, numeric
  extra). Frozen 1m and 3m challengers trained on the platform pilot development
  exports live under `/data/training/alpha03/` on the target host; their pins are
  mirrored in platform `tasks/evidence/XLLM03-challengers-*.json`. Validation rank
  correlations are selection diagnostics, not trading evidence; the 2025 test was not
  read. Chronos-2 and text-attribute extraction remain planned. DATA01 is complete:
  the hash-verified SEC EDGAR R11 receipt now links a reviewed nine-target plan
  with pinned platform identity/calendar provenance, one-month horizons, three
  chronological cutoff groups, 21-session embargo evidence and a protected test
  boundary. The plan is explicitly survivorship-biased historical reconstruction;
  expected analyses and outcomes are absent and labels remain separate. Local
  general-LLM RAG/adaptation/export/promotion is outside the approved architecture.
  Offline structural checks
  do not establish semantic grounding, model quality, trading performance or authority.

## Next work

Platform ALPHA01–03 (mirrors XPLAT05–07) and CPU ALPHA02 here (platform XLLM03) are
done. Platform ALPHA04 orchestration is next on the numeric path; it invokes these
jobs and validates and persists their forecasts. Platform is not waiting on this
repository for it.

HARD01 remains the next eligible local task in parallel and is required only before
GPU experiments such as ALPHA03; it does not block the platform numeric path. CTX01
belongs only to the separate, still-unapproved L03 revision-5 path. Platform AGENT04
implemented the text-capture workflow, but XPLAT09 remains open because no real capture
set, human-reviewed target or TEXT01 export exists yet. Hosted calls and persistence
remain platform-owned; this repository owns numeric batch jobs and offline evaluation.
No new task depends on L03e. Only explicitly permitted evidence may cross a hosted
provider boundary.

## Known limits

The benchmark measured endpoint behavior, not semantic truth or trading quality.
The host still lacks complete RAM topology, cooling, PSU and permitted-disk
qualification. A completed reviewed numeric dataset, point-in-time universe controls,
real human-reviewed text captures and prospective evaluation are also outstanding; DATA01's
small R11 target plan is not training or performance evidence.

## CPU numeric jobs validation (2026-10-26)

ALPHA02 is complete: `make check` passed on the target host (102 contract and 11
numeric-job tests, 13 fixture commands, shell syntax); `make check-core` passed on the
Mac, where LightGBM cannot load without libomp. On the real 1m development export
(3,591 rows, 189 decisions, 3,157 usable) all 25 trials completed; ridge α=1000 and
LightGBM trial 23 were selected (mean validation rank correlation −0.0066 and +0.0622;
momentum reference +0.0463). The 3m family selected ridge α=1000 (+0.0198) and
LightGBM trial 20 (+0.0829; momentum −0.0073). A rerun reproduced every artifact byte
for byte. The pilot is survivorship-biased and uses reconstruction availability.

## Scope cleanup validation (2026-10-23)

CLEAN01 is complete: `make check` passed 102 retained tests, 13 fixture commands and
shell syntax. CLI help, Python compilation, all 50 JSON/JSONL files, dashboard
JavaScript and `git diff --check` also passed. The cleanup did not change the pinned
Qwen model, runtime, Compose deployment or platform code, so no target-host GPU
validation was required.

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
