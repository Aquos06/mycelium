"""The model gateway (ARCHITECTURE §11): slots, providers, keys, budget, traces.

schemas/        every shape: config (slots, providers), completion (request, result, reply), usage, trace
providers/      one `complete()` per vendor: claude (Anthropic SDK), openai_compat (vLLM, Ollama, OpenAI)
service.py      the bus handlers: budget check -> call -> cost -> trace -> shadow
__main__.py     entrypoint; reads providers.yaml and the key env vars
"""
