# LLM operations observability

The dashboard is a read-only operational surface served by a restricted native
systemd process. It polls host, Docker, NVIDIA, and llama.cpp telemetry every two
seconds and keeps only a short in-browser resource history. It never exposes raw
prompts, completions, environment variables, credentials, arbitrary files, or
Docker logs.

## Live sources

| Surface | Source | Meaning |
|---|---|---|
| Host | `/proc`, filesystem usage, OS metadata | CPU, RAM, load, uptime, network totals, root and `/data` capacity |
| GPU | bounded `nvidia-smi` query | utilization, VRAM, temperature, power, clocks |
| Runtime | read-only Docker inspect | container state, health, restarts, pinned image, loopback binding |
| Inference | llama.cpp `/health`, `/v1/models`, `/slots`, `/metrics` | readiness, model identity, active slot, token counters; never prompt content |
| Deployment | model receipt, runtime lock, Git metadata | model/revision/hash, image digest, repository commit and dirty state |

An inference slot can prove that generation is active, but cannot explain the
business task. Work attribution comes only from an allowlisted pipeline document.
The inference card reports llama.cpp's current generation-rate metric when available;
zero while idle is expected and is not a benchmark result.

## Pipeline status producer

The future Go orchestration layer may atomically replace
`/data/status/pipeline.json`. The dashboard reads at most 64 KiB, requires schema
version `1`, ignores unknown fields, and returns only the allowlisted fields below.
Write a temporary file in the same directory, `fsync` it, then rename it over the
target. Do not write prompts, model responses, evidence content, credentials, error
stacks, or personal data.

```json
{
  "schema_version": "1",
  "updated_at": "2026-09-29T20:00:05Z",
  "run_id": "analysis-run-id",
  "status": "idle | queued | running | succeeded | failed | cancelled",
  "stage": "idle | collecting | validating_context | inference | validating_output | persisting | evaluating | complete",
  "attempt": 1,
  "progress": {"completed": 3, "total": 7},
  "work": {
    "listing_id": 7,
    "symbol": "AAPL",
    "horizon": "1m",
    "as_of_timestamp": "2026-09-29T20:00:00Z",
    "replay_mode": "platform_replay"
  },
  "message": "Short operator-safe state"
}
```

Running or queued telemetry older than 15 seconds is displayed as stale. Terminal
records may remain until the next run begins. The status file is visibility only;
it is not durable run evidence and cannot authorize a signal, order, promotion, or
policy change. PostgreSQL remains authoritative once L03b persistence exists.

## Training status producer

Future training code may atomically replace `/data/status/training.json` with the
same size and safety rules. Accepted status values are `idle`, `queued`, `running`,
`succeeded`, `failed`, and `cancelled`; stages are `idle`, `preparing`,
`loading_model`, `training`, `checkpointing`, `exporting`, `evaluating`, and
`complete`. Optional allowlisted fields are `run_id`, `dataset_id`, `progress`,
`epoch`, `total_epochs`, `step`, `total_steps`, finite `loss`, `eta_seconds`, and a
short operator-safe `message`. The dashboard must show unavailable until a real
producer exists.

## Network boundary

The dashboard listens on TCP 8090 and is the only service exposed to the LAN. UFW
admits that port only from `192.168.50.0/24`. llama.cpp remains on
`127.0.0.1:8080`; remote inference continues through the SSH tunnel. The dashboard
has no write route and no cross-origin API access. Anyone on the allowed LAN can
read the displayed operational metadata, so a broader or untrusted network requires
authentication before exposure.
