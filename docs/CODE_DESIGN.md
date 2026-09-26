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

## Runnable modules

| Module | Public boundary | Responsibility |
|---|---|---|
| `contracts.py` | `Contracts.validate`, `Contracts.analysis` | JSON Schema, trusted request identity, evidence/metric references |
| `datasets/samples.py` | `validate_sample`, `validate_dataset` | Source availability, ingestion cutoff, content hashes, IDs, chronological split order |
| `datasets/samples.py` | `build_messages` | Fixed prompt plus validated sources; never serializes target/outcome fields |
| `evaluation/runner.py` | `evaluate` | Counts every expected sample; missing/invalid responses are failures |
| `inference/client.py` | `smoke` | Health and first completion; not a production orchestration client |
| `cli.py` | CLI entry point | Local jobs, JSON output, stable success/failure exit codes |

The CLI runs from the repo root by default. For another working directory, supply
`--contracts /absolute/path/to/contracts` before the subcommand. Schema resources
resolve locally; remote schema retrieval is not enabled.

Exit codes: `0` completed with no contract failures; `1` evaluation includes failed
predictions; `2` invalid input or operational failure. JSON reports go to stdout;
errors go to stderr. The current evaluator never permits model promotion.

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
Chronological ordering is implemented; horizon-aware purge/embargo, cross-split
near-duplicate checks, survivorship controls, and licensing review remain pending.
Outcome labels belong in a separately permissioned dataset, never this sample
schema or a trainer mount. Synthetic examples are not financial training data.

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

## Versioning and validation

Schema version `1` is explicit. Breaking contract changes require a new version and
consumer migration. Pin datasets by manifest/content hashes, models by repository
commit and artifact hash, and images by digest. Record prompt and template hashes.

`uv.lock` is authoritative for CPU dependencies. `requirements.lock.txt` is a
hash-locked export used by the CPU Docker image and CI. Regenerate together:

```bash
uv lock
uv export --frozen --no-dev --no-emit-project -o requirements.lock.txt
```

The CPU image base is pinned to a resolved multi-platform Python image digest.
Update it deliberately alongside dependency validation. GPU runtime selection is locked by
the bootstrap script; actual CUDA compatibility is accepted only after server tests.
