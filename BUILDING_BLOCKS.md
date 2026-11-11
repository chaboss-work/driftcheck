# Building Blocks Tested

OpenMinion 0.1.20 from PyPI, Python 3.12, Windows 11, provider preset `ollama` (Ollama 0.40.15, `qwen2.5:7b`,
RTX 3060 Laptop 6 GB). Each row says what DriftCheck used, what happened, and where to look.

| Building block | How DriftCheck uses it | Result |
| --- | --- | --- |
| `Agent` as a context manager | one investigator agent per scan (`driftcheck/agent.py`) | **Worked.** Runtime is created lazily and closed on exit. First turn ~28 s including model load. |
| `@tool(min_scope="READ_ONLY", idempotent=True)` | five read-only tools (`driftcheck/tools.py`) | **Worked.** Schemas come from annotations and docstrings; the model called `grep_source` correctly when asked. |
| `forced_tools` | `forced_tools=["grep_source"]` on the investigator | **Did not work on Ollama.** Not enforced; a prompt that needs no tool finishes with `tool_calls == 0`. The Ollama adapter has no tool-choice mapping. Issue draft: `upstream-issues/01-...`. With an explicit "call at least one tool" instruction the model then looped on tools until the 300 s turn timeout, so DriftCheck now gives a deterministic evidence pack up front and a per-finding **tool budget** (the tools answer "budget used up, write your answer" after three calls). |
| `output_type=` (Pydantic) | tried for the judge (`Facts`) and the reporter (`IssueDraft`) | **Did not hold up on a 7B model.** (1) With tools and `output_type` in one agent, qwen2.5 7B answered in prose after the tool loop → `AgentOutputValidationError`. (2) In a tool-free judge subagent, the closure step sometimes rewrote the valid JSON into a shorter object such as `{"doc_means": "cli_command"}` (same as upstream #720, here on Ollama), or the freshness verifier replaced it with a refusal. Final design: the judge calls a `submit_facts(...)` tool; its arguments are schema-checked by OpenMinion, not rewritten, and we validate them with the same Pydantic model. The verdict is then derived from the facts in code. |
| `subagent(parent, ..., tools=[decorated tool])` | judge with `[submit_facts]`, reporter with `[submit_issue]` | **Worked** in 0.1.20 (the `TypeError` from #703 is fixed). Bounded by `timeout_seconds`. |
| `AgentOutputValidationError.raw_text` | logged per finding | **Useful.** It showed that the "invalid JSON" was actually the freshness verifier's refusal text, not the model's answer. |
| `TurnTimeoutError`, `ProviderError` | caught per finding | **Worked.** One bad turn never stops a scan of many findings. |
| Sessions / threads | one `session_id` per scan; each `run()` without `thread_id` starts a new thread | **Worked.** Findings do not leak into each other. |
| Project-owned config (`config_path`, `agent_id`) | `.openminion/agents.json`, profile `driftcheck`, created by `openminion --config ... setup --provider ollama --base-url ... --no-chat` | **Worked.** The model lives under `agents.<id>.model_connections`, not a top-level `model` key. |
| Ollama preset `--base-url` | our own Ollama on port 11435 next to an existing one on 11434 | **Worked.** |
| Ollama context size | — | **Missing.** `num_ctx` is never sent; we start Ollama with `OLLAMA_CONTEXT_LENGTH=12288`. Patch ready: `upstream-patches/0001-ollama-forward-num-ctx.patch`. |
| Freshness classifier / verifier (runs on every turn) | not used on purpose | **Got in the way.** On local code-reading prompts it sometimes decided "needs live data" and replaced correct answers (including valid JSON for `output_type`) with a refusal. A one-line "static task, no dates or live data" note in every prompt avoided it. No opt-out exists. Issue draft: `upstream-issues/03-...`. |
| CLI parser (`openminion.cli.parser.base.build_parser(selected_command=...)`) | DriftCheck walks it to verify ~400 documented CLI lines without executing anything | **Worked well.** Lazy sub-parsers are built per command; `allow_abbrev=False` keeps the check exact. |
| Token / call stats (`result.stats`) | timing and cost per finding | **Worked.** A simple one-tool turn: 6 LLM calls, ~15k input tokens (freshness classification, entry, tool step, closure). |

## Bugs and rough edges found (summary)

1. `forced_tools` not enforced on Ollama, silently (`upstream-issues/01`).
2. Ollama `num_ctx` cannot be set (`upstream-issues/02`, patch in `upstream-patches/`).
3. Freshness verifier replaces valid local answers, breaks `output_type`; "answer.." double period
   (`upstream-issues/03`).
4. Docs site drift: `openminion cron tick`, `openminion skill learning-observation-list`, stale
   `otel_export` import path, version banner says 0.1.8 (`upstream-issues/04`).
