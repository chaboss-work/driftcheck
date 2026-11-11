# DriftCheck

**An OpenMinion agent that checks that documentation still matches the installed code.**

Built for Cortensor Hackathon #5 on the [OpenMinion](https://github.com/OpenMinion/openminion) 0.1 Python SDK
(tested with `openminion==0.1.20`), running on a local model through Ollama.

Builders learn an SDK from its docs. When a doc page tells you to run a command that was renamed, or import a
class from a path that moved, you lose an hour before you suspect the docs. DriftCheck finds those places first:

1. **Static pass (no model):** every CLI line in the docs is walked through the package's real `argparse` tree
   (nothing is executed), every Python snippet is parsed with `ast` and checked against the installed package with
   `inspect` (imports, keyword arguments, result attributes), every inline API reference is resolved, every link
   and anchor is followed.
2. **Agent pass (OpenMinion):** each mismatch goes to an investigator agent with read-only tools
   (`doc_context`, `grep_source`, `read_source`, `cli_help`, `python_symbol`) and a deterministic evidence pack.
   A judge subagent records the facts with a `submit_facts(...)` tool call (how the doc uses the text, whether the
   code has it, the working alternative), and DriftCheck derives the verdict from those facts: *confirmed drift*,
   *false positive* (for example an event name such as `openminion.token_usage.v1` that only looks like an import
   path), or *needs a human*.
3. **Report:** a Markdown report, `findings.json`, one GitHub-issue draft per confirmed drift (written by a
   reporter subagent), and a ledger that marks findings as new, still open or fixed since the previous run.

Nothing is posted anywhere automatically. Issue drafts are files for a human to review.

## Results on the OpenMinion docs (2026-11-11)

Scan of <https://www.openminion.com/docs/> (99 pages) against `openminion==0.1.20` from PyPI, local qwen2.5 7B:
[`reports/site/report.md`](reports/site/report.md), raw data in [`reports/site/findings.json`](reports/site/findings.json).

| | |
| --- | --- |
| Claims checked statically | **1,776** (407 CLI lines, 34 Python blocks, 425 inline API references, 910 links) |
| Static mismatches | 11 |
| Agent verdicts | 3 confirmed drift, 7 false positives filtered, 1 agent error (OpenMinion #719, now covered by a signal-only fallback) |
| Agreement with a manual check | 10 of 10 decided findings |
| Time | ~25 min for the agent pass on an RTX 3060 6 GB (≈2 min per finding, 2-3 model turns each) |

Confirmed drift in the published docs:

- `openminion cron tick` (Scheduled Tasks guide, CLI reference): `cron` has no `tick` in 0.1.20, `main` or `dev`.
- `openminion.modules.telemetry.otel_export.OpenTelemetryTraceExporter` (Observability guide): moved to
  `openminion.modules.telemetry.export.otel.OpenTelemetryTraceExporter`.
- `openminion skill learning-observation-list` (Skills and Retrieval guide): the command exists only in the
  `skillctl` console script (found by the deterministic other-entry-point signal; the model turn hit #719).

False positives the agent filtered: schema versions such as `openminion.token_usage.v1` and
`openminion.turn_cost.v1`, the entry-point group `openminion.cli.animation_providers`, and a sentence that says
`openminion.eval` does *not* exist. The repository's own `docs/` folder had no drift (144 CLI lines, 100 links).

Findings about OpenMinion itself, written up as issue drafts in [`upstream-issues/`](upstream-issues/):
`forced_tools` is not enforced on Ollama; Ollama `num_ctx` cannot be set (patch in
[`upstream-patches/`](upstream-patches/)); the freshness verifier replaces valid answers to local tasks;
#720 (closure step truncates `output_type` JSON) reproduces on Ollama.


## Quick start

```bash
python -m venv .venv
. .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -e ".[test]"

# a local model (no API key, no cost)
ollama pull qwen2.5:7b
OLLAMA_CONTEXT_LENGTH=12288 ollama serve          # OpenMinion does not pass a context size to Ollama

# an OpenMinion agent profile for DriftCheck, stored in the project
openminion --config .openminion/agents.json setup --provider ollama --agent driftcheck \
  --model qwen2.5:7b --base-url http://127.0.0.1:11434 --no-chat

# scan the published OpenMinion docs against the installed package
python -m driftcheck scan --site https://www.openminion.com/docs/ --out reports/site

# or a local checkout with Markdown docs
python -m driftcheck scan --repo ../openminion --docs README.md docs examples --out reports/repo

# static checks only (no model), e.g. in CI
python -m driftcheck scan --site https://www.openminion.com/docs/ --no-llm --out reports/static
```

Tests (static checks against the real installed package, no model needed): `pytest -q`.

## How the OpenMinion SDK is used

| Building block | Where |
| --- | --- |
| `Agent` with decorated `@tool` functions (`min_scope="READ_ONLY"`, `idempotent=True`) | `driftcheck/tools.py`, investigator in `driftcheck/agent.py` |
| `forced_tools` | set on the investigator; not enforced on Ollama, so a per-finding tool budget and an evidence pack keep runs bounded |
| `subagent(..., tools=[...])` | the judge (`submit_facts`) and the reporter (`submit_issue`); arguments validated with Pydantic |
| `output_type=` | tried first; replaced by submission tools after the closure step truncated valid JSON (upstream #720) |
| Sessions and threads | one session per scan; each mismatch runs in its own thread so verdicts do not bleed into each other |
| Project-owned config (`config_path=`, `agent_id=`) | `.openminion/agents.json`, profile `driftcheck` |
| Error contracts | `ProviderError`, `TurnTimeoutError`, `AgentOutputValidationError` are caught per finding; one bad turn never stops the scan |
| Local provider | Ollama preset with a custom `--base-url` |

Details, what worked and what did not: [BUILDING_BLOCKS.md](BUILDING_BLOCKS.md).
Product feedback for OpenMinion and Cortensor: [WHAT_WE_LEARNED.md](WHAT_WE_LEARNED.md).

## Layout

```text
driftcheck/
  extract.py   Markdown -> code blocks, inline API references, links
  web.py       mirror a published MkDocs site into Markdown (cached)
  checks.py    deterministic checks (argparse walk, ast + inspect, links/anchors)
  tools.py     read-only OpenMinion tools for the agent, plus submit_facts / submit_issue
  agent.py     evidence pack, deterministic signals, investigator Agent, judge and reporter subagents, guardrails
  report.py    report.md, findings.json, issue drafts, run-to-run ledger
tests/         27 tests against the installed openminion package (no model needed)
reports/       output of the run above
upstream-issues/, upstream-patches/   what we found in OpenMinion while building this
```

## Disclosure

AI-assisted development: the code was written with an AI coding assistant and reviewed and run by the author.
The agent itself runs on a local open-weights model (qwen2.5 7B via Ollama).

## License

MIT
