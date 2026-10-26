# AI-Treader LLM-repository implementation plan

Accepted architecture, revised 2026-10-27 (CLEAN02). This document describes
implementation shape, not task state. See [STATUS](../STATUS.md), [the backlog](../tasks/BACKLOG.csv)
and [CODE_DESIGN.md](CODE_DESIGN.md). Git history holds the earlier GPU/llama.cpp plan.

## 1. Architecture

| Concern | Decision |
|---|---|
| Prediction | CPU numeric batch jobs only: regularized linear, LightGBM, then pinned Chronos-2 on CPU |
| Text (filings, reports, news, events) | Hosted Claude/OpenAI agents, owned by the platform; this repo evaluates reviewed exports (TEXT01) |
| GPU / local LLM | None. Qwen/llama.cpp, L03, HARD01 and CTX01 were retired on 2026-10-27 |
| Orchestration, finance, persistence | Go platform + PostgreSQL |
| Artifacts | Hashed, on disk under `/data`, outside Git |
| Host | Ubuntu Server on the existing machine; Linux may use only `/dev/sda` (both NVMe devices belong to Windows) |

```text
Mac ── SSH / Git ──► Ubuntu host (/srv/ai-treader, CPU only)
 │                     └─ one-shot numeric fit/predict jobs (uv, locked env)
Go platform ── export snapshot → batch job → strict import → mapping → policy/risk → paper ledger
Go platform ── bounded evidence → hosted agents → cited structured features → ablation
```

No model holds trade-execution tools or credentials. Hermes is excluded. No daemon,
queue, vector service or experiment database is added. Reintroducing a GPU or a local
LLM requires a new explicit architecture decision, a measured gap and a bounded
backlog row.

## 2. Workflow

Edit on the Mac, commit, push, and pull the exact commit into `/srv/ai-treader`. Run
Linux jobs there with `uv` or the `jobs` Compose profile. Large artifacts stay under
`/data`. Avoid remotely mounted source; use rsync only for explicit artifact transfers.

## 3. Data and leakage controls

| Information | Mechanism |
|---|---|
| Prices, ratios, indicators, exposure, returns | Structured APIs and deterministic Go calculations |
| Filings, reports, news, events | Platform point-in-time evidence; hosted agents read it and return cited features |

- Track event time, availability time, ingestion time and revision; include only what
  is available by the cutoff (faithful replay also requires ingestion by then).
- Preserve original filings and unrevised fundamentals; restatements never replace
  historical inputs.
- Outcome labels stay outside every prediction input and prompt. The supervised trainer
  reads training labels under its split policy; evaluation labels stay in evaluation.
- Chronological splits with purge/embargo for overlapping label windows; preserve
  historical universes, delistings and point-in-time corporate actions.
- Pretraining contamination is possible (Chronos-2 and hosted models may know later
  events). Retrospective results are diagnostic; confirm prospectively after a freeze.

## 4. Supervised research scope (approved 2026-10-06)

| Work | This repository | Platform |
|---|---|---|
| Numeric contracts | ALPHA01: alpha-forecast-v1, numeric dataset schemas, fixtures (delivered) | Go conformance (delivered) |
| Dataset | DATA01: reviewed R11 receipt and target plan (delivered) | PIT features and separate labels (delivered) |
| CPU baseline | ALPHA02/02a: ridge/LightGBM training and feature-only prediction (delivered) | ALPHA03 protocol, ALPHA04 import, ALPHA05 replay (delivered) |
| Pretrained challenger | ALPHA03: pinned Chronos-2 on CPU, no fine-tuning | XLLM04 mirror; ALPHA06 compares under separately frozen parameters |
| Text attributes | TEXT01: evaluate reviewed hosted exports, publish numeric fixtures | AGENT04 captures; ALPHA07 numeric-only vs numeric-plus-text |
| Forward evidence | Immutable artifacts, reproducible jobs | ALPHA09 forward run; operator decides any promotion |

Daily features, 1-month and 3-month targets, weekly decisions; a horizon never forces
an exit by itself. The pilot universe is survivorship-biased and proves plumbing only.
Candidate decisions follow held-out and matured forward evidence including costs,
delays, drawdown, turnover, exposure and failures. CatBoost may be compared if
categorical features justify it. PatchTST/TFT training, RL and intraday stay deferred.
Platform ALPHA08 decides whether to combine models; it does not activate a blend.

**Chronos-2 (ALPHA03).** Pin the model revision, license and CPU runtime
([model card](https://huggingface.co/amazon/chronos-2)). Use the same cutoff, features
and target as the frozen comparison. Check quantile coverage, disclose pretraining
overlap, measure CPU latency and memory, and export every prediction and failure.
The ALPHA02 pinned code (`alpha/*`, `contracts.py`, `numeric.py`) must not change while
the platform's ALPHA09 forward run uses its pins, so Chronos lives in new modules with
its own pins. General forecasting benchmarks are not evidence of trading performance.

## 5. Evaluation boundaries

Compare candidates on identical versioned inputs and budgets. Hosted research, numeric
baselines, Chronos and text-feature ablations are separate protocols; a result in one
does not promote another. Report failures rather than dropping them. Financial
evaluation freezes the downstream signal, portfolio and risk rules and compares
walk-forward returns, drawdown, turnover and exposure after costs. Analysis-quality
scores stay separate from financial results.

## 6. Hosted-agent ownership (2026-10-07)

Platform AGENT01–06 deliver the call instructions, qualified adapters, bounded
proposals and backtests, text capture, as-of research records and evaluation
machinery. AGENT07 is the frozen matured paper evaluation and now also gates broker
access (B00s). TEXT01 consumes AGENT04 captures via XPLAT09. It does not own provider
credentials, provider calls or application database writes. No provider or model is
silently substituted during an experiment.
