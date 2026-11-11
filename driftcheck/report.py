"""Report, issue drafts and a run-to-run ledger (new / still open / fixed)."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from .agent import Triage
from .checks import Mismatch


def update_ledger(path: Path, found: list[Mismatch], run_id: str) -> dict[str, list[str]]:
    ledger = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    now_keys = {m.key for m in found}
    status = {"new": [], "still_open": [], "fixed": []}
    for k in sorted(now_keys):
        if k in ledger and ledger[k].get("state") == "open":
            status["still_open"].append(k)
            ledger[k]["last_seen"] = run_id
        else:
            status["new"].append(k)
            ledger[k] = {"first_seen": run_id, "last_seen": run_id, "state": "open"}
    for k, v in ledger.items():
        if v.get("state") == "open" and k not in now_keys:
            v["state"], v["fixed_in"] = "fixed", run_id
            status["fixed"].append(k)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(ledger, indent=1, ensure_ascii=False), encoding="utf-8")
    return status


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60]


def write_report(out: Path, *, source: str, package: str, version: str, stats: dict, triaged: list[Triage],
                 untriaged: list[Mismatch], ledger_status: dict, model: str, seconds: float) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    (out / "issues").mkdir(exist_ok=True)
    confirmed = [t for t in triaged if t.verdict and t.verdict.verdict == "confirmed_drift"]
    fps = [t for t in triaged if t.verdict and t.verdict.verdict == "false_positive"]
    human = [t for t in triaged if t.verdict and t.verdict.verdict == "needs_human"]
    errors = [t for t in triaged if not t.verdict]
    for n, t in enumerate(confirmed, 1):
        if t.issue:
            (out / "issues" / f"{n:02d}-{_slug(t.issue.title)}.md").write_text(
                f"# {t.issue.title}\n\n{t.issue.body}\n", encoding="utf-8")
    (out / "findings.json").write_text(json.dumps({
        "source": source, "package": package, "version": version, "model": model, "stats": stats,
        "ledger": ledger_status, "triaged": [t.to_json() for t in triaged],
        "untriaged": [m.__dict__ for m in untriaged],
    }, indent=1, ensure_ascii=False), encoding="utf-8")

    def row(t: Triage) -> str:
        v = t.verdict
        fix = (v.suggested_fix if v else "").replace("|", "\\|").replace("\n", " ")
        why = (v.explanation if v else t.error or "").replace("|", "\\|").replace("\n", " ")
        src = "" if not v or v.source == "agent" else " *(signal only)*"
        guard = f" Guardrail: {v.guardrail}." if v and v.guardrail else ""
        return (f"| `{t.mismatch.doc}:{t.mismatch.line}` | {t.mismatch.claim[:80].replace('|', '/')} | "
                f"{v.category if v else '-'}{src} | {why}{guard} | {fix} |")

    total_claims = sum(stats.values())
    lines = [
        f"# DriftCheck report: {package} {version}",
        "",
        f"- Docs: {source}",
        f"- Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}, model `{model}`, {seconds:.0f} s",
        f"- Claims checked: **{total_claims}** ({stats.get('cli_commands', 0)} CLI commands, {stats.get('python_blocks', 0)} Python blocks, "
        f"{stats.get('refs', 0)} inline API references, {stats.get('links', 0)} links)",
        f"- Static mismatches: {len(triaged) + len(untriaged)} → agent verdicts: **{len(confirmed)} confirmed drift**, "
        f"{len(fps)} false positive, {len(human)} need a human, {len(errors)} errors",
        f"- Since last run: {len(ledger_status['new'])} new, {len(ledger_status['still_open'])} still open, {len(ledger_status['fixed'])} fixed",
        "",
        "## Confirmed drift",
        "",
        "| Where | Doc says | Category | Why | Suggested fix |",
        "| --- | --- | --- | --- | --- |",
        *[row(t) for t in confirmed],
        "",
        "## Needs a human",
        "",
        "| Where | Doc says | Category | Why | Suggested fix |",
        "| --- | --- | --- | --- | --- |",
        *[row(t) for t in human],
        "",
        "## False positives filtered by the agent",
        "",
        "| Where | Doc says | Category | Why | Suggested fix |",
        "| --- | --- | --- | --- | --- |",
        *[row(t) for t in fps],
    ]
    if errors:
        lines += ["", "## Agent errors", "", *[f"- `{t.mismatch.doc}:{t.mismatch.line}` {t.error}" for t in errors]]
    if untriaged:
        lines += ["", "## Not triaged (static checker only)", "",
                  *[f"- `{m.doc}:{m.line}` {m.kind}: {m.claim} → {m.evidence}" for m in untriaged]]
    lines += ["", "## Agent tool calls", "",
              *[f"- `{t.mismatch.doc}:{t.mismatch.line}`: {', '.join(t.tool_calls) or '(none)'}" for t in triaged]]
    f = out / "report.md"
    f.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return f
