.PHONY: setup test check fixtures
setup:
	uv sync --frozen --python 3.12

test:
	uv run --frozen python -m unittest discover -s tests -v

fixtures:
	uv run --frozen ai-treader-llm validate-analysis examples/analysis.json --context examples/context.json
	uv run --frozen ai-treader-llm validate-dataset examples/samples.jsonl
	uv run --frozen ai-treader-llm validate-outcomes examples/samples.jsonl examples/outcomes.jsonl
	uv run --frozen ai-treader-llm validate-manifest examples/dataset-manifest.json
	uv run --frozen ai-treader-llm evaluate examples/samples.jsonl examples/predictions.jsonl
	uv run --frozen ai-treader-llm evaluate-tools examples/tool-call-fixtures.jsonl examples/tool-call-predictions.jsonl
	uv run --frozen ai-treader-llm validate-analysis examples/v2/analysis.json --context examples/v2/context.json
	uv run --frozen ai-treader-llm validate-outcomes examples/v2/samples.jsonl examples/v2/outcomes.jsonl
	uv run --frozen ai-treader-llm validate-manifest examples/v2/dataset-manifest.json --evaluation-boundary 2025-06-01T00:00:00Z

check: test fixtures
