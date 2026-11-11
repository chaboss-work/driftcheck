"""DriftCheck CLI: python -m driftcheck scan ..."""

from __future__ import annotations

import argparse
import importlib
import importlib.metadata as md
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from .checks import Mismatch, scan_doc
from .extract import extract, iter_docs
from .web import Fetcher, check_web_link, mirror_site


def _parser_factory(prog: str | None, factory: str | None):
    if not prog or not factory:
        return None
    mod, _, attr = factory.partition(":")
    build = getattr(importlib.import_module(mod), attr)
    return lambda selected: build(selected_command=selected)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="driftcheck", description="Check that docs still match the installed code.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan", help="scan docs, triage mismatches with an OpenMinion agent, write a report")
    src = s.add_mutually_exclusive_group(required=True)
    src.add_argument("--site", help="published MkDocs site URL, e.g. https://www.openminion.com/docs/")
    src.add_argument("--repo", type=Path, help="local checkout with Markdown docs")
    s.add_argument("--docs", nargs="*", default=["README.md", "docs"], help="doc files/dirs inside --repo")
    s.add_argument("--package", default="openminion", help="installed package the docs describe")
    s.add_argument("--prog", default="openminion", help="CLI program name to check in shell blocks ('' to skip)")
    s.add_argument("--cli-parser", default="openminion.cli.parser.base:build_parser",
                   help="module:function that builds the CLI argparse parser (selected_command kwarg)")
    s.add_argument("--agent", default="driftcheck", help="OpenMinion agent id from the config")
    s.add_argument("--config", default=".openminion/agents.json", help="OpenMinion config path")
    s.add_argument("--out", type=Path, default=Path("reports/latest"))
    s.add_argument("--cache", type=Path, default=Path("cache"))
    s.add_argument("--no-llm", action="store_true", help="static checks only, no model calls")
    s.add_argument("--no-issues", action="store_true", help="skip the reporter subagent")
    s.add_argument("--limit", type=int, default=0, help="triage at most N mismatches (0 = all)")
    s.add_argument("--only", nargs="*", default=[], help="triage only these mismatch kinds")
    s.add_argument("--timeout", type=float, default=300)
    a = ap.parse_args(argv)

    t0 = time.monotonic()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    factory = _parser_factory(a.prog or None, a.cli_parser)
    fetcher = Fetcher(a.cache / "html")
    if a.site:
        site_dir = a.cache / "site"
        mapping = mirror_site(a.site, site_dir, fetcher)
        root, docs, source = site_dir.resolve(), list(mapping.values()), a.site
    else:
        root = a.repo.resolve()
        docs, source = iter_docs(root, a.docs), f"{root} ({', '.join(a.docs)})"
    print(f"{len(docs)} doc pages from {source}")

    found: list[Mismatch] = []
    stats: Counter = Counter()
    for d in docs:
        claims = extract(Path(d).resolve(), root)
        ms, st = scan_doc(claims, root, a.package, a.prog or None, factory)
        if a.site:
            for l in claims.links:
                prob = check_web_link(l.target, fetcher, a.site)
                if prob:
                    ms.append(Mismatch("broken_link", claims.doc, l.line, l.target, prob))
        found += ms
        stats.update(st)
    print(f"claims checked: {dict(stats)}; static mismatches: {len(found)} {dict(Counter(m.kind for m in found))}")

    from .report import update_ledger, write_report
    ledger_status = update_ledger(a.out.parent / "ledger.json", found, run_id)
    todo = [m for m in found if not a.only or m.kind in a.only]
    if a.limit:
        todo = todo[: a.limit]
    untriaged = [m for m in found if m not in todo]
    triaged, model = [], "none (static only)"
    if not a.no_llm and todo:
        from .agent import triage_all
        from .tools import configure
        configure(a.package, root, a.prog or None, factory)
        model = _model_name(a.config, a.agent)
        triaged = triage_all(todo, agent_id=a.agent, config_path=a.config, session_id=f"driftcheck-{run_id}",
                             timeout_seconds=a.timeout, write_issues=not a.no_issues)
    else:
        untriaged = found
    try:
        version = md.version(a.package)
    except md.PackageNotFoundError:
        version = "unknown"
    report = write_report(a.out, source=source, package=a.package, version=version, stats=dict(stats),
                          triaged=triaged, untriaged=untriaged, ledger_status=ledger_status, model=model,
                          seconds=time.monotonic() - t0)
    print(f"report: {report}")
    return 0


def _model_name(config: str, agent: str) -> str:
    import json
    try:
        cfg = json.loads(Path(config).read_text(encoding="utf-8"))
        prof = cfg.get("agents", {}).get(agent, {})
        model = prof.get("model")
        if not model:
            conns = prof.get("model_connections", {})
            default = next((c for c in conns.values() if c.get("default")), next(iter(conns.values()), {}))
            model = (default.get("models") or ["?"])[0]
        return f"{prof.get('provider', '?')}/{model}"
    except (OSError, ValueError):
        return "unknown"


if __name__ == "__main__":
    sys.exit(main())
