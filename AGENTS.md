# Repository guidance

Read `docs/STATUS.md` and `docs/CODE_DESIGN.md` before changing architecture.
The accepted scope is in `docs/IMPLEMENTATION_PLAN.md`.

- Keep production orchestration, deterministic financial calculations, risk, and
  execution in the existing Go platform. Never give the LLM trade authority.
- No Hermes. Do not add GPU libraries to the Mac/CPU dependency environment.
- Contracts reject unknown fields. Preserve UTC as-of boundaries and source
  availability/revision metadata. Outcome labels must never enter model inputs.
- Do not claim that structural evaluation proves grounding or trading quality.
- Keep models, datasets, secrets, and generated artifacts out of Git.
- Update delivery status accurately; reserved modules are not completed features.
- Run `make check` for Python/contract changes. Validate Compose syntax separately;
  document when GPU/server validation was not possible.
