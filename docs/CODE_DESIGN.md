# Code design

## Ownership and dependency direction

```text
Existing Go platform
  hosted research via the Codex/Claude review bridge
    → canonical role/template + bounded evidence → strict review/proposal
    → Go-owned strategy versions/backtests + concise PostgreSQL research records
  numeric batch orchestration
    → hashed feature export → isolated CPU job here → strict forecast import
    → versioned mapping → existing policy / risk → paper ledger

This repository
  contracts/ → Python contract validator
                  ↓
             dataset integrity → input builder
                  ↓
             offline evaluation → versioned report
  numeric batch job → locked CPU fit/predict → forecast artifact
```

Dependencies flow toward contracts; no module imports trading execution code.
There is no standalone gateway, queue, vector database, or model registry service.

There is no GPU, local LLM or inference service (CLEAN02, 2026-10-27). Jobs run
one-shot on CPU, on the Mac or the target host.

## Runnable modules

| Module | Public boundary | Responsibility |
|---|---|---|
| `contracts.py` | `Contracts.validate`, `Contracts.analysis` | JSON Schema, trusted request identity, and evidence/metric references |
| `contracts_v2.py` | `validate_context`, `validate_analysis`, `context_hash` | Contract v2: trusted envelope, canonical hash, shared-code grounding checks |
| `contract_fixtures.py` | `build` / `python -m ai_treader_llm.contract_fixtures` | Generates the shared v2 fixtures and v2 examples; tests fail on drift |
| `datasets/samples.py` | `validate_sample`, `validate_dataset` | Source availability, ingestion cutoff, content hashes, IDs, chronological split order |
| `datasets/samples.py` | `build_messages` | Fixed prompt plus validated sources; never serializes target/outcome fields |
| `datasets/duplicates.py` | `validate_cross_split_duplicates` | Deterministic cross-split exact/near-duplicate sample-input checks |
| `datasets/outcomes.py` | `validate_outcomes` | Separate labels, exact sample coverage, finite values, split purge/embargo |
| `datasets/manifests.py` | `validate_manifest` | Artifact hashes/counts, contained paths, split/policy/provenance consistency |
| `datasets/reviews.py` | `validate_source_review` | Real-source receipts, external compressed/decoded bytes, linked target-plan hash and source coverage |
| `datasets/targets.py` | `validate_data_targets` | Reviewed identities/horizons, cutoff-group splits, explicit session embargo, held-out boundary and absent labels |
| `evaluation/runner.py` | `evaluate` | Counts every expected sample; missing/invalid responses are failures |
| `cli.py` | CLI entry point | Local jobs, JSON output, stable success/failure exit codes |

The CLI runs from the repo root by default. For another working directory, supply
`--contracts /absolute/path/to/contracts` before the subcommand. Schema resources
resolve locally; remote schema retrieval is not enabled.

Exit codes: `0` completed with no contract failures; `1` evaluation includes failed
predictions; `2` invalid input or operational failure. JSON reports go to stdout;
errors go to stderr. The evaluator never permits model promotion.

## Dataset design refinement

The planning sketch included arbitrary `model_input` and multiple snapshot fields.
The executable contract instead normalizes snapshots into typed `sources[]`, each
with content, hash, revision, availability, ingestion, and evidence/metric IDs.
`build_messages` derives input from these validated fields. This removes a second,
unchecked input blob where future outcomes could otherwise hide.

`event_at` may be in the future for an announced event. Availability, not event
date, determines whether the information was knowable. `public_information` replay
allows later ingestion of historically available documents. `platform_replay`
requires ingestion by the cutoff as well. Input construction omits ingestion
metadata, so later collection timestamps never reach the model.

These checks cannot detect dishonest metadata or future facts embedded in prose.
Source ingestion must establish provenance; reviewed labels must use only the
contemporaneous evidence. Source hashes detect modification, not truthfulness.
Chronological ordering and explicit label-window purge/embargo checks are
implemented. Legacy v1 sample validation accepts a calendar-day embargo; v2
manifests use platform-computed session timestamps. DATA01's reviewed target plan
also records each of the 21 XNYS sessions after the preceding label end before the
later split may begin. Cross-split checks compare each
sample's complete source-content input, rejecting normalized exact matches and,
for inputs with at least 20 tokens, multiset-token Jaccard similarity of 0.90 or
greater. Individual historical sources may legitimately recur in later samples.
This is a deterministic leakage heuristic, not proof that lower-scoring inputs are
independent. The R11 SEC access review is recorded, while its three-listing
convenience universe remains explicitly survivorship-biased and ineligible for
performance claims. Outcome labels belong in a separately permissioned dataset, never the sample schema or an
LLM/SFT trainer mount. A separate numeric supervised fit job may read its permitted
training labels; prediction jobs never receive labels. Synthetic examples are not
financial training data.

## Persistence mapping

Before creating SQL, inspect the platform's actual migration conventions and reuse
its instrument, document, analysis, and job IDs. Proposed tables are listed in the
implementation plan; this repo intentionally supplies no speculative migrations.

Persist run status transitions (`queued → running → succeeded | failed | cancelled`),
request ID, deployment ID, timestamps, tool events, validated analysis JSONB,
source snapshot references, and error category. Index `(instrument_id, as_of_timestamp)`
and deployment/run references. Registry records are immutable versions. Numeric
fit/predict retries create attempts without changing completed artifacts. Use UTC
timestamptz and explicit monetary units.

## Job boundaries

- Numeric fit (ALPHA02, `alpha-train`): validated feature manifest + hash-pinned label
  artifact + the frozen ALPHA03 parameters → immutable ridge and LightGBM artifacts,
  a wall-clock-free training manifest and frozen challenger pins. Training labels
  are read only here.
- Numeric predict (ALPHA02, `alpha-predict`): frozen challenger + feature-only
  manifest + trusted request → strict alpha-forecast-v1 with complete expected
  coverage; labels are never read.
- Chronos challenger (ALPHA03): isolated pinned CPU runtime and weights → batch
  forecasts, in new modules so the ALPHA02 pinned code stays byte-identical.
- Text evaluation: reviewed platform export → offline accuracy/failure report and
  numeric fixtures; hosted calls and application writes remain platform-owned.

The retired local general-LLM tool evaluator, RAG, QLoRA, adapter-export and
deployment-promotion branch has been removed. Reintroducing it requires a new
architecture decision and measured need. No library or container here loads GPU
dependencies.

## Artifact and prompt ownership

Downloaded pretrained weights (Chronos-2) receive an immutable manifest beside the
artifact: repository/revision, license, file hashes, runtime, code commit and seed.
Do not invent revisions or provenance for synthetic examples.

Dataset manifests keep artifact paths relative and contained; validate them with
`uv run --frozen ai-treader-llm validate-manifest <manifest>`. Git and files hold
reproducibility metadata, while the platform registry owns active deployment state.

The runnable dataset builder's initial system prompt lives in
`python/ai_treader_llm/datasets/samples.py`. Production prompts belong in the Go
platform and each run records their content hashes. Retrieved strings are data, never
instructions; calculations and authorization remain platform-owned.

## Contract v2 (shared with the platform)

v2 is authored here and vendored by the platform (`scripts/llm-contract-sync.sh`
there, `--check` compares). Both repositories validate the same fixtures in
`contracts/fixtures/v2`; each invalid case breaks one rule and names the code both
validators must return. The check order is part of the contract.

- **Envelope** (`analysis-context-v2`): platform-owned `listing_id`, symbol, UTC
  cutoff, `replay_mode`, one `horizon` (label `1m`/`3m`, policy
  `xnys-calendar-months-v1`, calendar version, start/end session and end close),
  typed source metadata (content travels separately, bound by its SHA-256), typed
  `unavailable` inputs, and `context_sha256`.
- **Canonical hash**: SHA-256 of `json.dumps(sort_keys=True, separators=(",", ":"),
  ensure_ascii=False)` UTF-8 bytes of the envelope without `context_sha256`.
  Integers only; the Go encoder reproduces these escapes byte for byte
  (`context-hash-vectors.json` includes the hard cases).
- **Horizons**: the end session is the first XNYS session on or after the decision
  session plus N calendar months, the platform journal's rule. `1m` is never 30
  days. This repository checks order only; the platform checks the sessions
  against its calendar (`horizon_sessions_mismatch`, platform-only).
- **Grounding (structural)**: every claim cites at least one supplied source; a
  cited metric's source is among the claim's citations; each section cites a kind
  that can support it; an abstention has `thesis: null` and
  `insufficient_evidence`; `unavailable` acknowledges exactly the missing inputs.
  Numeric claims are not checked against values and prose is not verified.
- **Outcomes** (`outcome-record-v2`): one record per sample horizon; each measure is
  `available` with a finite value or `unavailable` with a typed reason
  (`pending`, `missing_bars`, ...). Never a zero for an unmeasured label.
- **Datasets**: v2 samples carry their horizon, so label ends are known without
  outcomes and splits are always purged. Session embargoes are stated by the
  platform as `embargoed_starts` timestamps. `validate-manifest
  --evaluation-boundary` refuses any sample whose cutoff or label end is not before
  the platform's embargoed evaluation boundary (a v1 dataset needs outcomes for it).

v1 schemas, examples and validators are unchanged and still read.

## Versioning and validation

Schema versions `1` and `2` are explicit. Breaking contract changes require a new version and
consumer migration. Pin datasets by manifest/content hashes, models by repository
commit and artifact hash, and images by digest. Record prompt and template hashes.

Dataset manifest paths are relative and must resolve within the manifest directory.
The validator hashes raw artifact bytes, checks declared row counts, revalidates
samples and optional outcomes, and compares split summaries and analysis horizons.
Licensing and review status are explicit metadata; schema validity does not prove
that a claimed review occurred.

`uv.lock` is authoritative for CPU dependencies. `requirements.lock.txt` is a
hash-locked export used by the CPU Docker image. Checks run locally with `make check`;
there is no hosted CI. Regenerate together:

```bash
uv lock
uv export --frozen --no-dev --no-emit-project -o requirements.lock.txt
```

The CPU image base is pinned to a resolved multi-platform Python image digest.
Update it deliberately alongside dependency validation.

## Numeric forecasting boundary (ALPHA01 delivered 2026-10-19)

ALPHA01 introduces a separate numeric contract package and runnable Python
validators. ALPHA02 (`python/ai_treader_llm/alpha/`) adds the CPU fit/predict jobs;
platform import is ALPHA04.
Numeric scores do not reuse the prose-analysis schema.

The alpha-forecast-v1 family must bind immutable listing ID, UTC cutoff, exact
calendar-based horizon, feature schema/version, input manifest hash, model artifact,
training/configuration/code/runtime hashes, score meaning and explicit unavailable
state. Pin expected listing/cutoff coverage so failures cannot disappear. Preserve
exact IDs, hashes and financial values; define numeric serialization and test
canonical hash vectors in Python and Go. Unknown fields must fail. A rank is not a
calibrated probability or an order, and missing data is never a zero forecast.

Numeric manifests bind separate feature and label artifacts, source revisions,
identity/universe membership, availability policy (observed versus reconstructed),
corporate-action basis, feature definitions and label entry/end timestamps. The
platform computes deterministic financial transforms/labels; model packages own
learned preprocessing and fitting. Every learned transform is fit inside training
folds. Group each decision date across listings in the same chronological split;
purge actual overlapping label windows and record the session embargo. Only
matured permitted labels may enter training. Held-out labels are evaluation-only.
LLM prompts, SFT targets and prediction job mounts never receive outcome labels.

The public artifact family is:

| Artifact | Purpose |
|---|---|
| `numeric-calendar-v1` | Hash-pinned XNYS session/open/close schedule used to verify next-open entry and calendar-month horizon close |
| `numeric-input-v1` + `numeric-feature-row-v1` | Feature-only prediction input, expected row coverage, universe/action/availability policy and source provenance |
| `alpha-request-v1` | Trusted batch/attempt, deadline, model provenance and score semantics |
| `alpha-forecast-v1` | Complete available or typed-unavailable results bound to the trusted request |
| `numeric-dataset-v1` + `numeric-label-v1` | Separate supervised labels, target definition, split assignment, purge and embargo evidence |

Numeric values are canonical decimal strings. Listing IDs are canonical positive
signed-int64 strings so cross-language JSON cannot round them. Self-hashed JSON
uses sorted UTF-8 keys, compact separators, exact scalar bytes, no floats, no BOM
and no trailing newline; referenced artifacts hash their raw bytes. The shared
fixture suite declares ordered error codes and includes values beyond JavaScript's
safe-integer range, DST, microsecond cutoffs, tampering and coverage failures.

ALPHA02 fixes the job-side choices the protocol leaves open: features enter in
feature-schema order as float64; a row with any unavailable feature or label is
excluded and counted; the target is the label demeaned across each date's usable
rows; standardization uses population deviation (zero → 1); per-date Spearman uses
average ranks and is undefined (excluded, counted) below two rows or for a constant
side; a fold's score is the mean of its defined dates and selection uses the mean
of the fold scores. Scores are `ranking_score`/`unitless` with the label target
attached, written with at most 15 fractional digits. BLAS/OpenMP run on one thread.
`code_sha256` covers the job and contract modules; `runtime_sha256` covers Python,
OS/machine, numpy/scipy/LightGBM versions, `uv.lock` and thread pins.

Batch attempts are platform-created and idempotent. Jobs receive immutable bounded
inputs and emit artifacts; they have no database write or trading credentials.
Platform import verifies scope, hashes, full coverage, schema and freshness before
persisting successes, unavailable results or errors. Failed batches cannot silently
reuse stale scores. Map validated scores to proposals through a separately
versioned Go rule and existing policy/risk checks. Use PostgreSQL and existing job
infrastructure rather than a second store or queue.

TEXT01 attributes bind source passages and availability, model/prompt/schema hashes
and unknown states. Human-reviewed extraction accuracy is separate from financial
ablation performance. Historical extraction can retain pretrained hindsight even
when sources are timestamp-filtered. Neither structural references nor model
quantiles establish semantic truth, calibration or financial benefit.

## Provider-neutral evidence evaluation (current boundary, 2026-10-22)

Hosted product-agent instructions and application persistence belong to the platform,
not this repository or engineering-assistant memory. Each call records role/template/
schema versions, exact input hashes, configured and observed provider/model identity,
source cutoffs and complete attempt outcomes. Existing review JSON and analysis-v2
have different purposes; platform AGENT01/AGENT02 delivered tested versioned adapters
without fabricating local-model artifact hashes for hosted providers.

TEXT01 will validate reviewed attribute captures from platform AGENT04, including exact
listing/cutoff, source passages, unknown states, prompt/model/schema provenance and
all failures. The workflow exists, but no real capture set, human-reviewed target or
TEXT01 export exists yet. Financial feature
calculation and concise per-listing research retrieval remain Go-owned; labels never
enter inference context, including indirectly through later outcomes or summaries.
