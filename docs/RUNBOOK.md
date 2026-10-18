# Development and first-server runbook

## Mac: start now, without a GPU

Prerequisites: Git and `uv`. Run from the repository root:

```bash
uv sync --frozen --python 3.12
make check
uv run --frozen ai-treader-llm build-inputs examples/samples.jsonl
uv run --frozen ai-treader-llm evaluate-tools \
  examples/tool-call-fixtures.jsonl examples/tool-call-predictions.jsonl
```

Fixtures are synthetic. The evaluators check schema/reference validity and offline
tool-call correctness; a passing run does not demonstrate a useful financial model,
actual tool execution, or deployed template/parser compatibility.

## Server: after hardware, Ubuntu, SSH, and GPU setup

For a new host, follow phases 0–3 of [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md)
and the unfinished HOST/HARD rows in [the backlog](../tasks/BACKLOG.csv). On the
current interim dual-boot host, `/dev/sda` is the only disk permitted for Linux and
AI-Treader. Do not mount, format, repartition, repair, or store anything on
`/dev/nvme0n1` or `/dev/nvme1n1`; both belong to Windows. The scripts here do not
install the OS, change SSH, or provision the host automatically.

From the normal `ai-treader-llm` sudo account, verify that `/data` is the approved
`/dev/sda1` ext4 filesystem, mounted persistently by UUID, then:

```bash
mountpoint /data
findmnt -no SOURCE,FSTYPE,TARGET / /data
grep -F ' /data ' /etc/fstab
sudo install -d -o ai-treader-llm -g ai-treader-llm /srv/ai-treader
sudo install -d -o ai-treader-llm -g ai-treader-llm \
  /data/models /data/datasets /data/checkpoints /data/adapters \
  /data/cache /data/evaluations /data/training /data/status
git clone git@github.com:ragabi-ops/ai-treader-llm.git /srv/ai-treader
cd /srv/ai-treader
cp .env.example .env
sudo bash scripts/smoke/gpu.sh
python3 scripts/bootstrap/download-model.py --destination /data/models
sudo bash scripts/bootstrap/pin-runtime.sh
sudo docker compose --env-file .env --env-file configs/runtime.lock.env config --quiet
sudo docker compose --env-file .env --env-file configs/runtime.lock.env up -d inference
sudo docker compose --env-file .env --env-file configs/runtime.lock.env logs --tail=100 inference
curl --fail http://127.0.0.1:8080/health
```

The operator accepted root-equivalent Docker access for the dedicated
`ai-treader-llm` account on 2026-09-29. Add only that account, then disconnect and
open a fresh SSH session before using Docker without `sudo`:

```bash
sudo usermod -aG docker ai-treader-llm
id
docker version
```

The fresh session's `id` output must contain `docker`. Do not grant this group to
other users.

### Hardware qualification capture

Install `dmidecode`, `smartmontools`, and `lm-sensors` on the target, then capture
the read-only HARD01 evidence as root. The script is fixed to `/dev/sda`, verifies
the expected `/` and `/data` mounts, and checks mount metadata for the Windows-owned
NVMe devices. It never opens or probes either NVMe device. Keep the generated record
out of Git because it includes hardware serial numbers.

```bash
sudo bash scripts/qualification/hardware.sh \
  | tee /data/evaluations/hardware-qualification-$(date -u +%Y%m%dT%H%M%SZ).txt
```

The PSU is not normally exposed by consumer motherboard firmware. Separately record
the manufacturer, exact model, rated wattage, physical condition, and whether the
GPU power plugs use the connector layout required by the exact card. Inspect dust,
fan operation, and cable seating while powered off. A software estimate or the GPU's
reported power limit is not evidence of PSU capacity.

For cooling acceptance, bracket a versioned sustained benchmark with
`nvidia-smi -q -d PERFORMANCE,TEMPERATURE,POWER`. Record peak temperature, fan and
power behavior, any active slowdown reason, and before/after slowdown counters.
Do not interpret a stable endpoint response alone as proof of adequate cooling.

The checkout directory must be empty for `git clone`. Use your existing Git access
or a repository-scoped read-only key on the server. No agent forwarding is required.
`pin-runtime.sh` pulls an amd64 image and writes the actual digest; the placeholder
in `.env` is overridden by the second env file. Do not copy a made-up digest.

The downloader resolves the model's full repository SHA and verifies the official
LFS SHA-256 before publishing the file. It refuses to replace a different existing
model. For upgrades, use a new versioned directory and update `MODEL_DIR`. Keep the
adjacent `.manifest.json` with the artifact. The inference container uses a dedicated
bridge because Docker internal networks cannot publish the host loopback endpoint.
Only `127.0.0.1:8080` is published; the model mount is read-only, no credentials or
writable application data are mounted, all capabilities are dropped, and
`no-new-privileges` remains enabled.

First completion:

```bash
curl --fail http://127.0.0.1:8080/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"ai-treader-analyst","messages":[{"role":"user","content":"Reply with READY."}],"max_tokens":32}'
```

Confirm GPU layer offload and VRAM usage in logs/`nvidia-smi`. A successful HTTP
response alone does not prove GPU execution. Run final-schema and tool-call contract
tests before wiring an analysis into the platform.

## Mac: connect through SSH

Use the SSH config from the implementation plan. Leave `ssh ai-treader-llm` connected,
then in another Mac terminal at the repository root:

```bash
scripts/smoke/inference.sh
```

The default URL is `http://127.0.0.1:18080`; the server-local URL is port 8080.
Do not publish the inference port on all interfaces. A containerized Go backend
needs an explicit tunnel/network integration; its own localhost is not the Mac's.

For an always-on Mac tunnel, include both forwards and failure detection in the
`Host ai-treader-llm` block of `~/.ssh/config`:

```sshconfig
ServerAliveInterval 30
ServerAliveCountMax 3
LocalForward 18080 127.0.0.1:8080
LocalForward 18090 127.0.0.1:8090
ExitOnForwardFailure yes
```

Install the supplied per-user launch agent, after closing any manual
`ssh ai-treader-llm` session that owns port 18080:

```bash
install -d -m 0700 ~/Library/LaunchAgents
install -m 0600 scripts/bootstrap/com.ai-treader.llm-tunnel.plist \
  ~/Library/LaunchAgents/com.ai-treader.llm-tunnel.plist
launchctl bootstrap "gui/$(id -u)" \
  ~/Library/LaunchAgents/com.ai-treader.llm-tunnel.plist
launchctl kickstart -k "gui/$(id -u)/com.ai-treader.llm-tunnel"
curl --fail http://127.0.0.1:18080/health
curl --fail http://127.0.0.1:18090/health
```

`launchd` starts the tunnel at Mac login and restarts it after network or SSH
failures. The dashboard is therefore reachable at both the direct LAN address and
`http://127.0.0.1:18090/`; inference remains private at
`http://127.0.0.1:18080/`. The launch agent uses batch mode and the dedicated key,
so it cannot stop for an interactive password or host-key prompt.

## Start after reboot

The inference unit starts Compose only after `/data` is mounted. The dashboard runs
as a restricted native process, reads the Docker socket through the already accepted
`docker` group membership, and listens on TCP 8090. Install both units:

```bash
sudo install -m 0644 scripts/bootstrap/ai-treader-llm.service /etc/systemd/system/
sudo install -m 0644 scripts/bootstrap/ai-treader-dashboard.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ai-treader-llm ai-treader-dashboard
systemctl --no-pager --full status ai-treader-llm ai-treader-dashboard
curl --fail http://127.0.0.1:8090/health
```

Compose uses `on-failure`, which handles process crashes but does not independently
start the existing container when Docker restarts. This leaves boot ordering to
systemd. After manually restarting Docker, restart `ai-treader-llm` as well. Recheck
GPU access after daemon reloads; NVIDIA documents a cgroup-related GPU-access issue.

Permit the dashboard only from the trusted internal subnet; never expose llama.cpp
port 8080 to the LAN:

```bash
sudo ufw allow from 192.168.50.0/24 to any port 8090 proto tcp comment 'LLM dashboard'
sudo ufw status numbered
```

From a Mac on that subnet, open `http://192.168.50.182:8090/`. The UI refreshes every
two seconds. It intentionally shows pipeline and training telemetry as unavailable
until a real producer atomically writes the allowlisted files in `/data/status`; see
[OBSERVABILITY.md](OBSERVABILITY.md). Anyone on the allowed subnet can read operational
metadata, so add authentication before using a broader or untrusted network.

## CPU job container (optional)

On the server after runtime pinning:

```bash
sudo docker compose --env-file .env --env-file configs/runtime.lock.env \
  --profile jobs run --rm --build jobs validate-dataset examples/samples.jsonl
```

This image contains synthetic fixtures and CPU tooling only. Real jobs must mount
explicit input directories read-only; never mount the entire `/data` tree into a
trainer. Run jobs locally with `uv` on the Mac to avoid the GPU Compose dependency.

## Stop, upgrade, and recover

```bash
sudo systemctl stop ai-treader-llm
sudo docker compose --env-file .env --env-file configs/runtime.lock.env stop inference
```

Stop inference before any future training job. An exclusive GPU job lock is still
required in the future trainer. Save the previous runtime lock, model receipt, and
configuration before changing any version. Re-run GPU, endpoint, tool, and schema
tests after upgrades; rollback restores the previous bundle and restarts inference.

## Numeric contract validation and planned jobs

ALPHA01 installs offline numeric contract validators; it does not install a model
or prediction job. Validate the committed synthetic bundle with:

```bash
uv run --frozen ai-treader-llm validate-numeric-input examples/numeric-v1/input-manifest.json
uv run --frozen ai-treader-llm validate-numeric-dataset examples/numeric-v1/dataset-manifest.json
uv run --frozen ai-treader-llm validate-alpha examples/numeric-v1/forecast.json \
  --request examples/numeric-v1/request.json \
  --input examples/numeric-v1/input-manifest.json
```

Regenerate the shared Python/Go conformance fixtures after a deliberate contract
change with `uv run --frozen python -m ai_treader_llm.numeric_fixtures`, then run
`make check`. Contract changes require a new version once platform adoption begins.

Until their later acceptance closes, do not report training, Chronos-2 forecasting
or text extraction as available.
Future jobs use locked CPU dependencies for the linear/LightGBM baseline, immutable
platform exports, separate fit/evaluation labels and feature-only prediction mounts.
Keep models, datasets and generated reports out of Git. GPU runs require measured
capacity and one exclusive GPU owner; GPU packages are not Mac/CPU dependencies.

The 8192-context / 2048-output candidate is already reflected in pre-existing local
configuration edits and a host override. CTX01 must capture realistic first/repair
requests, overflow, sustained latency/VRAM, recovery and rollback with exact hashes.
BENCH01 measured the earlier configuration; the pre-fence 52/52 platform probe is
not a full endpoint benchmark or approval of L03 revision 5. This planning change
neither deploys configuration nor freezes that revision.

## Hosted-agent priority (2026-10-07)

The platform owns Codex/Claude bridge operation and future agent call contracts.
Local numeric CPU work does not require Qwen, CTX01 or TOOLS01 completion. Preserve
the existing endpoint and uncommitted qualification/configuration changes; this
planning revision does not stop inference or change L03. HARD01 still gates GPU
experiments. Hosted qualification, data disclosure, rate/cost limits and runtime
failure behavior are platform AGENT tasks; TEXT01 only evaluates exported captures.
