# Development and server runbook

## Mac: start now

Prerequisites: Git and `uv`. Run from the repository root:

```bash
uv sync --frozen --python 3.12
make check
uv run --frozen ai-treader-llm build-inputs examples/samples.jsonl
```

Fixtures are synthetic. The validators and evaluator check contract, dataset and
reference integrity; a passing run does not demonstrate a useful financial model.

## Server: CPU numeric host

The target host runs the CPU numeric jobs only; there is no GPU or local-model runtime
(CLEAN02, 2026-10-27). On the current dual-boot host `/dev/sda` is the only disk
permitted for Linux and AI-Treader. Do not mount, format, repartition, repair, or store
anything on `/dev/nvme0n1` or `/dev/nvme1n1`; both belong to Windows.

From the `ai-treader-llm` account, with `/data` the approved `/dev/sda1` ext4 filesystem
mounted by UUID:

```bash
mountpoint /data
sudo install -d -o ai-treader-llm -g ai-treader-llm /srv/ai-treader
sudo install -d -o ai-treader-llm -g ai-treader-llm /data/datasets /data/cache /data/evaluations /data/training
git clone git@github.com:ragabi-ops/ai-treader-llm.git /srv/ai-treader
```

**Retire the old inference services** (once, operator action) — the Qwen/llama.cpp unit
and its dashboard are no longer part of the architecture:

```bash
sudo systemctl disable --now ai-treader-llm ai-treader-dashboard
sudo rm /etc/systemd/system/ai-treader-llm.service /etc/systemd/system/ai-treader-dashboard.service
sudo systemctl daemon-reload
sudo ufw status numbered   # delete the 'LLM dashboard' 8090 rule if present
```

On the Mac, unload `~/Library/LaunchAgents/com.ai-treader.llm-tunnel.plist` and drop the
`LocalForward 18080/18090` lines; numeric jobs use plain `ssh ai-treader-llm`. Model files
under `/data/models` may be deleted by the operator.

## CPU job container (optional)

```bash
docker compose --profile jobs run --rm --build jobs validate-dataset examples/samples.jsonl
```

This image contains synthetic fixtures and CPU tooling only. Real jobs must mount
explicit input directories read-only; never mount the entire `/data` tree into a
trainer.

For a real source bundle, validate its tracked review receipt first. Omitting the
optional roots checks the receipt and linked target plan structurally. Supplying
the read-only roots also checks the capture manifest, compressed/decoded bytes and
the platform identity/calendar source files:

```bash
uv run --frozen ai-treader-llm validate-source-review \
  examples/data-review-v1/sec-edgar-r11.json \
  --source-root ../ai-treader-platform/backend/internal/secfacts/testdata/r11 \
  --platform-root ../ai-treader-platform
```

This receipt approves the recorded SEC source for local personal research and
records its survivorship-biased pilot scope. Its linked target plan pins the current
development-database listing IDs, the platform calendar files, nine one-month 2024
targets, date-grouped train/validation/test splits, 21-session embargo evidence and
the held-out boundary. It deliberately carries `public_information` reconstruction
rather than claiming historical platform ingestion. It contains neither reviewed
expected analyses nor outcome labels and is not eligible for training or performance
claims. Re-export listing IDs after a platform database rebuild; keep any later
outcomes in their separate artifact.

## Numeric contract validation and CPU numeric jobs

ALPHA01 installs offline numeric contract validators. Validate the committed
synthetic bundle with:

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

ALPHA02 adds the CPU ridge/LightGBM jobs. They need the locked `numeric` extra
(`make setup-numeric`; on macOS LightGBM also needs `libomp`, so the jobs and
`make test-numeric` run on the Linux target host). `make check` runs both lanes;
`make check-core` runs the contract lane alone. Inputs are immutable platform
numeric exports (`calendar.json`, `input-manifest.json`, `features.jsonl`,
`labels.jsonl`, unchanged bytes) under `/data/datasets/alpha03/`; outputs are new
directories under `/data/training/alpha03/`:

```bash
uv run --frozen --extra numeric ai-treader-llm alpha-train \
  --input /data/datasets/alpha03/alpha03-dev-1m/input-manifest.json \
  --labels /data/datasets/alpha03/alpha03-dev-1m/labels.jsonl \
  --labels-sha256 <labels_sha256 the platform recorded> \
  --benchmark-listing-id 11 --horizon 1m \
  --out /data/training/alpha03/1m-<dataset_id>
uv run --frozen --extra numeric ai-treader-llm alpha-predict \
  --challengers /data/training/alpha03/1m-<dataset_id>/challengers.json --arm G \
  --input <feature-only input-manifest.json> --request <alpha-request-v1> --out forecast.json
```

`alpha-train` refuses parameters other than the frozen ALPHA03 file
(`configs/numeric/alpha03-parameters.json`, sha256 `5cba481a…acac5`), an export
whose decisions differ from the protocol windows, a label at or past the fence and
an existing output directory. It writes `trial-draw.json` before any fit, then
`trials.jsonl`, `artifacts/{R,G}.json`, `training-manifest.json`,
`challengers.json` and `run.json` (timing only). A rerun on the same runtime
reproduces every file except `run.json` byte for byte. `alpha-predict` reads no
labels and refuses a request whose model pins or score semantics differ from
`challengers.json`, or a host whose code or runtime hash differs from the frozen
one. `alpha-request` builds such a request for local checks; the platform builds
its own under ALPHA04. Chronos-2 forecasting and text extraction are not available.
Keep models, datasets and generated reports out of Git. All numeric work runs on CPU;
GPU packages are not dependencies.

## Hosted-agent and numeric split

The platform owns the Codex/Claude bridges, agent call contracts, hosted qualification,
data disclosure, rate/cost limits and runtime failure behavior. This repository owns the
CPU numeric jobs and evaluates reviewed text exports (TEXT01), which do not yet exist.
