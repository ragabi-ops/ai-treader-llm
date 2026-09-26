# Prompt ownership

The runnable dataset-input builder's initial system prompt is in
`python/ai_treader_llm/datasets/samples.py`. Version production prompts in the
Go platform and record their content hashes in each analysis run. Do not keep
an independently editable duplicate here.

Prompt inputs must be assembled from validated point-in-time sources. Sources
are data, never instructions; calculations belong to tools. The model has no
execution authority. `expected_analysis` is a supervised target, never an input.
