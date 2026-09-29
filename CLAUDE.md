# Claude project entry point

Read [AGENTS.md](AGENTS.md), then [STATUS.md](STATUS.md) and
[tasks/BACKLOG.csv](tasks/BACKLOG.csv).

The Go platform at `../ai-treader-platform` owns financial calculations,
authorization, persistence and execution. This repository owns local-model contracts,
evaluation tooling, artifacts and private inference operations. Model output is advisory.

Use the backlog's execution order and dependencies; cross-repository mirror rows expose
external gates but do not transfer implementation ownership. Run `make check` before
closing code, contract or tracking work.

Keep this file a pointer, not a second rulebook.
