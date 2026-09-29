# AI-Treader local LLM implementation plan

Accepted architecture reference, 2026-09-26. This document describes implementation
shape, not current task state or order. See [root STATUS](../STATUS.md) and
[the backlog](../tasks/BACKLOG.csv) for delivery state, and [CODE_DESIGN.md](CODE_DESIGN.md)
for module boundaries. Hardware compatibility references were checked during planning;
every deployment still requires validation on its target machine.

## 1. Recommended Final Architecture

**First, prepare and verify the Windows machine, then install Ubuntu Server.** Upgrade to 64 GB RAM if practical; keep the existing GPU and disks. On the current interim dual-boot host, Linux may use only `/dev/sda`; both NVMe devices are reserved for Windows and must not be mounted, formatted, repartitioned, or used for AI-Treader data. A future dedicated host may adopt a different disk layout only through a separate operator decision.

| Component | Decision |
|---|---|
| OS | Ubuntu Server 24.04 LTS, current 24.04.5 server installation image |
| Deployment | Docker Engine + Compose |
| Inference | llama.cpp, CUDA container |
| Initial model | Qwen3-8B, GGUF Q4_K_M |
| Initial capacity | One request at a time; 4,096-token total context |
| Backend | Existing Go backend with a small LLM client/orchestrator |
| Training | On-demand Python container: Unsloth, PyTorch, Transformers, PEFT, TRL, bitsandbytes |
| Persistence | Existing Postgres + versioned artifacts on disk |
| Retrieval | Existing Postgres, with pgvector when document retrieval is introduced |

Deployment decision, accepted 2026-09-29: keep inference in the pinned Docker
container on the interim host, run the read-only operations dashboard as a
restricted native systemd service, and run future training/evaluation containers
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
Go AI-Treader backend                       ├─ llama.cpp inference
 ├─ LLM client ── private HTTP ─────────────►│
 ├─ Tool dispatcher                         ├─ Training jobs
 │   ├─ Structured market-data services     └─ Evaluation / embedding jobs
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

64 GB is sufficient for preprocessing and CPU-side model merging. 128 GB offers little immediate benefit because 10 GB VRAM remains the main training constraint. Starting inference with the existing 32 GB is viable. The board revision matters for firmware and memory compatibility. [Gigabyte specifications](https://www.gigabyte.com/Motherboard/B550-AORUS-ELITE-AX-V2-rev-10/sp)

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
| `/dev/sda1` | ext4 `/data`, mounted by UUID | Models, datasets, adapters, training artifacts |
| `/dev/nvme0n1`, `/dev/nvme1n1` | Windows-owned; out of scope | Never mount, format, repartition, or use from this deployment |

```text
/srv/ai-treader/          Git checkout, Compose configuration
/data/models/            Immutable inference and original model files
/data/datasets/          Versioned snapshots and manifests
/data/checkpoints/       Resumable training checkpoints
/data/adapters/          PEFT adapters
/data/cache/             Disposable Hugging Face / download caches
/data/evaluations/       Reports and evaluation outputs
/data/training/          Training logs and exports
```

Use the existing plain ext4 filesystems on `/dev/sda`; skip LVM, ZFS, and RAID.
Keep approximately 15–20% disk space free. Enable periodic TRIM when supported by
the external SSD. Back up irreplaceable datasets, adapters, metadata, and database
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

Defer vLLM until larger VRAM or concurrency justifies it. Transformers remains part of training and reference evaluation. [vLLM requirements](https://docs.vllm.ai/en/latest/getting_started/installation/gpu/)

- Initial model: `Qwen/Qwen3-8B`, with instruction following, tool use, and controllable thinking mode.
- Inference: official `Qwen/Qwen3-8B-GGUF`, `Q4_K_M`; approximately 5.03 GB of weights.
- Current comparison candidate: `Qwen/Qwen3.5-9B`; evaluate text-only analysis and memory usage before replacement.
- Initial mode: thinking disabled, 4,096 total tokens, one request, maximum 1,024 output tokens.
- Training source: original Hugging Face safetensors at a recorded revision.
- Training quantization: bitsandbytes NF4 with double quantization.
- Adapter format: PEFT safetensors + adapter configuration.

Qwen3-8B is selected for a reproducible first deployment and training path, not as a claim that it is the strongest current model. [Qwen3-8B](https://huggingface.co/Qwen/Qwen3-8B), [official GGUF](https://huggingface.co/Qwen/Qwen3-8B-GGUF/tree/main), [Qwen3.5-9B](https://huggingface.co/Qwen/Qwen3.5-9B)

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
      - "4096"
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
| `llm_adapters` | Exact base, version, artifact, training-run reference |
| `llm_datasets` | Immutable manifest, temporal splits, provenance, hash |
| `llm_training_runs` | Dataset, configuration, code/image versions, status, artifacts |
| `llm_evaluations` | Deployment configuration, suite version, metrics, report |
| `llm_analysis_runs` | Existing analysis reference, inputs, model/adapter/prompt versions, status |
| `llm_tool_calls` | Run, arguments, snapshot references, latency, errors |

Every registry record has creation time and lifecycle state. A single active deployment reference contains model, adapter, runtime, prompt, and schema versions. Promotion updates it atomically; retain the previous deployment for rollback. Store large artifacts on disk and paths/hashes in Postgres. No MLflow or duplicate market-data database.

### Security and observability

Bind inference to loopback and use SSH tunnels. The dedicated Compose bridge is not
marked `internal`: Docker internal networks intentionally have no connection to host
interfaces and therefore cannot publish the required host loopback endpoint. Keep
the explicit `127.0.0.1` binding, mount no credentials or writable application data,
and retain dropped capabilities plus `no-new-privileges`. Docker-published ports can
bypass UFW. Across machines, use a private encrypted network and authenticated
endpoint. [Docker firewall behavior](https://docs.docker.com/engine/install/ubuntu/)

Use restricted secret files, read-only model mounts, and no Docker socket in containers. Retrieved documents are untrusted input. Start with rotated JSON logs, `nvidia-smi`, `nvtop`, `htop`, and disk monitoring. Record loaded deployment, GPU temperature/utilization/VRAM, CPU/RAM, disk usage, request latency, tokens/second, failures, and training progress. Keep sensitive raw payloads out of routine logs.

## 8. Phase 6 — Dataset / RAG / Evaluation

| Information | Mechanism |
|---|---|
| Prices, ratios, indicators, exposure, returns | Structured APIs and deterministic calculations |
| Filings, transcripts, reports, strategy documents | Timestamp-filtered document retrieval |
| Formatting, tool selection, analysis behavior | Prompts first; fine-tuning later |

Introduce RAG after the tool baseline. Use Postgres full-text search plus pgvector, with `BAAI/bge-small-en-v1.5` on CPU for English document embeddings. Chunk by document sections, preserve citations, and respect the embedding input limit. This avoids consuming inference VRAM or adding a vector database. [pgvector](https://github.com/pgvector/pgvector), [embedding model](https://huggingface.co/BAAI/bge-small-en-v1.5)

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
- Keep outcome files outside training container mounts.
- Use chronological train/validation/test splits, purging or embargo for overlapping outcome windows.
- Preserve historical universes, delisted securities, and point-in-time corporate-action handling.

Pretraining contamination remains possible: a model may already know subsequent historical events. Treat retrospective results as diagnostic and confirm behavior with prospective paper evaluation after freezing the model.

### Evaluation before training

Start with approximately 200 reviewed cases including normal conditions, missing/stale data, conflicting evidence, malformed tools, and document prompt injection. Compare identical cases and budgets:

```text
Qwen3-8B + tools
Qwen3.5-9B + tools
Selected model + tools + RAG
Selected model + tools + RAG + adapter
```

Measure first-pass/final JSON validity; tool name/argument correctness and unnecessary calls; citation validity, numerical consistency, unsupported claims; risk identification and abstention; repeat-run consistency; p50/p95 latency, generation speed, peak VRAM, and context failures.

Initial proposed gates: 100% valid persisted outputs, zero unauthorized tool execution, zero timestamp violations, and at least 95% tool-call correctness on reviewed fixtures. Report failures rather than silently dropping them. Historical financial evaluation freezes downstream signal/portfolio/risk rules and compares walk-forward returns, drawdown, turnover, and exposure after costs/slippage. Keep financial results separate from analysis-quality scores.

## 9. Phase 7 — QLoRA Training

```text
Base → Tools/prompts → Evaluation → Failure collection
     → Reviewed dataset → QLoRA → Evaluation → Promotion
```

Start with one general financial-analysis adapter, only after measured failures justify training.

| Dependency | Purpose |
|---|---|
| PyTorch | GPU tensor computation |
| Transformers | Loading and tokenization |
| PEFT | Portable adapters |
| TRL | Supervised fine-tuning |
| bitsandbytes | NF4 and memory-efficient optimization |
| Unsloth | Reduce training memory |

Use upstream Unsloth core, pinned by digest, without Studio/Jupyter. Preserve its compatible dependency set instead of independently upgrading PyTorch/Transformers. [Unsloth Docker](https://unsloth.ai/docs/get-started/install/docker.md), [Qwen3 training](https://unsloth.ai/blog/qwen3)

For a separately built reference environment, PyTorch 2.10.0 with CUDA 12.8 wheels is a verified available combination, not a claim that every current Unsloth release accepts it. Resolve and lock the actual training container's full package inventory in its smoke test. [PyTorch versions](https://pytorch.org/get-started/previous-versions/)

```text
4-bit NF4 + double quantization
BF16 compute when supported
sequence length: 1,024 initially; test 2,048 afterward
microbatch: 1
gradient accumulation: 16
LoRA rank: 8; alpha: 16
targets: attention projections initially
gradient checkpointing: enabled
optimizer: paged AdamW 8-bit
learning rate: 1e-4
epochs: 1 initially
loss: assistant responses only
```

These starting values require a short memory and convergence test. Stop inference during training and enforce one GPU-job lock. If memory is insufficient, shorten sequences before changing architecture.

Save PEFT, merge with the exact original base using CPU RAM, convert to GGUF, then quantize to Q4_K_M. Evaluate the final quantized deployment artifact, not only the training checkpoint. Preserve the unmerged adapter for future runtimes. Promote only if targeted failures improve without material grounding, tool-use, or risk regressions. Specialized adapters for filings, earnings, risk, and theses can follow if evaluation demonstrates a need.

## 10. Repository Structure

```text
ai-treader-llm/
├── compose.yaml
├── .env.example
├── contracts/             Analysis, dataset, provenance, tools
├── configs/               Inference, training, evaluation
├── python/                Dataset, retrieval, training, evaluation
├── docker/
├── scripts/               Bootstrap, smoke, export, promotion
└── docs/
```

Go client and platform migrations belong in the existing backend repository. Large artifacts stay under `/data`, outside Git. Edit on the Mac, commit/push, pull the exact commit into an independent server clone, and build/run Linux amd64 containers there. Avoid remotely mounted source. Use rsync only for explicit artifact transfers.

## 11. Services

| Service | Language | Responsibility | Port/API |
|---|---|---|---|
| Existing backend | Go | Tools, orchestration, validation, persistence | Existing API |
| Inference | C++ / llama.cpp | Generation | Loopback 8080, `/v1/*` |
| Training job | Python | QLoRA and export | None |
| Evaluation job | Python | Fixtures, scoring, benchmarks | None |
| Embedding/ingestion job | Python, CPU | Documents and vectors | None initially |
| Existing Postgres | SQL | Platform records, registry, retrieval | Existing private connection |

Only inference runs continuously on the AI server. Jobs use Compose profiles or one-shot runs. Compose is sufficient; no Kubernetes, service mesh, distributed training platform, or unnecessary supporting service.

## 12. Initial Hardware Limits

The RTX 3080 10 GB is suitable for one quantized 7B–8B model with modest context; structured analysis, summaries, and bounded tool loops; carefully configured short-context QLoRA.

It is unsuitable for full-precision 8B inference entirely in VRAM; full fine-tuning or foundation-model training; simultaneous training/inference; large concurrent batches or assumed 32K+ context. System RAM is not GPU memory. Start at 4K context and increase only after measuring realistic peak memory. Do not promise tokens/second before benchmarking this exact system.

## 13. Upgrade Path

1. 24 GB+ GPU: increase context/training sequence length and evaluate larger models. Recheck PSU/cooling.
2. More serving demand: evaluate vLLM behind the same Go provider interface.
3. Multiple GPUs: independent workers first; split models only as needed. Verify motherboard bandwidth and clearance.
4. Cloud training: same locked image and immutable datasets; return adapters/evaluation artifacts.
5. Remote inference: endpoint/authentication changes followed by provider contract tests.

Durable boundaries: HTTP API, typed tools, analysis schema, immutable dataset manifests, portable adapters, deployment registry. Hardware changes do not require a platform rewrite.
