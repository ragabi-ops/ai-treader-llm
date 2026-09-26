.PHONY: setup test check fixtures
setup:
	uv sync --frozen --python 3.12

test:
	uv run --frozen python -m unittest discover -s tests -v

fixtures:
	uv run --frozen ai-treader-llm validate-analysis examples/analysis.json --context examples/context.json
	uv run --frozen ai-treader-llm validate-dataset examples/samples.jsonl
	uv run --frozen ai-treader-llm evaluate examples/samples.jsonl examples/predictions.jsonl

check: test fixtures
