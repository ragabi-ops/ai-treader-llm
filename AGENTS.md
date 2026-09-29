# Repository engineering workflow

## Start and choose work

1. Follow the user's current request. Check Git HEAD and status; preserve unrelated edits.
2. Read root `STATUS.md` and `tasks/BACKLOG.csv`, then run `python3 scripts/backlog.py`.
3. For “continue” or “next task,” use the lowest `execution_order` unfinished local
   task whose dependencies are done. External `ai-treader-platform` rows mirror gates;
   they do not transfer implementation ownership to this repository.
4. Read only the relevant sections of `docs/IMPLEMENTATION_PLAN.md`,
   `docs/CODE_DESIGN.md` and `docs/RUNBOOK.md`. The CSV owns state and order.
5. Mark work `in_progress` when implementation starts and `done` only after acceptance
   checks pass. Keep close-out evidence in the CSV notes; do not create one Markdown
   document per task.

## Boundaries

- The Go platform owns orchestration, deterministic financial calculations, risk,
  persistence, authorization and execution. The LLM is advisory and never approves a trade.
- No Hermes. Do not add GPU libraries to the Mac/CPU dependency environment.
- Contracts reject unknown fields. Preserve exact IDs, UTC cutoffs, hashes, JSON,
  source availability/revisions and typed unavailable data. Outcome labels never enter inputs.
- Structural grounding and fixture success do not prove semantic truth, performance or
  trading quality. Missing evidence stays unavailable.
- Keep models, datasets, secrets and generated artifacts out of Git. Pin model/runtime/
  adapter/dataset/prompt/schema provenance before claiming a reproducible deployment.
- Shared contract changes require a new version and passing fixtures in both repositories.
- Training, RAG, export and promotion remain unimplemented until their backlog rows close.
  Promotion never grants platform execution authority.

## Validate and hand off

- Run `make check` for code, contract, tracking or documentation changes.
- Validate Compose rendering and shell syntax for deployment changes; state when target-host
  GPU validation was not possible.
- Update CSV and root STATUS together. Report exact checks, unresolved limits, external
  blockers and the next eligible local task.
