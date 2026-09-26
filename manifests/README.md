# Artifact manifests

A downloaded model receives `<name>.manifest.json` beside the GGUF. Store actual
reviewed deployment manifests here when available; do not invent revisions or
hashes. Each deployment must identify:

- base repository/revision and tokenizer/chat-template revision;
- inference artifact SHA-256 and quantization;
- runtime image digest, context settings, prompt/schema hashes;
- adapter hash/version and exact compatible base, when present;
- dataset manifest hash, training config hash, code commit and seed;
- evaluation suite/report hashes, creation time, lifecycle state.

Dataset manifests additionally describe immutable source snapshots, chronological
splits, label horizons, purge/embargo policy, licensing, and reviewer provenance.
The platform registry is the source of truth for the active deployment. Git/files
hold artifacts and reproducibility metadata, not a second active-state database.
