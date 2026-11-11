# Ollama: no way to set the context window (`num_ctx`)

## Summary
The Ollama adapter never sends `options.num_ctx`, so every OpenMinion turn runs with the Ollama server's default
context length. An OpenMinion turn is large (one simple tool turn in our runs used ~15k input tokens across 6 LLM
calls), so with a small default window the system prompt and tool schemas crowd out the conversation, silently.
Users have to restart Ollama with `OLLAMA_CONTEXT_LENGTH=...`, which affects every other client of that server.

## Environment
- openminion 0.1.20 (PyPI), Python 3.12, Windows 11; Ollama 0.40.15, `qwen2.5:7b`

## Steps to reproduce
1. Configure the `ollama` preset and run any turn.
2. Inspect the request body sent to `/api/chat` (or the adapter code): `options` contains only `temperature`,
   `top_p`, `num_predict` and `stop` when set.

## Expected
A per-connection setting, e.g. `provider_config_overrides: {"num_ctx": 16384}`, forwarded as `options.num_ctx`.

## Actual
No such setting; `num_ctx` is never sent.

## Where
`src/openminion/modules/llm/providers/ollama/adapter.py`, payload construction in `OllamaProvider.complete`.

## Proposed fix (small)
Read `num_ctx` from the provider config (positive integer, ignored otherwise) and set `payload["options"]["num_ctx"]`.
A patch with two unit tests in `tests/llm/test_providers_http.py` is ready; happy to open a PR once this is
confirmed in scope.
