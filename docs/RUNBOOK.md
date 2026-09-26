# Development and first-server runbook

## Mac: start now, without a GPU

Prerequisites: Git and `uv`. Run from the repository root:

```bash
uv sync --frozen --python 3.12
make check
uv run --frozen ai-treader-llm build-inputs examples/samples.jsonl
```

Fixtures are synthetic. The evaluator checks schema and reference validity only;
a passing fixture run does not demonstrate a useful financial model.

## Server: after hardware, Ubuntu, SSH, and GPU setup

Follow phases 0–3 of [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) first. Do not
run disk-formatting commands against unverified devices. The scripts here do not
install the OS, change SSH, or provision the host automatically.

From the normal `aitreader` sudo account, verify `/data` is actually mounted, then:

```bash
mountpoint /data
sudo install -d -o aitreader -g aitreader /srv/ai-treader
sudo install -d -o aitreader -g aitreader \
  /data/models /data/datasets /data/checkpoints /data/adapters \
  /data/cache /data/evaluations /data/training
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

The checkout directory must be empty for `git clone`. Use your existing Git access
or a repository-scoped read-only key on the server. No agent forwarding is required.
`pin-runtime.sh` pulls an amd64 image and writes the actual digest; the placeholder
in `.env` is overridden by the second env file. Do not copy a made-up digest.

The downloader resolves the model's full repository SHA and verifies the official
LFS SHA-256 before publishing the file. It refuses to replace a different existing
model. For upgrades, use a new versioned directory and update `MODEL_DIR`. Keep the
adjacent `.manifest.json` with the artifact. Downloads need Internet access; serving
does not, and the inference container uses an isolated internal Docker network.

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

Use the SSH config from the implementation plan. Leave `ssh ai-treader-ai` connected,
then in another Mac terminal at the repository root:

```bash
scripts/smoke/inference.sh
```

The default URL is `http://127.0.0.1:18080`; the server-local URL is port 8080.
Do not publish the inference port on all interfaces. A containerized Go backend
needs an explicit tunnel/network integration; its own localhost is not the Mac's.

## Start after reboot

The supplied systemd unit starts Compose only after `/data` is mounted:

```bash
sudo cp scripts/bootstrap/ai-treader-llm.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ai-treader-llm
```

Compose uses `on-failure`, which handles process crashes but does not independently
start the existing container when Docker restarts. This leaves boot ordering to
systemd. After manually restarting Docker, restart `ai-treader-llm` as well. Recheck
GPU access after daemon reloads; NVIDIA documents a cgroup-related GPU-access issue.

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
