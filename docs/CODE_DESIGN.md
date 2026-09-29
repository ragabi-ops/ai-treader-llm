# Code design

## Ownership and dependency direction

```text
Existing Go platform
  application analysis workflow
    → provider-neutral LLM client → llama.cpp / future provider
    → allowlisted deterministic tools → existing market services
    → timestamp-filtered retrieval → existing Postgres
    → validated analysis persistence → signal / portfolio / risk pipeline

This repository
  contracts/ → Python contract validator
                  ↓
             dataset integrity → input builder
                  ↓
             offline evaluation → versioned report
  deployment scripts → pinned model/runtime → inference container
  future trainer → PEFT adapter → GGUF export → evaluation → promotion
```

Dependencies flow toward contracts; no module imports trading execution code.
There is no standalone gateway, queue, vector database, or model registry service.

Runtime placement is an explicit deployment choice, not an API boundary. The
accepted interim deployment keeps digest-pinned llama.cpp inference in Docker,
future GPU training/evaluation jobs in on-demand containers, and the read-only host
dashboard in a restricted native systemd process. Reassess native inference at the
dedicated-host migration, or earlier only for a demonstrated container-specific
reliability or GPU compatibility blocker. A native candidate must pass the same
provider contracts and be compared against the container on latency, throughput,
VRAM, startup/recovery, and reproducible rollback.

## Runnable modules

| Module | Public boundary | Responsibility |
|---|---|---|
| `contracts.py` | `Contracts.validate`, `Contracts.analysis`, `Contracts.tool_arguments` | JSON Schema, trusted request identity, evidence/metric references, strict tool arguments |
| `contracts_v2.py` | `validate_context`, `validate_analysis`, `context_hash` | Contract v2: trusted envelope, canonical hash, shared-code grounding checks |
| `contract_fixtures.py` | `build` / `python -m ai_treader_llm.contract_fixtures` | Generates the shared v2 fixtures and v2 examples; tests fail on drift |
| `datasets/samples.py` | `validate_sample`, `validate_dataset` | Source availability, ingestion cutoff, content hashes, IDs, chronological split order |
| `datasets/samples.py` | `build_messages` | Fixed prompt plus validated sources; never serializes target/outcome fields |
| `datasets/duplicates.py` | `validate_cross_split_duplicates` | Deterministic cross-split exact/near-duplicate sample-input checks |
| `datasets/outcomes.py` | `validate_outcomes` | Separate labels, exact sample coverage, finite values, split purge/embargo |
| `datasets/manifests.py` | `validate_manifest` | Artifact hashes/counts, contained paths, split/policy/provenance consistency |
| `evaluation/runner.py` | `evaluate` | Counts every expected sample; missing/invalid responses are failures |
| `evaluation/tools.py` | `evaluate_tool_calls` | Scores allowlists, required/unnecessary calls, strict arguments, and trusted symbol/time boundaries |
| `inference/client.py` | `smoke` | Health and first completion; not a production orchestration client |
| `monitoring/collector.py` | `StatusCollector.snapshot` | Read-only host, GPU, Docker, llama.cpp, deployment, and allowlisted pipeline/training telemetry |
| `monitoring/server.py` | `python -m ai_treader_llm.monitoring.server` | Fixed-route dashboard and same-origin status API; no mutation, file, log, prompt, or response endpoints |
| `cli.py` | CLI entry point | Local jobs, JSON output, stable success/failure exit codes |

The CLI runs from the repo root by default. For another working directory, supply
`--contracts /absolute/path/to/contracts` before the subcommand. Schema resources
resolve locally; remote schema retrieval is not enabled.

Exit codes: `0` completed with no contract failures; `1` evaluation includes failed
predictions; `2` invalid input or operational failure. JSON reports go to stdout;
errors go to stderr. Neither evaluator permits model promotion.

## Offline tool-call evaluation

Tool-call fixtures contain model-visible messages plus a separately named trusted
scope, per-case allowlist, and expected tool names. The evaluator never adds
`trusted_scope` or `expected_tool_names` to the messages. Fixture allowlists must
resolve to schemas in `contracts/tools/`, and expected names must be a subset of the
allowlist. Saved predictions use a strict envelope; each proposed argument object is
validated against the named tool's strict schema.

A case passes only when all required calls are present and no unauthorized,
incorrect, unnecessary, schema-invalid, wrong-symbol, or out-of-bound time call is
present. Missing and malformed predictions remain in the denominator. Reports expose
stable per-category counts and individual failure records. These checks do not
execute tools, assess returned data, or prove prompt/template parsing, grounding, or
financial quality. The Go dispatcher must independently repeat authorization and
trusted-boundary enforcement at runtime.

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
implemented. Embargo is measured in calendar days; real label generation must use
the platform's point-in-time trading calendar. Cross-split checks compare each
sample's complete source-content input, rejecting normalized exact matches and,
for inputs with at least 20 tokens, multiset-token Jaccard similarity of 0.90 or
greater. Individual historical sources may legitimately recur in later samples.
This is a deterministic leakage heuristic, not proof that lower-scoring inputs are
independent. Survivorship controls and licensing review remain pending. Outcome
labels belong in a separately permissioned dataset, never the sample schema or a
trainer mount. Synthetic examples are not financial training data.

## Go integration contract (implement in the platform repository)

Suggested interfaces, not compiled/generated backend code:

```go
type AnalysisRequest struct {
    InstrumentID string
    Symbol       string
    AsOf         time.Time
    Horizon      string
}

type LLMProvider interface {
    Complete(ctx context.Context, request CompletionRequest) (CompletionResponse, error)
}

type ToolDispatcher interface {
    Execute(ctx context.Context, scope TrustedScope, call ToolCall) (ToolResult, error)
}
```

`TrustedScope` is created by Go and carries instrument identity, as-of timestamp,
tenant/portfolio permissions, and replay mode. It is never deserialized from model
arguments. Completion types encapsulate OpenAI-compatible messages/tools without
exposing GPU or model-file details. `ToolResult` includes source IDs, availability,
revision, units/currency, typed data, and an explicit error state.

Workflow:

1. Validate request, resolve immutable deployment, and create run ID.
2. Build system/user messages and select allowlisted tools.
3. Fit history, tool definitions/results, and reserved output within context budget.
4. Call provider with deadline/cancellation. Start with one in-flight request;
   bound queued requests and return a retriable busy error when full.
5. Validate proposed tool arguments against `contracts/tools`. Enforce symbol,
   `start <= end <= as_of`, authorization, and output limits in Go separately.
6. Execute tools with timeouts. Preserve tool call IDs; return structured failures.
7. Stop after six rounds. When gathering is complete, make a final schema-constrained
   call without tools so tool selection and final JSON constraints do not conflict.
8. Parse strictly, resolve evidence references, and check trusted request fields.
   Allow one repair. Persist a failure if still invalid; emit no analysis signal.
9. Assign server-generated timestamp/provenance and persist the immutable run.

Tool schemas intentionally omit `as_of_timestamp`: the model cannot choose its
information boundary. JSON Schema handles structure only; business/time rules
belong to Go. Treat every retrieved string as untrusted data. No executable tools.

Provider contract fixtures must cover JSON Schema support, template/parser tool
calls, error responses, timeout/cancellation, context overflow, and model identity.
OpenAI-compatible endpoints do not imply identical capabilities.

## Persistence mapping

Before creating SQL, inspect the platform's actual migration conventions and reuse
its instrument, document, analysis, and job IDs. Proposed tables are listed in the
implementation plan; this repo intentionally supplies no speculative migrations.

Persist run status transitions (`queued → running → succeeded | failed | cancelled`),
request ID, deployment ID, timestamps, tool events, validated analysis JSONB,
source snapshot references, and error category. Index `(instrument_id, as_of_timestamp)`
and deployment/run references. Registry records are immutable versions; a separate
active deployment pointer changes transactionally. Training retries create attempts
without changing completed artifacts. Use UTC timestamptz and explicit monetary units.

## Future job boundaries

- Retrieval: versioned document → section chunks → CPU embeddings → existing
  Postgres; filter availability before selection and recheck returned chunks.
- Training: validated dataset manifest + exact base + locked configuration → adapter.
  A shared exclusive GPU lock is mandatory; stop inference first. No outcome mount.
- Export: adapter + original base → merged safetensors → GGUF → quantized candidate.
- Promotion: complete evaluation gates → registry transaction → readiness check;
  rollback restores the prior artifact/configuration bundle.

Reserved packages deliberately have no fake successful training/RAG implementation.
No library or container here loads GPU training dependencies on the Mac.

## Artifact and prompt ownership

Downloaded models receive an immutable manifest beside the artifact. A deployment
records the base repository/revision, tokenizer/template revision, GGUF and adapter
hashes, quantization, runtime digest, context/decoding settings, prompt/schema hashes,
dataset/training/evaluation hashes, code commit, seed, creation time and lifecycle state.
Do not invent revisions or provenance for synthetic examples.

Dataset manifests keep artifact paths relative and contained; validate them with
`uv run --frozen ai-treader-llm validate-manifest <manifest>`. Git and files hold
reproducibility metadata, while the platform registry owns active deployment state.

The runnable dataset builder's initial system prompt lives in
`python/ai_treader_llm/datasets/samples.py`. Production prompts belong in the Go
platform and each run records their content hashes. Retrieved strings are data, never
instructions; calculations and authorization remain platform-owned.

## Contract v2 (L03a, shared with the platform)

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
hash-locked export used by the CPU Docker image and CI. Regenerate together:

```bash
uv lock
uv export --frozen --no-dev --no-emit-project -o requirements.lock.txt
```

The CPU image base is pinned to a resolved multi-platform Python image digest.
Update it deliberately alongside dependency validation. GPU runtime selection is locked by
the bootstrap script; actual CUDA compatibility is accepted only after server tests.
