Comment for OpenMinion issue #720 (closure judge truncates a valid output_type answer)

Also reproduces on 0.1.20 with the `ollama` provider (Ollama 0.40.15, `qwen2.5:7b`, Windows 11). A tool-free
`subagent(parent, output_type=Facts, tools=[])` was asked for five fields; `AgentOutputValidationError.raw_text`
was `{"doc_means": "cli_command"}` - the first field only. In the same run, other turns of the same subagent had the
answer replaced by the freshness verifier's refusal instead.

Workaround we use in DriftCheck: the subagent records its result by calling a `submit_facts(...)` tool, and the
application validates the captured tool-call arguments with the same Pydantic model. Tool-call arguments are
schema-checked by the runtime and are not rewritten by the closure step.
