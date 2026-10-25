# AI-Treader local LLM implementation plan

Accepted architecture reference, 2026-09-26; supervised research extension approved
2026-10-06; hosted-agent priority revision approved 2026-10-07; obsolete local
general-LLM expansion removed 2026-10-22. This document describes implementation
shape, not current task state or order. See [root STATUS](../STATUS.md) and
[the backlog](../tasks/BACKLOG.csv) for delivery state, and [CODE_DESIGN.md](CODE_DESIGN.md)
for module boundaries. Hardware compatibility references were checked during planning;
every deployment still requires validation on its target machine.

## 1. Recommended Final Architecture

Current direction (2026-10-22): the platform's Codex/Claude bridge owns hosted
research and analysis. This repository prioritizes numeric contracts, CPU
linear/LightGBM, Chronos-2 and offline text-attribute evaluation. Qwen is retained
only for the existing L03 experiment. Standalone local-model tool qualification,
RAG, QLoRA, adapter export and local-model promotion are no longer planned work.
No DGX or larger GPU purchase is required by the approved plan.

**First, prepare and verify the Windows machine, then install Ubuntu Server.** Upgrade to 64 GB RAM if practical; keep the existing GPU and disks. On the current interim dual-boot host, Linux may use only `/dev/sda`; both NVMe devices are reserved for Windows and must not be mounted, formatted, repartitioned, or used for AI-Treader data. A future dedicated host may adopt a different disk layout only through a separate operator decision.

| Component | Decision |
|---|---|
| OS | Ubuntu Server 24.04 LTS, current 24.04.5 server installation image |
| Deployment | Docker Engine + Compose |
| Inference | llama.cpp, CUDA container |
| Initial model | Qwen3-8B, GGUF Q4_K_M |
| Initial capacity | One request at a time; 4,096-token benchmark baseline; 8,192/2,048 context/output candidate needs CTX01 qualification and separate L03 revision approval |
| Backend | Existing Go backend with a small LLM client/orchestrator |
| Numeric jobs | Isolated locked CPU environment for regularized linear and LightGBM fit/predict; separately pinned Chronos runtime |
| Persistence | Existing Postgres + versioned artifacts on disk |
| Research context | Platform-owned bounded as-of PostgreSQL summaries; no vector service |

Deployment decision, accepted 2026-09-29: keep inference in the pinned Docker
container on the interim host, run the read-only operations dashboard as a
restricted native systemd service, and run future numeric/evaluation containers
only on demand. Linux containers use the host kernel and direct NVIDIA device
access; the image digest keeps llama.cpp and CUDA userspace reproducible while the
host driver remains independently managed.

Reassess native llama.cpp when the future dedicated host is commissioned. Reopen
the decision earlier only for a repeated container-specific reliability problem or
a Docker/NVIDIA compatibility blocker. Compare the same model hash, context, request
fixtures, and concurrency while measuring p50/p95 latency, generation throughput,
VRAM, cold start, restart/recovery, and rollback. Adopt native serving only when the
measured operational or performance benefit justifies pinning and recording the
native binary hash, build flags, CUDA libraries, and service configuration. Preserve
the OpenAI-compatible HTTP boundary so either runtime remains replaceable.

```text
Mac ── SSH / Git ───────────────────────► Ubuntu AI server
 │                                          │
Go AI-Treader backend                       ├─ llama.cpp inference (existing L03)
 ├─ LLM client ── private HTTP ─────────────►│
 ├─ Tool dispatcher                         ├─ CPU numeric fit/predict jobs
 │   ├─ Structured market-data services     └─ Optional measured Chronos job
 │   └─ Document retrieval
 └─ Existing Postgres + analysis records

Data → LLM analysis → Signal engine → Portfolio logic → Risk engine → Execution
```

The LLM has no trade-execution tool or credentials. Hermes is excluded. The existing backend remains Go. At planning time this repository contained only a README; integration types and database migrations must be mapped against the actual platform before implementation.

## 2. Phase 0 — Hardware Preparation

Perform these checks before erasing Windows, in order:

1. Back up retained files and recovery information. Record both SSD serial numbers so the installer cannot confuse them.
2. Verify GPU identity and VRAM:
   ```powershell
   nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv
   ```
   Confirm the ASUS board model physically or using GPU-Z. Plan around 10 GB unless verified otherwise.
3. Record motherboard revision and BIOS version. Use the matching Gigabyte revision's support page. Update BIOS only for a relevant stability/security fix or memory-support requirement.
4. Inspect RAM module count, capacity, speed, occupied slots, and compatible kits. Prefer a matched 2 × 32 GB DDR4 kit if replacing existing memory. Avoid mixing kits unnecessarily.
5. Record the two NVMe identities as Windows-owned dual-boot devices and leave them untouched. Do not mount them or run repair, formatting, partitioning, filesystem, model-storage, or training-storage operations against them. Their Windows-side health and backup remain an operator responsibility outside this deployment.
6. Inspect cooling and power: dust, fans, GPU temperatures under sustained load, throttling, PSU model/capacity, and GPU power connectors. Replace the PSU only if inadequate for the exact ASUS card or demonstrably unstable.
7. Verify wired Ethernet. Use the existing interface; no networking upgrade is required.
8. Install the RAM upgrade and run a memory test, then repeat a sustained CPU/GPU stability test.

The existing 32 GB is the accepted starting point for inference and CPU baselines;
64 GB remains an optional capacity improvement, not a prerequisite. No adapter merge
or high-end GPU training workload is planned. The board revision matters for firmware
and memory compatibility. [Gigabyte specifications](https://www.gigabyte.com/Motherboard/B550-AORUS-ELITE-AX-V2-rev-10/sp)

## 3. Phase 1 — Ubuntu Installation

Install Ubuntu Server 24.04 LTS, amd64, without a desktop. The official download listing provided the 24.04.5 server image when checked. Verify its published checksum before writing the USB installer. [Ubuntu downloads](https://releases.ubuntu.com/24.04/)

Ubuntu 26.04 LTS is also supported by Docker and NVIDIA Container Toolkit. Choose 24.04 for its established deployment ecosystem and support through 2029; the older hardware gains little from moving immediately to the newer LTS. [Ubuntu releases](https://ubuntu.com/project/docs/release-team/list-of-releases/), [Docker support](https://docs.docker.com/engine/install/ubuntu/), [NVIDIA support](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/supported-platforms.html)

- Over Windows: simpler headless services, filesystem permissions, GPU containers, and automation.
- Over WSL2: avoids maintaining two operating systems and their networking/storage boundaries.
- Over another Linux distribution: fewer deviations from upstream AI installation instructions.
- Server over Desktop: SSH provides everything needed; a graphical desktop adds no useful capability here.

Use UEFI installation and a normal sudo account named `ai-treader-llm`. Install OpenSSH during setup. Keep a monitor attached until networking and the NVIDIA driver work.

The current interim dual-boot layout is intentionally limited to the external
`/dev/sda` disk. Device names are identification evidence only; persistent mounts
must use filesystem UUIDs. The NVMe disks are not Linux capacity.

| Current partition | Filesystem/layout | Contents |
|---|---|---|
| `/dev/sda2` | EFI system partition mounted at `/boot/efi` | Linux boot files |
| `/dev/sda3` | ext4 `/` | OS, Docker, `/srv/ai-treader`, service state |
| `/dev/sda1` | ext4 `/data`, mounted by UUID | Models, datasets and numeric evaluation artifacts |
| `/dev/nvme0n1`, `/dev/nvme1n1` | Windows-owned; out of scope | Never mount, format, repartition, or use from this deployment |

```text
/srv/ai-treader/          Git checkout, Compose configuration
/data/models/            Immutable inference and original model files
/data/datasets/          Versioned snapshots and manifests
/data/checkpoints/       Resumable numeric fit checkpoints
/data/cache/             Disposable Hugging Face / download caches
/data/evaluations/       Reports and evaluation outputs
/data/training/          Numeric fit logs and immutable model artifacts
```

Use the existing plain ext4 filesystems on `/dev/sda`; skip LVM, ZFS, and RAID.
Keep approximately 15–20% disk space free. Enable periodic TRIM when supported by
the external SSD. Back up irreplaceable datasets, numeric model artifacts, metadata, and database
backups off this machine; downloadable model caches need not be backed up. Make
service startup require the `/dev/sda1` filesystem to be mounted at `/data` by UUID,
preventing accidental writes into the root filesystem's empty mount-point directory.
Because `/` and `/data` share one physical disk, this split provides isolation from
path mistakes but not disk-failure redundancy or independent I/O capacity. Revisit
the storage plan when the dedicated system is available.

## 4. Phase 2 — Remote Access

1. Set hostname `ai-treader-llm`.
2. Create a router DHCP reservation for its Ethernet MAC address.
3. Generate a dedicated, passphrase-protected SSH key on the Mac:
   ```bash
   ssh-keygen -t ed25519 -f ~/.ssh/ai_treader_llm
   ```
4. Add the public key to the server's `~/.ssh/authorized_keys`.
5. Verify key login in a second terminal before changing SSH authentication.

Mac `~/.ssh/config` (replace the example IP):

```sshconfig
Host ai-treader-llm
    HostName 192.168.50.182
    User ai-treader-llm
    IdentityFile ~/.ssh/ai_treader_llm
    IdentitiesOnly yes
    ServerAliveInterval 30
    LocalForward 18080 127.0.0.1:8080
    ExitOnForwardFailure yes
```

SSH policy:

```text
PermitRootLogin no
PubkeyAuthentication yes
PasswordAuthentication no
KbdInteractiveAuthentication no
```

Validate with `sudo sshd -t`, reload SSH, and verify effective settings with `sudo sshd -T`. Keep the existing session open until a new login succeeds. Allow SSH from the actual LAN subnet before enabling UFW; deny other incoming traffic. No router port forwarding. mDNS is optional and unnecessary with the SSH alias.

Daily workflow: `ssh ai-treader-llm`. Use terminal + Git; VS Code Remote SSH is optional. The Mac reaches inference at `http://127.0.0.1:18080/v1` through the tunnel.

## 5. Phase 3 — NVIDIA + Docker

Install in this order.

### 1. OS updates and utilities

```bash
sudo apt update
sudo apt full-upgrade -y
sudo apt install -y \
  openssh-server ufw git curl wget ca-certificates gnupg \
  build-essential tmux htop nvtop jq unzip rsync \
  nvme-cli smartmontools lm-sensors \
  python3 python3-venv python3-pip ubuntu-drivers-common
```

These provide remote administration, downloads/build tools, diagnostics, and isolated Python tooling. GPU Python packages belong in containers.

### 2. NVIDIA driver, then reboot

Use Ubuntu's packaged R580 driver with current security updates, rather than NVIDIA's `.run` installer. Inspect `ubuntu-drivers devices` before installation. [Ubuntu driver installation](https://ubuntu.com/server/docs/how-to/graphics/install-nvidia-drivers/), [R580 package](https://packages.ubuntu.com/en/noble-updates/amd64/nvidia-driver-580)

```bash
ubuntu-drivers devices
sudo ubuntu-drivers install nvidia:580
sudo reboot
```

Complete Secure Boot key enrollment if requested. After reboot, `nvidia-smi` must work.

### 3. Docker Engine and Compose

Configure Docker's official Ubuntu apt repository, then install:

```bash
sudo apt install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

Use the official repository setup instructions; do not mix these packages with Ubuntu's `docker.io`. Docker-group membership is root-equivalent. For this dedicated operator-controlled host, the operator explicitly accepted adding `ai-treader-llm` to that group on 2026-09-29 so deployment automation can use the daemon after a fresh login. Do not add other users. [Docker installation](https://docs.docker.com/engine/install/ubuntu/)

### 4. NVIDIA Container Toolkit

Configure NVIDIA's stable apt repository and install `nvidia-container-toolkit`, then:

```bash
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
sudo docker run --rm --gpus all nvidia/cuda:12.8.1-base-ubuntu24.04 nvidia-smi
```

The toolkit guide listed 1.20.1-1 when checked. [NVIDIA installation](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html)

CUDA strategy: driver on the host; CUDA userspace libraries and build tools inside containers. Do not install a separate host CUDA toolkit. R580 supports the selected CUDA 12.8 environment through backward compatibility. [CUDA compatibility](https://docs.nvidia.com/deploy/cuda-compatibility/minor-version-compatibility.html)

Record installed package versions and container digests after verification. Apply upgrades deliberately and rerun GPU smoke tests.

## 6. Phase 4 — LLM Runtime

Preferred: llama.cpp, for direct GGUF support and explicit context, GPU offload, and memory control. Use its CUDA 12 image; upstream used CUDA 12.8.1 for that image when checked. [Container documentation](https://github.com/ggml-org/llama.cpp/blob/master/docs/docker.md)

Fallback: Ollama, if simpler model lifecycle management becomes more valuable than runtime control. Its OpenAI-compatible API must pass the same contract tests. [Ollama compatibility](https://docs.ollama.com/api/openai-compatibility)

- Initial model: `Qwen/Qwen3-8B`, with instruction following, tool use, and controllable thinking mode.
- Inference: official `Qwen/Qwen3-8B-GGUF`, `Q4_K_M`; approximately 5.03 GB of weights.
- Initial mode: thinking disabled, 4,096 total tokens, one request, maximum 1,024 output tokens.

Qwen3-8B is the reproducible model for the existing L03 deployment, not a default
for new research and not a claim that it is the strongest current model.
[Qwen3-8B](https://huggingface.co/Qwen/Qwen3-8B), [official GGUF](https://huggingface.co/Qwen/Qwen3-8B-GGUF/tree/main)

The executable skeleton uses `compose.yaml`, `.env.example`, and the bootstrap scripts to download an immutable model revision, record its hash, and pin the runtime digest. See [RUNBOOK.md](RUNBOOK.md) for exact commands. The original minimal deployment is equivalent to:

```yaml
services:
  inference:
    image: ghcr.io/ggml-org/llama.cpp:server-cuda
    restart: unless-stopped
    ports: ["127.0.0.1:8080:8080"]
    volumes: ["/data/models:/models:ro"]
    command:
      - --model
      - /models/Qwen3-8B-Q4_K_M.gguf
      - --alias
      - ai-treader-analyst
      - --host
      - 0.0.0.0
      - --port
      - "8080"
      - --n-gpu-layers
      - "99"
      - --ctx-size
      - "8192"
      - --parallel
      - "1"
      - --jinja
      - --reasoning
      - "off"
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    logging:
      driver: json-file
      options: {max-size: "10m", max-file: "3"}
```

First-generation test on the server:

```bash
curl http://127.0.0.1:8080/health
curl http://127.0.0.1:8080/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"ai-treader-analyst","messages":[{"role":"user","content":"Reply with READY."}],"max_tokens":32}'
```

Verify GPU offload in logs. Before baseline evaluation, pin the image digest and model revision/hash. Tool calling and schema-constrained output depend on the model/template pairing and require explicit tests. [Server documentation](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)

## 7. Phase 5 — AI-Treader Integration

Keep orchestration in Go; no separate Python gateway initially. Provider configuration includes `base_url`, `model_alias`, credentials, timeout, context budget, and tool/JSON-schema capabilities. Use `/v1/chat/completions`, `/v1/models`, and `/health`. Normalize provider differences inside the client.

Tool loop:

1. Go fixes the analysis request's `as_of_timestamp`.
2. The model proposes a tool call.
3. Go validates its name and typed arguments.
4. Go executes an allowlisted tool and returns bounded results.
5. The model produces final structured analysis.
6. Go validates and persists it.

Start with prices, fundamentals, filings, news, technical indicators, and market context. Add earnings, insider activity, peers, prior analyses, portfolio exposure, and backtests through existing services. Apply deadlines, result-size limits, and at most six tool rounds. Go enforces time scope; the model cannot override it. No arbitrary SQL, shell execution, URLs, or trading tools.

### Analysis contract

Define versioned JSON Schema and matching Go types, reject unknown fields, require every field, and represent unavailable sections explicitly as `null`:

```text
AnalysisV1 {
  schema_version: "1"
  symbol: string
  timestamp: UTC datetime
  as_of_timestamp: UTC datetime
  horizon: "1d" | "5d" | "30d" | "90d"
  thesis: Claim
  bull_case: Claim[]
  bear_case: Claim[]
  catalysts: Claim[]
  risks: Claim[]
  fundamentals: Section | null
  technicals: Section | null
  sentiment: Section | null
  market_context: Section | null
  confidence: "low" | "medium" | "high"
  missing_data: string[]
  suggested_signal_state: "bullish" | "neutral" | "bearish" | "insufficient_evidence"
}
Claim   = { text: string, evidence_ids: string[] }
Section = { summary: Claim, metric_refs: string[] }
```

The backend assigns/verifies symbol, timestamps, and provenance. Evidence and metric references must resolve to actual tool/retrieval results. Money and calculations stay in deterministic records with units/currencies. Confidence describes evidence quality, not probability of profit. Permit at most one repair attempt; continued invalid output yields no usable signal.

### Postgres and registry

Reuse instruments, market data, documents, portfolios, and analysis records.

| Table | Minimum responsibility |
|---|---|
| `llm_models` | Revision, quantization, artifact hash, runtime digest |
| `llm_datasets` | Immutable manifest, temporal splits, provenance, hash |
| `llm_evaluations` | Deployment configuration, suite version, metrics, report |
| `llm_analysis_runs` | Existing analysis reference, inputs, model/runtime/prompt versions, status |
| `llm_tool_calls` | Run, arguments, snapshot references, latency, errors |

Every registry record has creation time and lifecycle state. Existing L03 deployment
records retain the model, runtime, prompt and schema versions they already use. Numeric
model lifecycle and activation remain platform ALPHA work; this repository does not
add a second model registry. Store large artifacts on disk and paths/hashes in
Postgres. No MLflow or duplicate market-data database.

### Security and observability

Bind inference to loopback and use SSH tunnels. The dedicated Compose bridge is not
marked `internal`: Docker internal networks intentionally have no connection to host
interfaces and therefore cannot publish the required host loopback endpoint. Keep
the explicit `127.0.0.1` binding, mount no credentials or writable application data,
and retain dropped capabilities plus `no-new-privileges`. Docker-published ports can
bypass UFW. Across machines, use a private encrypted network and authenticated
endpoint. [Docker firewall behavior](https://docs.docker.com/engine/install/ubuntu/)

Use restricted secret files, read-only model mounts, and no Docker socket in containers. Retrieved documents are untrusted input. Start with rotated JSON logs, `nvidia-smi`, `nvtop`, `htop`, and disk monitoring. Record loaded deployment, GPU temperature/utilization/VRAM, CPU/RAM, disk usage, request latency, tokens/second, failures, and training progress. Keep sensitive raw payloads out of routine logs.

## 8. Phase 6 — Dataset and evaluation

| Information | Mechanism |
|---|---|
| Prices, ratios, indicators, exposure, returns | Structured APIs and deterministic calculations |
| Filings and research records | Platform-owned point-in-time evidence and bounded as-of summaries |
| Analysis behavior | Versioned hosted prompts/contracts; existing frozen L03 prompt |

The platform already owns document passages, cited evidence and bounded as-of research
summaries. Do not add an LLM-repository RAG or vector-memory layer.

```text
AnalysisSample:
  sample_id, instrument_id, symbol, as_of_timestamp
  price_snapshot_ref, fundamentals_snapshot_ref
  news_refs, filing_refs, earnings_refs
  technical_features_ref, market_context_ref
  model_input, expected_analysis
  source_manifest_hash, split

OutcomeRecord:                 # Separate file/table and permissions
  sample_id, label_end_timestamp
  return_1d, return_5d, return_30d, return_90d
  max_drawdown, volatility
```

Mandatory leakage controls:

- Track event time, publication/availability time, ingestion time, and revision.
- Include only information available by `as_of_timestamp`.
- Faithful platform replay also requires ingestion by then.
- Preserve original filings and unrevised fundamentals; later restatements cannot replace historical inputs.
- Apply timestamp rules to retrieval, prior analyses, and every tool.
- Generate expected analyses from contemporaneous evidence only. Future outcomes must not influence SFT answers.
- Keep outcome files outside LLM/SFT training container mounts and all prediction inputs.
  The separate numeric supervised trainer may read training labels under its split policy;
  evaluation labels stay in the evaluation job.
- Use chronological train/validation/test splits, purging or embargo for overlapping outcome windows.
- Preserve historical universes, delisted securities, and point-in-time corporate-action handling.

Pretraining contamination remains possible: a model may already know subsequent historical events. Treat retrospective results as diagnostic and confirm behavior with prospective paper evaluation after freezing the model.

### Evaluation boundaries

Compare candidates on identical versioned inputs and budgets. Keep hosted research,
the existing L03 experiment, numeric baselines, Chronos and text-feature ablations as
separate protocols; a result in one does not promote another.

```text
Hosted provider arm(s) + deterministic baseline
Existing frozen L03 arm(s)
Regularized linear + LightGBM + deterministic numeric baselines
Chronos-2 and numeric-plus-reviewed-text challengers
```

Measure first-pass/final JSON validity, citation validity, numerical consistency,
unsupported claims, risk identification, abstention, repeat-run consistency, p50/p95
latency, generation speed, peak VRAM, and context failures. Platform workflows that
use tools measure authorization and argument correctness in the platform suite.

Initial proposed gates include 100% valid persisted outputs, zero unauthorized tool
execution and zero timestamp violations. Any platform tool-call threshold belongs to
that workflow's frozen protocol, not a synthetic evaluator in this repository. Report
failures rather than silently dropping them. Historical financial evaluation freezes
downstream signal/portfolio/risk rules and compares walk-forward returns, drawdown,
turnover, and exposure after costs/slippage. Keep financial results separate from
analysis-quality scores.

## 9. Retired local general-LLM expansion

The former standalone tool-suite, RAG, QLoRA, adapter-export and local-model
promotion branch was removed from the backlog on 2026-10-22. Hosted research now
lives in the platform, and numeric learning uses isolated batch jobs. The existing
Qwen deployment remains supported for L03, but it is not extended into a competing
general research stack. Reintroducing any retired capability requires a new explicit
architecture decision, a measured gap and a bounded backlog row.

## 10. Repository Structure

```text
ai-treader-llm/
├── compose.yaml
├── .env.example
├── contracts/             Analysis, dataset, provenance, tools
├── configs/               Inference and evaluation
├── python/                Contracts, dataset integrity, numeric jobs, evaluation
├── docker/
├── scripts/               Bootstrap, qualification and smoke checks
└── docs/
```

Go client and platform migrations belong in the existing backend repository. Large artifacts stay under `/data`, outside Git. Edit on the Mac, commit/push, pull the exact commit into an independent server clone, and build/run Linux amd64 containers there. Avoid remotely mounted source. Use rsync only for explicit artifact transfers.

## 11. Services

| Service | Language | Responsibility | Port/API |
|---|---|---|---|
| Existing backend | Go | Tools, orchestration, validation, persistence | Existing API |
| Inference | C++ / llama.cpp | Generation | Loopback 8080, `/v1/*` |
| Numeric batch job | Python | CPU fit/predict; Chronos evaluation when separately pinned | None |
| Evaluation job | Python | Fixtures, scoring, benchmarks | None |
| Existing Postgres | SQL | Platform records, registry, retrieval | Existing private connection |

Only inference runs continuously on the AI server. Jobs use Compose profiles or one-shot runs. Compose is sufficient; no Kubernetes, service mesh, distributed training platform, or unnecessary supporting service.

## 12. Initial Hardware Limits

The RTX 3080 10 GB is suitable for the existing quantized Qwen deployment and may
be measured for a separately pinned Chronos challenger after HARD01.

It is unsuitable for assumed simultaneous model residency, large concurrent batches
or unmeasured 32K+ context. System RAM is not GPU memory. Do not promise throughput
or challenger capacity before benchmarking the exact pinned workload.

## 13. Fixed resource boundary

The approved plan uses the current CPU environment and RTX 3080. It contains no
larger-GPU, multi-GPU or alternative serving-stack work. If a future measured protocol
cannot run within this boundary, record that limitation and require a new architecture
decision instead of keeping speculative upgrade tasks in this plan.

Durable boundaries: HTTP API, strict schemas, immutable dataset manifests and hashed
model/evaluation artifacts. Hardware changes do not require a platform rewrite.

## 14. Approved supervised research extension (2026-10-06)

The operator approved local personal research using the existing Go platform and
a numeric prediction track. The 2026-10-22 scope keeps hosted Codex/Claude research
in the platform and retains Qwen only for separate L03. This is implementation scope, not
an implemented model, an approved experiment protocol or performance evidence.
The CSV owns order and state; this section defines the architecture.

| Work | This repository | Platform boundary |
|---|---|---|
| Numeric contracts | ALPHA01 delivered strict alpha-forecast-v1, numeric dataset schemas and Python fixtures | ALPHA01 Go shared-fixture conformance delivered |
| Dataset | DATA01 delivered the reviewed R11 source receipt and controlled analysis-target plan; ALPHA02 consumes the frozen export after protocol approval | Platform ALPHA02 delivered PIT features and separate matured labels |
| CPU baseline | ALPHA02 delivered locked ridge/LightGBM training under the frozen ALPHA03 protocol and feature-only batch prediction | ALPHA03 froze the protocol; ALPHA04 imports; ALPHA05 evaluates |
| Pretrained challenger | ALPHA03 benchmarks pinned Chronos-2 without fine-tuning | ALPHA06 compares under separately frozen parameters |
| Text attributes | TEXT01 evaluates reviewed provider-neutral exports and publishes numeric fixtures | AGENT04 workflow is delivered but a real reviewed export is still required; ALPHA07 measures numeric-only versus numeric-plus-text |
| Forward evidence | Immutable artifacts and reproducible jobs | ALPHA09 records matured observation; operator decides promotion |

Begin with daily numeric features, a one-calendar-month target and weekly decisions;
a three-month experiment is separate. A target horizon does not silently force an
exit: the platform protocol must define executable entry, exit and extension rules.
Retain product support for 1–6 month holdings. The 13-listing L03 replay and broader
survivorship-biased pilot/sizing set prove plumbing, not research-universe coverage.

Go exports a hashed snapshot; an isolated one-shot Python job fits or predicts;
Go validates and persists results, including missing/failed predictions. Go owns
financial feature/label definitions, portfolio calculations, policy and execution.
No new daemon, database, broker path or experiment-tracking service is needed.
Numeric CPU dependencies are isolated from the existing LLM runtime. GPU libraries
stay off the Mac/CPU environment. The existing RTX 3080 is the fixed GPU boundary;
optional GPU challengers require HARD01 qualification, resource measurements and
exclusive scheduling. Do not assume concurrent Qwen and forecast-model residency.

Numeric candidate decisions follow held-out and matured forward evidence, including costs,
delays, drawdown, turnover, exposure and failures. CatBoost may be considered if
categorical features justify a bounded comparison. Custom PatchTST/TFT training,
RL and intraday work remain deferred. Platform ALPHA08 is a go/no-go decision on
combining models, not authorization to implement or activate an untested blend.
Local general-LLM RAG and QLoRA are outside the approved architecture.

The existing L03 arms, frozen revision 4 and protected evaluation windows remain
unchanged. Revision 5 still needs its own approval. New numeric work does not wait
for L03e's long observation, but must not tune on L03-protected outcomes. Local,
personal use is accepted scope; retain license/source metadata and explicit unknowns,
without declaring all provider permissions verified or creating a blanket blocker.

Candidate reference: [Chronos-2 official model card](https://huggingface.co/amazon/chronos-2).
Pin a specific revision and runtime at implementation time; general forecasting
benchmarks are not evidence of trading performance.

## 15. Hosted-agent ownership revision (2026-10-07)

Platform AGENT01–06 delivered canonical call instructions, qualified adapters,
bounded proposals/backtests, the text-capture workflow, concise as-of research
records and the evaluation/protocol machinery. AGENT07 remains the separately frozen
matured paper evaluation.
The existing reviewer contract and roles are reused without an unversioned change.
See [platform PLAN](../../ai-treader-platform/tasks/PLAN.md) for exact call and memory
requirements. LLM TEXT01 consumes AGENT04 captures via XPLAT09; it does not own
hosted credentials, provider calls or application database writes.

Platform ALPHA01–03 and CPU ALPHA02 are complete; platform ALPHA04 orchestration is
the next numeric step.
HARD01 remains required before GPU experiments but does not block the CPU or platform
numeric path. CTX01 belongs only to the separate L03 revision-5 path. No provider or
model is silently substituted during an experiment. L03's frozen parameters and
external-provider exclusion remain intact.
