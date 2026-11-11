# DriftCheck report: openminion 0.1.20

- Docs: https://www.openminion.com/docs/
- Generated: 2026-11-11 07:31 UTC, model `ollama/qwen2.5:7b`, 1828 s
- Claims checked: **1776** (407 CLI commands, 34 Python blocks, 425 inline API references, 910 links)
- Static mismatches: 11 → agent verdicts: **3 confirmed drift**, 7 false positive, 0 need a human, 1 errors
- Since last run: 10 new, 0 still open, 0 fixed

## Confirmed drift

| Where | Doc says | Category | Why | Suggested fix |
| --- | --- | --- | --- | --- |
| `docs__guides__scheduled-tasks.md:98` | openminion cron tick | stale_command | The documentation suggests `openminion cron tick` as a valid command, but `cli_help` shows no such subcommand. The `tick` function in the code is used internally for status updates and debugging, not as a standalone command. | remove or rewrite the passage; the installed version has no equivalent |
| `docs__guides__observability.md:17` | `openminion.modules.telemetry.otel_export.OpenTelemetryTraceExporter` | stale_import_path | The documentation at line 17 of docs__guides__observability.md specifies `openminion.modules.telemetry.otel_export.OpenTelemetryTraceExporter`, but the code has no attribute or submodule `otel_export`. The correct import path is `openminion.modules.telemetry.export.otel.OpenTelemetryTraceExporter` as defined at `openminion/modules/telemetry/export/otel.py:130`. | use `openminion.modules.telemetry.export.otel.OpenTelemetryTraceExporter` |
| `docs__reference__cli-commands.md:584` | openminion cron tick | stale_command | The documentation for `openminion cron` in `docs__reference__cli-commands.md` at line 584 claims `tick` is a subcommand, but `cli_help` shows no such subcommand exists. The `tick` references found in the source code are related to status updates and not a standalone `cron` subcommand. | remove or rewrite the passage; the installed version has no equivalent |

## Needs a human

| Where | Doc says | Category | Why | Suggested fix |
| --- | --- | --- | --- | --- |

## False positives filtered by the agent

| Where | Doc says | Category | Why | Suggested fix |
| --- | --- | --- | --- | --- |
| `docs__guides__sessions-and-history.md:105` | `openminion.token_usage.v1` | not_an_api_reference | The documentation claims that the JSON response uses the `openminion.token_usage.v1` envelope, but the `openminion` package does not have an attribute named `token_usage`. The closest available symbol is `subagent`, which is not related to `token_usage`. | none |
| `docs__guides__observability.md:57` | `openminion.token_usage.v1` | not_an_api_reference | `openminion.token_usage.v1` is used as a string literal in the code to define a schema version and emit the raw envelope. This aligns with the documentation. | none |
| `docs__guides__observability.md:66` | `openminion.turn_cost.v1` | not_an_api_reference | The documented `openminion.turn_cost.v1` is used as a name or value, not as an import path. It appears in `openminion/modules/telemetry/trace/turn_cost.py` at line 17 as a schema version string. | none |
| `docs__guides__observability.md:87` | `openminion.turn_cost.v1` | not_an_api_reference | The document states `openminion.turn_cost.v1` but the code has no attribute or submodule named `turn_cost`. The string `openminion.turn_cost.v1` is used as a schema version in the code. | none |
| `docs__unicode-animatio.md:33` | `openminion.cli.animation_providers` | not_an_api_reference | The `openminion.cli.animation_providers` entry point is defined in the file `openminion/cli/presentation/animation/registry.py` but `openminion.cli` module does not have an `animation_providers` attribute or submodule. It is likely an external package entry point. | none |
| `docs__reference__cli-commands.md:642` | `openminion.token_usage.v1` | not_an_api_reference | The documentation mentions `openminion.token_usage.v1`, but the code does not have an attribute or submodule named `token_usage`. The string `openminion.token_usage.v1` is used as a literal name or value, likely indicating a schema or constant. | none |
| `docs__reference__openminion-api.md:370` | `openminion.eval` | not_an_api_reference | The documentation claims `openminion.eval` exists, but the static checker and source code search indicate it does not. | none |

## Agent errors

- `docs__guides__skills-and-retrieval.md:107` no submit_facts call; reply was: 'driftcheck: I could not safely update the task conditions. Please restate the current task and its required conditions.'

## Agent tool calls

- `docs__guides__sessions-and-history.md:105`: pack:doc_context(docs__guides__sessions-and-history.md:105), pack:python_symbol(openminion.token_usage.v1), pack:grep_source('token_usage.v1'), submit_facts(doc_means='name_or_identifier', exists=False)
- `docs__guides__skills-and-retrieval.md:107`: pack:doc_context(docs__guides__skills-and-retrieval.md:107), pack:cli_help('skill'), pack:grep_source('learning-observation-list')
- `docs__guides__scheduled-tasks.md:98`: pack:doc_context(docs__guides__scheduled-tasks.md:98), pack:cli_help('cron'), pack:grep_source('tick'), submit_facts(doc_means='cli_command', exists=False)
- `docs__guides__observability.md:17`: pack:doc_context(docs__guides__observability.md:17), pack:python_symbol(openminion.modules.telemetry.otel_export.OpenTelemetryTraceExporter), pack:grep_source('otel_export.OpenTelemetryTraceExporter'), grep_source('otel_export.OpenTelemetryTraceExporter'), python_symbol(openminion.modules.telemetry.otel_export.OpenTelemetryTraceExporter), submit_facts(doc_means='import_path', exists=False)
- `docs__guides__observability.md:57`: pack:doc_context(docs__guides__observability.md:57), pack:python_symbol(openminion.token_usage.v1), pack:grep_source('token_usage.v1'), grep_source('token_usage.v1'), python_symbol(openminion.token_usage.v1), read_source(openminion/modules/telemetry/usage/contracts.py:1-40), submit_facts(doc_means='name_or_identifier', exists=True)
- `docs__guides__observability.md:66`: pack:doc_context(docs__guides__observability.md:66), pack:python_symbol(openminion.turn_cost.v1), pack:grep_source('turn_cost.v1'), submit_facts(doc_means='name_or_identifier', exists=False)
- `docs__guides__observability.md:87`: pack:doc_context(docs__guides__observability.md:87), pack:python_symbol(openminion.turn_cost.v1), pack:grep_source('turn_cost.v1'), submit_facts(doc_means='name_or_identifier', exists=False)
- `docs__unicode-animatio.md:33`: pack:doc_context(docs__unicode-animatio.md:33), pack:python_symbol(openminion.cli.animation_providers), pack:grep_source('cli.animation_providers'), grep_source('openminion.cli.animation_providers'), python_symbol(openminion.cli.animation_providers), read_source(openminion/cli/presentation/animation/registry.py:1-40), submit_facts(doc_means='name_or_identifier', exists=False)
- `docs__reference__cli-commands.md:642`: pack:doc_context(docs__reference__cli-commands.md:642), pack:python_symbol(openminion.token_usage.v1), pack:grep_source('token_usage.v1'), submit_facts(doc_means='name_or_identifier', exists=False)
- `docs__reference__cli-commands.md:584`: pack:doc_context(docs__reference__cli-commands.md:584), pack:cli_help('cron'), pack:grep_source('tick'), submit_facts(doc_means='cli_command', exists=False)
- `docs__reference__openminion-api.md:370`: pack:doc_context(docs__reference__openminion-api.md:370), pack:python_symbol(openminion.eval), pack:grep_source('openminion.eval'), submit_facts(doc_means='name_or_identifier', exists=False)
