# Export boundary — implementation pending

After a validated QLoRA run: load the exact original safetensors revision on CPU,
merge the PEFT adapter, convert with a pinned llama.cpp converter, and quantize to
Q4_K_M. Record base/adapter/converter hashes and evaluate the final GGUF. Never
merge directly into a quantized GGUF or overwrite the active deployment artifact.
No export command is implemented until an actual adapter passes baseline gates.
