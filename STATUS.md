# STATUS

Updated 2026-10-01. [tasks/BACKLOG.csv](tasks/BACKLOG.csv) is the task-state,
execution-order and cross-repository dependency authority. Run
`python3 scripts/backlog.py` before selecting work.

**Next task: HARD01 — finish permitted target-host hardware qualification.**

## Current state

- Contract v1/v2, CPU validation/evaluation tooling, private pinned inference,
  target-host endpoint validation, representative endpoint benchmarks and the
  read-only dashboard are delivered.
- The target host runs Qwen3-8B Q4_K_M through digest-pinned llama.cpp on an RTX 3080.
  Strict-schema output, forced tool-call parsing, GPU offload and tunnel recovery passed.
- Platform L03a/shared contract integration and platform L03b (XPLAT02: Go client,
  persisted run/attempt provenance, one same-evidence repair) are done; a live run
  against this endpoint returned a strict-schema reply that passed the v2 validator.
- Training, RAG, export and promotion are not implemented. Offline structural checks
  do not establish semantic grounding, model quality, trading performance or authority.

## Next work

HARD01 is the next eligible local task, followed by TOOLS01 and DATA01. Platform
L03b is complete; later RAG, training, export and promotion rows show their
dependencies in the CSV.

## Known limits

The benchmark measured endpoint behavior, not semantic truth or trading quality.
The host still lacks complete RAM topology, cooling, PSU and permitted-disk
qualification. Real reviewed datasets, survivorship/licensing controls,
model/template captures and prospective evaluation are also outstanding.
