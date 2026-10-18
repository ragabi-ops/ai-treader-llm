.PHONY: setup test check fixtures shell
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
	uv run --frozen ai-treader-llm validate-source-review examples/data-review-v1/sec-edgar-r11.json
	uv run --frozen ai-treader-llm validate-numeric-input examples/numeric-v1/input-manifest.json
	uv run --frozen ai-treader-llm validate-numeric-dataset examples/numeric-v1/dataset-manifest.json
	uv run --frozen ai-treader-llm validate-alpha examples/numeric-v1/forecast.json --request examples/numeric-v1/request.json --input examples/numeric-v1/input-manifest.json

shell:
	bash -n scripts/bootstrap/*.sh scripts/qualification/*.sh scripts/smoke/*.sh

check:
	python3 scripts/backlog.py
	$(MAKE) shell
	$(MAKE) test
	$(MAKE) fixtures
