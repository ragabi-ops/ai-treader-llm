# STATUS

Updated 2026-10-27. [tasks/BACKLOG.csv](tasks/BACKLOG.csv) is the task-state,
execution-order and cross-repository dependency authority. Run
`python3 scripts/backlog.py` before selecting work.

**Next task: ALPHA03 — evaluate pinned Chronos-2 on CPU as a batch challenger (LLM project; mirrored by platform XLLM04).**

CLEAN02 (2026-10-27): no GPU and no local LLM. Prediction is CPU numeric only (ridge,
LightGBM, Chronos-2 on CPU). Text analysis (filings, reports, news, events) goes to hosted
Claude/OpenAI agents on the platform. The llama.cpp/Qwen deployment, benchmarks,
hardware qualification and dashboard were removed; HARD01, CTX01 and XPLAT04 are retired.
See [architecture.md](architecture.md) for the cross-repository overview (ARCH01).

## Current state

- Contract v1/v2 and CPU validation/evaluation tooling are delivered. Contract v2 stays
  vendored by the platform.
- The target host still runs the retired Qwen inference and dashboard services until the
  operator stops them (`systemctl disable --now ai-treader-llm ai-treader-dashboard`).
  Numeric jobs do not use them.
- Numeric v1 contracts and fixtures are shared with the platform Go validator (68 cases).
- ALPHA02: CPU ridge/LightGBM `alpha-train` and feature-only `alpha-predict` under the
  frozen ALPHA03 protocol. Platform ALPHA05 read the 2025 retrospective test once
  (XPLAT08); its §4 gate passed.
- ALPHA02a (platform XLLM06, 2026-10-27): an `observed` input may be created after its
  decision close and before its cutoff; sources ingested after creation are still
  refused. Challenger pins were re-issued under the new code hash in
  `/data/training/alpha03/{1m,3m}-xllm06-*`. The model artifacts are byte-identical to
  the XLLM03 ones, and only `code_sha256` changed. `/srv/ai-treader` runs this code
  (671f85f), so the older pins no longer predict.
- DATA01's SEC R11 target plan is a small survivorship-biased reconstruction and not
  training or performance evidence. Chronos-2 on CPU (ALPHA03) and text attributes
  (TEXT01) remain planned.

## Next work

ALPHA03 is next: Chronos-2 on CPU, run in the existing isolated numeric job. On the
platform, ALPHA03 revision 2 is frozen and the forward run (ALPHA09) is unblocked. The
pinned code (`alpha/*`, `contracts.py`, `numeric.py`) must not change while ALPHA09 runs,
so Chronos goes in new modules with its own pins.

## Known limits

Validation rank
correlations and retrospective figures are diagnostics on a survivorship-biased pilot,
not trading evidence. Per-task validation detail lives in the backlog notes.
