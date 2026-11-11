# Docs site: commands and import paths that do not exist in 0.1.20

## Summary
DriftCheck compared every CLI line, Python snippet, inline API reference and link on
<https://www.openminion.com/docs/> (99 pages) with `openminion==0.1.20` from PyPI. These passages do not match
the installed package (each one is reproducible with `--help` only):

| Page | Doc says | 0.1.20 has |
| --- | --- | --- |
| Use OpenMinion → Scheduled Tasks; Reference → CLI Commands | `openminion cron tick` | `cron` subcommands are `create, status, pause, resume, show, run` (also on `main` and `dev`) |
| Use OpenMinion → Skills and Retrieval | `openminion skill learning-observation-list --agent-id <id>` | `openminion skill` rejects it; the command exists as `skillctl learning-observation-list` (`openminion.modules.skill.cli`) |
| Use OpenMinion → Observability | `openminion.modules.telemetry.otel_export.OpenTelemetryTraceExporter` | `openminion.modules.telemetry.export.otel.OpenTelemetryTraceExporter` (re-exported from `openminion.modules.telemetry`) |
| Home | "What's included in 0.1.8", "Python SDK in 0.1.8" | PyPI ships 0.1.20 |

## Steps to reproduce
```bash
pip install openminion==0.1.20
openminion cron tick --help                       # error: invalid choice: 'tick'
openminion skill learning-observation-list --help # error: invalid choice
skillctl learning-observation-list --help         # works
python -c "import openminion.modules.telemetry.otel_export"   # ModuleNotFoundError
```

## Suggested fix
Update the three passages as in the table, and show the package version the site was built from. The repository
`docs/` folder is clean in our scan (all 144 CLI lines and 100 links resolve), so the site seems to be built from a
different source; a DriftCheck-style static pass (`python -m driftcheck scan --site ... --no-llm`) in the site's
CI would catch these.
