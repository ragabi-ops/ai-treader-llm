"""ALPHA03 Chronos-2 CPU batch challenger: pinned weights, zero-shot, no fine-tuning.

Runs in the isolated runtime under runtimes/chronos (its own uv.lock), so the frozen
ALPHA02 code and runtime pins stay unchanged. Only model.py and weights.py import
torch or huggingface_hub; the rest is plain Python and runs in the contract tests.
"""
