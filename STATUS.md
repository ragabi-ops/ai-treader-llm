# STATUS

Updated 2026-10-27. [tasks/BACKLOG.csv](tasks/BACKLOG.csv) is the task-state,
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
  target-host endpoint validation, endpoint benchmarks and the read-only dashboard are
  delivered.
- The target host runs Qwen3-8B Q4_K_M through digest-pinned llama.cpp on an RTX 3080,
  used only by the platform L03 experiment. L03d is in progress; revision 5 (CTX01
  path) needs separate operator approval.
- Numeric v1 contracts and fixtures are shared with the platform Go validator (68 cases).
- ALPHA02: CPU ridge/LightGBM `alpha-train` and feature-only `alpha-predict` under the
  frozen ALPHA03 protocol. Platform ALPHA05 read the 2025 retrospective test once
  (XPLAT08); its §4 gate passed.
- ALPHA02a (platform XLLM06, 2026-10-27): an `observed` input may be created after its
  decision close and before its cutoff; sources ingested after creation are still
  refused. Challenger pins were re-issued under the new code hash in
  `/data/training/alpha03/{1m,3m}-xllm06-*`. The model artifacts are byte-identical to
  the XLLM03 ones, and only `code_sha256` changed. The older pins stop predicting once
  `/srv/ai-treader` runs this code.
- DATA01's SEC R11 target plan is a small survivorship-biased reconstruction and not
  training or performance evidence. Chronos-2 (ALPHA03) and text attributes (TEXT01)
  remain planned.

## Next work

HARD01 is the next local task; it is needed before GPU experiments such as ALPHA03.
On the platform, ALPHA03e (operator freezes ALPHA03 revision 2 citing the re-issued
pins) gates the forward run (ALPHA09).

## Known limits

The benchmark measured endpoint behavior, not semantic truth or trading quality. The
host lacks full RAM, cooling, PSU and permitted-disk qualification. Validation rank
correlations and retrospective figures are diagnostics on a survivorship-biased pilot,
not trading evidence. Per-task validation detail lives in the backlog notes.
