# AI-Treader architecture

Architecture and delivery snapshot — **2026-10-07**.

We are building a local, personal research and trading system that turns traceable
evidence into recommendations, measures those recommendations in paper trading,
and can eventually operate within separately approved live limits.

**Today:** the platform foundation, hosted strategy-review bridge and local Qwen endpoint work. Hosted Codex/Claude agents are the preferred research direction; listing analysis, strategy proposals and concise research memory still require implementation. The L03 replay
engine is built, but its evaluation is unfinished. Numeric prediction and the new
research track are approved plans, not implemented capabilities. No broker is
connected and no live trading is authorized.

This document is a visual explanation, not another backlog. Current task state and
order remain in the [LLM backlog](tasks/BACKLOG.csv) and
[platform backlog](../ai-treader-platform/tasks/BACKLOG.csv). Task IDs below are
qualified by repository because both repositories use ALPHA IDs.

## 1. What does what

The **platform controls the system**, the **models supply evidence or predictions**,
and the **operator approves experiments and authority**.

| Component | Responsibility | Runs where | Delivery state |
|---|---|---|---|
| React cockpit | Show recommendations, evidence, operations and outcomes | Platform UI in the browser | Existing surfaces delivered; new numeric views not implemented |
| Go backend | Ingest data, select information available at a cutoff, calculate financial features, orchestrate jobs, validate results and enforce policy/risk | Existing platform deployment | Foundation delivered; numeric extensions planned |
| PostgreSQL | Authoritative identities, source revisions, datasets, runs, decisions, paper ledger and outcomes | Existing platform database | Delivered; new numeric records planned |
| Hosted agent bridge | Existing bounded strategy review; planned listing analysis, declarative proposals and text attributes | Platform CLI adapters; inference at the provider | Review bridge delivered; new contracts and provider qualification planned |
| Qwen3-8B / llama.cpp | Retained local L03 analysis and optional measured comparator | Pinned Docker inference on Ubuntu / RTX 3080 | Endpoint and Go integration delivered |
| Linear model / LightGBM | Learn numeric relationships and produce relative-return scores | Planned isolated CPU batch jobs owned by LLM repository | Not started |
| Chronos-2 | Challenge the numeric baseline with pretrained time-series forecasts | Planned local batch job; CPU/GPU placement measured before use | Not started |
| Reviewed text attributes | Extract cited guidance, liquidity and event attributes; evaluate accuracy and numeric usefulness | Platform hosted captures; LLM repository offline evaluation | Not started |
| Contract validators | Reject malformed, out-of-scope or mismatched results | Python in LLM repository; Go in platform | Analysis v2 delivered; numeric contract planned |
| Paper engine and journal | Simulate orders, enforce risk, record fills/costs/holdings and mature outcomes | Go and PostgreSQL | Delivered; comparative evaluation unfinished |
| Host dashboard | Report sanitized hardware and endpoint health | Restricted native service on Ubuntu | Delivered; future-job telemetry remains unavailable |
| Broker adapter | Reconcile accounts and eventually submit authorized orders | Future Go integration | Not started; separate security and approval gates |

## 2. Whole-system view

**Legend:** green = delivered foundation; amber = built but qualification/evaluation
unfinished; blue = approved planned extension; gray = future conditional capability.
Each node also states its status so color is not required. Arrows show information
flow or authority, not proof that every connected path is implemented.

```mermaid
flowchart TB
    Operator["Operator<br/>Approves protocols and authority"]
    Sources["Market data and SEC evidence<br/>Ingestion foundation delivered"]

    subgraph Platform["ai-treader-platform — Go / React / PostgreSQL"]
        PIT["Identity, revisions and cutoff filtering<br/>Delivered foundation"]
        DB[("PostgreSQL<br/>Authoritative records — delivered")]
        Bridge["Hosted agent bridge<br/>Review delivered; research extensions planned"]
        Text["Reviewed text attributes<br/>Planned platform capture"]
        Worker["Go orchestration and validation<br/>LLM delivered; numeric import planned"]
        Rules["Versioned proposal mapping and risk<br/>Existing paper rules; new mappings planned"]
        Paper["Paper execution and outcome journal<br/>Delivered"]
        UI["React cockpit<br/>Existing evidence and operations views"]
    end

    subgraph Models["ai-treader-llm — model runtime and research jobs"]
        Qwen["Qwen3-8B via llama.cpp<br/>Delivered private endpoint"]
        Trees["Linear / LightGBM<br/>Planned CPU batch prediction"]
        Chronos["Chronos-2<br/>Planned independent challenger"]
    end

    Hosted["Codex / Claude provider inference<br/>Existing review adapters; qualification pending"]
    Broker["Broker adapter<br/>Future; disconnected today"]
    Sources --> PIT --> DB
    DB --> Worker
    Worker -->|Bounded as-of evidence| Qwen
    Qwen -->|Strict advisory response| Worker
    Worker -.->|Feature snapshot| Trees
    Worker -.->|Feature snapshot| Chronos
    Trees -.->|Forecast artifact| Worker
    Chronos -.->|Forecast artifact| Worker
    Worker -->|Existing strategy-review scope| Bridge
    Bridge -->|Bounded outbound evidence| Hosted
    Hosted -->|Advisory structured output| Bridge
    Bridge --> Worker
    Bridge -.-> Text -.-> Worker
    Worker -->|Validated result; eligible workflow only| Rules
    Operator -->|Approved policy| Rules
    Rules --> Paper --> DB
    DB --> UI
    Rules -.->|Future account and live gates| Broker

    classDef delivered fill:#dcfce7,stroke:#15803d,color:#14532d;
    classDef partial fill:#fef3c7,stroke:#b45309,color:#78350f;
    classDef planned fill:#dbeafe,stroke:#2563eb,color:#1e3a8a;
    classDef future fill:#f3f4f6,stroke:#6b7280,color:#111827;
    class Sources,PIT,DB,Qwen,Paper,UI delivered;
    class Worker,Rules,Bridge,Hosted partial;
    class Trees,Chronos,Text planned;
    class Broker future;
```

Models have no broker credentials or database write authority. Go computes financial
values, checks limits and owns execution. The standalone local-analysis command is
preview-only; paper proposals are produced by the separately controlled replay path.
Combining numeric scores and LLM evidence is a future experiment, not an automatic
rule in this diagram.

## 3. Retained local LLM / L03 path

```mermaid
flowchart TD
    Request["Go fixes listing, UTC cutoff and calendar horizon"]
    Evidence["Bounded evidence bundle<br/>Caller supplied for standalone analysis;<br/>Go-built inside L03 replay"]
    Call["Private Qwen endpoint<br/>Pinned model, runtime, prompt and decoding"]
    Check{"Strict v2 validation passes?"}
    Repair["At most one repair<br/>Same evidence and original deadline"]
    Valid["Persist validated analysis or abstention"]
    Failed["Persist failure<br/>No usable analysis signal"]
    Attempts["Persist every attempt and provenance"]
    Preview["Standalone command<br/>Preview-only mapping; no order"]
    Replay["L03 replay path<br/>Frozen mapping to paper proposal"]
    Risk["Existing Go policy and risk checks"]
    Paper["Local paper account and journal"]

    Request --> Evidence --> Call --> Check
    Call --> Attempts
    Check -->|Yes| Valid
    Check -->|No; repair remains| Repair --> Call
    Check -->|No; exhausted or terminal error| Failed
    Valid --> Preview
    Valid -->|Controlled replay only| Replay --> Risk --> Paper
```

Schema and citation checks establish structural validity, not the truth of prose
or numerical claims. The live endpoint smoke and endpoint benchmark do not prove
predictive value. L03 Stage 1 is incomplete: revision 4 encountered reply truncation;
revision 5 proposes 8192 context / 2048 output tokens and still needs separate approval.
The newer host configuration needs CTX01 qualification beyond the earlier benchmark.

The existing hosted strategy-review bridge is a separate advisory workflow. It does
not yet implement general listing analysis or autonomous strategy creation. AGENT01–07
add those bounded research capabilities without changing this frozen L03 path.

## 4. Planned numeric learning and prediction

Training and prediction use separate inputs. Numeric supervised fitting needs
historical training labels; prediction jobs and LLM prompts must never receive them.

```mermaid
flowchart TD
    Historical["Go: pinned historical evidence and membership"]
    Features["Go: versioned as-of feature snapshots"]
    Labels["Go: separate matured outcome labels<br/>Executable entry and exact horizon end"]
    Split["Chronological folds grouped by decision date<br/>Purge overlapping labels; record embargo"]
    Fit["LLM repo: CPU linear / LightGBM fit<br/>Training folds only; bounded trials"]
    Artifact["Immutable model and preprocessing artifact<br/>Dataset, code, runtime, config and seed hashes"]
    NewFeatures["Go: prediction-time feature snapshot<br/>No outcome labels"]
    Predict["LLM repo: isolated batch prediction"]
    Import["Go: validate alpha-forecast-v1<br/>Identity, hashes, freshness and complete coverage"]
    Evaluate["Go: paired replay and forward observation<br/>Costs, risk, failures and no-trades retained"]
    Heldout["Held-out labels<br/>Evaluation access only"]
    Decision{"Operator reviews matured evidence"}
    Keep["Failure or inconclusive<br/>Keep incumbent; retain evidence"]
    Candidate["Approved candidate version<br/>Separate activation checks; no trade authority"]

    Historical --> Features --> Split
    Historical --> Labels --> Split
    Split -->|Permitted training partition| Fit --> Artifact
    Split -->|Protected evaluation partition| Heldout
    Artifact --> Predict
    NewFeatures --> Predict --> Import --> Evaluate
    Heldout --> Evaluate --> Decision
    Decision --> Keep
    Decision --> Candidate
```

All components in this new numeric path require implementation, although they reuse
existing platform infrastructure. Start with daily features, a **one-calendar-month
target and weekly decisions**; evaluate 3m separately. Product scope remains 1–6 month
holdings. A forecast horizon does not itself force liquidation.

After baseline replay readiness, evaluate Chronos-2 and reviewed text attributes as
separate challengers. Compare numeric-only against numeric-plus-text on the same
folds and mechanics. A ranking score is not a probability; model quantiles need
calibration checks. A combined model is considered only after incremental evidence.

## 5. Where we stand

| Capability | Current position | Remaining work / owner |
|---|---|---|
| Data and paper foundation | Identity, revisions, PIT machinery, policy/risk, ledger and journal delivered | Real training coverage and historical universe evidence still needed |
| Hosted agents | Existing restricted strategy-review bridge | Platform AGENT01–04: versioned instructions, qualification, proposals and text capture |
| Concise research history | Existing run/backtest/review/journal records | Platform AGENT05: linked immutable summaries and as-of retrieval; AGENT06–07 evaluation |
| Local LLM | Endpoint, Go client, strict analysis and attempt persistence delivered | LLM HARD01, CTX01 and TOOLS01 qualification |
| Reviewed datasets | Integrity tooling exists; real reviewed dataset not complete | LLM DATA01; platform ALPHA02 numeric export |
| Existing L03 experiment | Replay/evaluator built; Stage 1 unfinished | Platform L03d revision-5 approval and run; L03e forward observation |
| Numeric contracts and models | Plan approved; no implementation | LLM ALPHA01–ALPHA02; platform ALPHA01–ALPHA05 |
| Chronos-2 and text attributes | Planned | LLM ALPHA03 / TEXT01; platform ALPHA06 / ALPHA07 |
| Combined challenger | Conditional decision only | Platform ALPHA08; implement only through subsequent bounded tasks |
| Numeric forward evidence | Not started | Platform ALPHA09; actual elapsed time and matured outcomes required |
| RAG / QLoRA / GGUF export / promotion | Not implemented; retained later in backlog | LLM RAG01 / TRAIN01 / EXPORT01 / PROMOTE01 |
| Broker and bounded live operation | No connection or authorization | Platform B00s–B03; independent account, security and operator gates |

The existing 13-listing L03 universe and survivorship-biased pilot/sizing universe
can test plumbing; they do not establish broad stock-selection performance.
Historical reconstruction assumptions and pretrained hindsight remain explicit.
L03's power analysis indicates that its forward result is expected to be inconclusive;
it cannot establish a general profitability claim.

The three evaluation tracks remain separate:

```mermaid
flowchart LR
    subgraph HostedTrack["Hosted research — preferred agent direction"]
        H1["Versioned roles, contracts and adapter qualification"]
        H2["Bounded proposals, backtests and as-of memory"]
        H3["Curated evaluation and separate protocol freeze"]
        H4["Matured hosted forward paper evidence"]
        H1 --> H2 --> H3 --> H4
    end
    subgraph Existing["Existing L03 — frozen question"]
        L1["Revision 4 frozen<br/>Revision 5 approval pending"]
        L2["L03d: finish replay and Stage 1 gates"]
        L3["L03e: 52 decision weeks<br/>plus exact 3-month follow-up"]
        L1 --> L2 --> L3
    end
    subgraph Numeric["New numeric research — approved scope"]
        A1["Shared contract and PIT export"]
        A2["Separate protocol freeze"]
        A3["CPU baselines and batch integration"]
        A4["Baseline replay / shadow readiness"]
        A5["Chronos-2 and text comparisons"]
        A6["Matured numeric forward evidence"]
        A1 --> A2 --> A3 --> A4
        A4 --> A5
        A4 --> A6
        A5 -.->|Separately frozen eligible candidates| A6
    end
```

Hosted and numeric implementation do not depend on completing L03e. It must preserve L03's protected
evaluation windows. These arrows summarize milestones; exact dependencies and
serial work order are owned by the two backlogs, not this diagram.

## 6. Deployment and resource boundaries

| Location | Existing | Planned |
|---|---|---|
| Mac development environment | Repository work and CPU checks; no GPU dependency environment | Isolated CPU numeric development and validation |
| Platform deployment | Go backend, React cockpit, PostgreSQL and worker infrastructure | Batch orchestration/import and numeric evaluation; same infrastructure |
| Ubuntu AI host | RTX 3080, pinned Qwen Docker inference, private access and read-only dashboard | Measured on-demand model jobs with exclusive GPU scheduling |
| Hosted provider | Existing Codex/Claude review adapters; inference outside the local machine | Qualified research calls with explicitly scoped outbound evidence |
| Artifact storage | Versioned model files and manifests; generated artifacts outside Git | Hashed numeric datasets, trained models and evaluation reports |

Local operation does not make hosted inference local: scoped evidence is sent to the
selected provider. Keep credentials and unnecessary private records out of envelopes.
Use the existing machine for CPU baselines and measure Chronos-2 resource needs before
a hardware purchase; this direction does not require a DGX or a dedicated Qwen server.

No additional always-on model gateway, queue, vector service or experiment database
is planned. CPU baselines come first. Hardware qualification is unfinished; 64 GiB
RAM is a design target, not a verified installed capacity. Do not assume Qwen and a
second GPU model can run concurrently. Current Linux storage is restricted to the
permitted disk; Windows NVMe devices remain out of scope.

## 7. Planned call instructions, versions and reusable history

Use reusable versioned role instructions, not a newly invented prompt for each call.
Go builds the variable envelope with exact listing identity, UTC cutoff, allowed
source references, strategy version, engine capabilities, trial budget and schema.
Persist the rendered prompt hash and configured/observed provider identity. Preserve
unknown values and refusals. Hosted model weights may not be reproducible even when
the captured request is exact.

```mermaid
flowchart TD
    Role["Versioned role instructions and strict task schema"]
    Scope["Go envelope<br/>Listing, cutoff, evidence, permissions and budgets"]
    History["Bounded as-of context<br/>Only records available at cutoff; no held-out labels"]
    Agent["Hosted agent<br/>Advisory output or abstention"]
    Validate{"Go validates supported declarative proposal"}
    Version["Immutable strategy version<br/>Parent, rules, parameters and rationale"]
    Run["Go backtest request and run<br/>Pinned data, engine, costs, folds and seed"]
    Records[("Existing PostgreSQL records<br/>All attempts, failures and exact artifact references")]
    Summary["Immutable concise summary revision<br/>Listing ID, strategy/run refs, metrics, unknowns and availability"]
    Role --> Scope
    History --> Scope --> Agent --> Validate
    Validate -->|Accepted| Version --> Run --> Records
    Validate -->|Rejected or unavailable| Records
    Agent -->|Attempt and provenance| Records
    Records --> Summary -->|As-of retrieval only| History
```

An agent proposes; Go allocates strategy versions, validates backtest specifications,
runs supported engines and writes records. A retry is not a new independent trial;
intentional repeated trials remain visible against the campaign budget. Changed
rules, parameters, features or compiler semantics require a new strategy version.

Concise history is keyed by stable listing identity, with ticker history preserved;
cross-sectional strategies also retain their universe snapshot. Summaries link exact
runs, units, windows and evidence rather than replacing underlying records. A summary
written later cannot enter an earlier simulated decision merely because it describes
old data. Outcome maturity and protected evaluation partitions remain enforced.

See the [platform implementation plan](../ai-treader-platform/tasks/PLAN.md#hosted-agents-call-instructions-and-research-records-approved-2026-10-07)
for the canonical planned envelopes and record fields. No new database or vector
service is required by this design. Next local tasks: **LLM ALPHA01** (shared numeric
contract) and **platform AGENT01** (versioned agent instructions/contracts).

## 8. What we want to accomplish

```mermaid
flowchart TD
    Evidence["Traceable, point-in-time evidence"]
    Recommendation["Useful recommendation<br/>Ranking, supporting facts, risks and uncertainty"]
    Paper["Reproducible paper record<br/>Every decision, refusal, fill, cost and outcome"]
    Review{"Enough matured evidence<br/>under a frozen protocol?"}
    Retain["Keep incumbent or reject candidate<br/>Record what was learned"]
    Approve["Operator-approved candidate<br/>Measured behavior and rollback"]
    Gates["Separate security, account and live-policy gates<br/>B00s through B03"]
    Live["Conditional end goal<br/>Bounded local trading under Go enforcement"]

    Evidence --> Recommendation --> Paper --> Review
    Review -->|No or inconclusive| Retain
    Review -->|Yes; operator approves| Approve --> Gates --> Live
```

Success means recommendations we can inspect and reproduce, a measured paper record,
and a system that keeps the incumbent when a challenger fails. The eventual trading
module may operate under a bounded standing policy, but only the Go backend can
enforce that policy and authorize execution. The proposed approximately USD 1,000
live allocation is a future separately approved scope, not funded or enabled here.

The learning loop creates reviewed dataset, model and policy versions. It does not
let a model rewrite live limits, increase budgets or promote itself. Local personal
use is recorded; source/license metadata and unknown permissions remain explicit.

## References and maintenance

- [LLM status](STATUS.md) and [LLM backlog](tasks/BACKLOG.csv).
- [Platform status](../ai-treader-platform/STATUS.md),
  [platform backlog](../ai-treader-platform/tasks/BACKLOG.csv) and
  [approved product plan](../ai-treader-platform/tasks/PLAN.md).
- [LLM implementation plan](docs/IMPLEMENTATION_PLAN.md),
  [contract and code boundaries](docs/CODE_DESIGN.md), and [runbook](docs/RUNBOOK.md).

Update this snapshot when architecture or delivered capabilities change. Backlog
acceptance evidence remains authoritative; a diagram is not implementation proof.
