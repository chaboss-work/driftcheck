# Ollama: `forced_tools` is silently not enforced

## Summary
With the `ollama` provider, `Agent(..., forced_tools=["name"])` does not make the model call the tool. The docs
say `forced_tools` "requires that registered tool for the run". On Ollama the run finishes with zero tool calls
and no warning.

## Environment
- openminion 0.1.20 (PyPI), Python 3.12, Windows 11
- Ollama 0.40.15, model `qwen2.5:7b`, provider preset `ollama` with `--base-url`

## Steps to reproduce
```python
from openminion import Agent, tool

@tool(min_scope="READ_ONLY", idempotent=True)
def lookup_order(order_id: str) -> str:
    """Return the current status for one order."""
    return f"order {order_id}: ready"

with Agent(agent_id="ollama-agent", config_path=".openminion/agents.json",
           tools=[lookup_order], forced_tools=["lookup_order"]) as agent:
    result = agent.run("What is 2+2? Answer with one number.")
    print(result.text, result.stats["tool_calls"])
```

## Expected
Either the tool is called (the runtime enforces the forced tool), or the run fails/warns that the provider cannot
force tool choice.

## Actual
`driftcheck: 4`, `stats["tool_calls"] == 0`, `llm_calls == 3`. No warning in the result or logs.

## Where
`src/openminion/modules/llm/providers/ollama/adapter.py`: the native `/api/chat` payload carries `tools` but no
tool-choice field (Ollama's native chat API has none), and `request.tool_choice` is not used anywhere in the
adapter. The OpenAI and Anthropic adapters do map `tool_choice`.

## Suggested fix
Mark tool-choice forcing as unsupported in the Ollama provider behavior profile and, when `forced_tools` is set
for such a provider, either enforce it in the runtime (re-prompt until the forced tool is called, bounded by the
turn budget) or emit a warning in `result.metadata` so applications can tell the requirement was not met.
