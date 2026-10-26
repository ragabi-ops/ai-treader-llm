.PHONY: setup setup-numeric setup-chronos test test-numeric test-chronos check check-core fixtures
setup:
	uv sync --frozen --python 3.12

setup-numeric:
	uv sync --frozen --python 3.12 --extra numeric

# Isolated Chronos-2 runtime (own uv.lock; CPU-only torch). The root lock is untouched.
setup-chronos:
	uv sync --frozen --project runtimes/chronos

# Contract tooling; the numeric job tests need the numeric extra (and libomp on macOS).
test:
	uv run --frozen python -m unittest discover -s tests -p 'test_[!a]*.py' -v

test-numeric:
	uv run --frozen --extra numeric python -m unittest discover -s tests -p 'test_alpha_*.py' -v

# Real Chronos-2 smoke in the isolated runtime; set CHRONOS_WEIGHTS to a chronos-fetch directory.
test-chronos:
	uv run --frozen --project runtimes/chronos python -m unittest discover -s tests -p 'test_chronos*.py' -v

fixtures:
	uv run --frozen ai-treader-llm validate-analysis examples/analysis.json --context examples/context.json
	uv run --frozen ai-treader-llm validate-dataset examples/samples.jsonl
	uv run --frozen ai-treader-llm validate-outcomes examples/samples.jsonl examples/outcomes.jsonl
	uv run --frozen ai-treader-llm validate-manifest examples/dataset-manifest.json
	uv run --frozen ai-treader-llm evaluate examples/samples.jsonl examples/predictions.jsonl
	uv run --frozen ai-treader-llm validate-analysis examples/v2/analysis.json --context examples/v2/context.json
	uv run --frozen ai-treader-llm validate-outcomes examples/v2/samples.jsonl examples/v2/outcomes.jsonl
	uv run --frozen ai-treader-llm validate-manifest examples/v2/dataset-manifest.json --evaluation-boundary 2025-06-01T00:00:00Z
	uv run --frozen ai-treader-llm validate-source-review examples/data-review-v1/sec-edgar-r11.json
	uv run --frozen ai-treader-llm validate-data-targets examples/data-review-v1/sec-edgar-r11-analysis-targets.json
	uv run --frozen ai-treader-llm validate-numeric-input examples/numeric-v1/input-manifest.json
	uv run --frozen ai-treader-llm validate-numeric-dataset examples/numeric-v1/dataset-manifest.json
	uv run --frozen ai-treader-llm validate-alpha examples/numeric-v1/forecast.json --request examples/numeric-v1/request.json --input examples/numeric-v1/input-manifest.json

check-core:
	python3 scripts/backlog.py
	$(MAKE) test
	$(MAKE) fixtures

check: check-core
	$(MAKE) test-numeric
