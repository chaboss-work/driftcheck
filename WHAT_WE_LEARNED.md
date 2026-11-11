# What We Learned

Actionable feedback for OpenMinion and Cortensor, from building DriftCheck on `openminion==0.1.20` with a local
qwen2.5 7B model (Ollama 0.40.15, RTX 3060 6 GB, Windows 11). Every item says where we saw it and how to check it.

## Documentation

1. **The docs site does not say which version it describes.** <https://www.openminion.com/docs/> has sections
   "What's included in 0.1.8" and "Python SDK in 0.1.8" while PyPI ships 0.1.20. A builder cannot tell whether a
   page matches what `pip install openminion` gave them. Suggestion: print the package version the site was built
   from in the header, and keep one page per release line.
2. **Example links point at `blob/dev`.** Site pages link source examples on the `dev` branch, while PyPI releases
   come from `main`. When `dev` moves ahead, the linked example and the installed package disagree. Suggestion:
   link to the release tag.
3. **Concrete drift found by DriftCheck** (all reproducible with `--help` only; see `reports/`):
   - `openminion cron tick` is documented (Scheduled Tasks guide, CLI reference) but `cron` has only
     `create, status, pause, resume, show, run` in 0.1.20, `main` and `dev`.
   - `openminion skill learning-observation-list` is documented (Skills and Retrieval guide) but `openminion skill`
     rejects it; the command exists in the separate `skillctl` / `skill` entry point
     (`openminion.modules.skill.cli`, which calls `add_learning_subcommands`).
   - `openminion.modules.telemetry.otel_export.OpenTelemetryTraceExporter` (Observability guide) no longer exists;
     the class is `openminion.modules.telemetry.export.otel.OpenTelemetryTraceExporter`, re-exported from
     `openminion.modules.telemetry`.
4. **The repository docs are in good shape.** 144 CLI lines in `README.md`, `docs/` and `examples/` all resolve
   against the 0.1.20 parser, and all 100 relative links resolve. The drift is in the published site, which seems
   to be built from a different source than `docs/` in the repository.

## SDK and runtime

5. **Structured output in a tool-using turn is fragile on small local models.** With `tools=[...]` and
   `output_type=Verdict` in one `Agent`, qwen2.5 7B answered in prose after its tool calls, so every turn ended in
   `AgentOutputValidationError`. Splitting the work fixed it: an investigator `Agent` with tools and text output,
   then a `subagent(..., output_type=Verdict, tools=[])` judge with no tools. Suggestion: document this pattern, or
   offer an opt-in final "format to schema" step after the tool loop.
6. **Ollama context size is not set by OpenMinion.** We had to start Ollama with `OLLAMA_CONTEXT_LENGTH=12288`;
   with the default window the system prompt plus tool schemas crowd out the conversation. A `num_ctx` option on
   the Ollama preset would make local runs reproducible.
7. **The agent profile has no top-level `model`.** `openminion setup --provider ollama --model qwen2.5:7b` stores
   the model under `agents.<id>.model_connections.<conn>.models`. Tools that read the config to show the active
   model need to know this; a `openminion agent inspect --json` field with the resolved model would help.
8. **`--base-url` on the Ollama preset works** and lets a second Ollama instance run on another port (we kept a
   pre-existing Ollama on 11434 untouched and ran ours on 11435).
