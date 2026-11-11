"""Read-only OpenMinion tools the triage agent uses to investigate one doc/code mismatch.

All tools are confined to the installed package directory and the mirrored docs; none execute doc code.
"""

from __future__ import annotations

import argparse
import difflib
import importlib
import inspect
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Literal

from openminion import tool

MAX_OUT = 3500


@dataclass
class Context:
    package: str = "openminion"
    package_dir: Path = Path(".")
    docs_root: Path = Path(".")
    prog: str | None = None
    parser_factory: Callable[[str | None], argparse.ArgumentParser] | None = None
    calls: list[str] = field(default_factory=list)  # audit trail of tool calls for the report
    budget: int = 0  # max agent tool calls per investigation (0 = unlimited)
    used: int = 0


CTX = Context()


def configure(package: str, docs_root: Path, prog: str | None, parser_factory) -> None:
    mod = importlib.import_module(package)
    CTX.package = package
    CTX.package_dir = Path(mod.__file__).resolve().parent
    CTX.docs_root = docs_root.resolve()
    CTX.prog = prog
    CTX.parser_factory = parser_factory


def _clip(s: str) -> str:
    return s if len(s) <= MAX_OUT else s[:MAX_OUT] + f"\n... [{len(s) - MAX_OUT} more chars cut]"


BUDGET_DONE = ("Tool budget for this finding is used up. Do not call more tools. "
               "Write your bullet-point answer now from the evidence you already have.")


def _log(name: str, arg: str) -> str | None:
    """Record the call; return a stop message instead of running the tool once the budget is spent."""
    if CTX.budget and CTX.used >= CTX.budget:
        CTX.calls.append(f"{name}({arg}) [refused: budget]")
        return BUDGET_DONE
    CTX.used += 1
    CTX.calls.append(f"{name}({arg})")
    return None


def start_investigation(budget: int) -> None:
    CTX.budget, CTX.used = budget, 0


def end_investigation() -> None:
    CTX.budget, CTX.used = 0, 0


@tool(min_scope="READ_ONLY", idempotent=True)
def doc_context(doc: str, line: int, radius: int = 6) -> str:
    """Show the documentation lines around a claim. doc is the doc file name from the finding, line is 1-based."""
    if (stop := _log("doc_context", f"{doc}:{line}")):
        return stop
    p = (CTX.docs_root / doc).resolve()
    if not p.is_relative_to(CTX.docs_root) or not p.exists():
        return f"no such doc: {doc}"
    lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    lo, hi = max(0, line - 1 - radius), min(len(lines), line + radius)
    return _clip("\n".join(f"{i + 1:5}| {lines[i]}" for i in range(lo, hi)))


@tool(min_scope="READ_ONLY", idempotent=True)
def grep_source(text: str, max_hits: int = 15) -> str:
    """Search the installed package source for a literal string (case-sensitive). Returns path:line: code lines."""
    if (stop := _log("grep_source", repr(text))):
        return stop
    if not text.strip():
        return "empty search text"
    hits: list[str] = []
    for f in sorted(CTX.package_dir.rglob("*.py")):
        try:
            for n, l in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if text in l:
                    hits.append(f"{f.relative_to(CTX.package_dir.parent).as_posix()}:{n}: {l.strip()[:160]}")
                    if len(hits) >= max_hits:
                        return _clip("\n".join(hits) + f"\n(stopped at {max_hits} hits)")
        except OSError:
            continue
    return _clip("\n".join(hits)) if hits else f"no occurrences of {text!r} in {CTX.package} source"


@tool(min_scope="READ_ONLY", idempotent=True)
def read_source(path: str, start: int = 1, end: int = 40) -> str:
    """Read lines start..end (1-based, inclusive, at most 80 lines) of a package source file, e.g. openminion/cli/commands/cron.py."""
    if (stop := _log("read_source", f"{path}:{start}-{end}")):
        return stop
    p = (CTX.package_dir.parent / path).resolve()
    if not p.is_relative_to(CTX.package_dir) or not p.is_file():
        return f"no such package file: {path}"
    lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    start, end = max(1, start), min(len(lines), end, start + 79)
    return _clip("\n".join(f"{i:5}| {lines[i - 1]}" for i in range(start, end + 1)))


@tool(min_scope="READ_ONLY", idempotent=True)
def cli_help(command: str) -> str:
    """Show the real argparse help for a CLI command path such as 'cron' or 'skill' or 'agent status' (no program name)."""
    if (stop := _log("cli_help", repr(command))):
        return stop
    if not CTX.parser_factory:
        return "no CLI configured"
    words = command.split()
    if words and CTX.prog and words[0] == CTX.prog:
        words = words[1:]  # models often include the program name
    if not words:
        return CTX.parser_factory(None).format_help()
    try:
        parser = CTX.parser_factory(words[0])
    except Exception as exc:  # noqa: BLE001
        return f"cannot build parser for {words[0]!r}: {exc}"
    cur: argparse.ArgumentParser = parser
    for w in words:
        sub = next((a for a in cur._actions if isinstance(a, argparse._SubParsersAction)), None)
        if sub is None or w not in sub.choices:
            choices = sorted(sub.choices) if sub else []
            return f"'{w}' is not a subcommand of '{cur.prog}'. Available: {', '.join(choices) or '(none)'}"
        cur = sub.choices[w]
    return _clip(cur.format_help())


@tool(min_scope="READ_ONLY", idempotent=True)
def python_symbol(dotted: str) -> str:
    """Resolve a dotted Python path like openminion.modules.telemetry.OpenTelemetryTraceExporter; report where it is defined or the closest existing names."""
    if (stop := _log("python_symbol", dotted)):
        return stop
    parts = dotted.strip("`()").split(".")
    try:
        obj = importlib.import_module(parts[0])
    except Exception as exc:  # noqa: BLE001
        return f"cannot import {parts[0]}: {exc}"
    walked = [parts[0]]
    for p in parts[1:]:
        nxt = getattr(obj, p, None)
        if nxt is None and inspect.ismodule(obj):
            try:
                nxt = importlib.import_module(f"{obj.__name__}.{p}")
            except Exception:  # noqa: BLE001
                nxt = None
        if nxt is None:
            names = [n for n in dir(obj) if not n.startswith("_")]
            if inspect.ismodule(obj) and getattr(obj, "__path__", None):
                names += [c.stem if c.is_file() else c.name for c in Path(obj.__path__[0]).iterdir() if not c.name.startswith("_")]
            close = difflib.get_close_matches(p, sorted(set(names)), n=5, cutoff=0.4)
            return f"{'.'.join(walked)} has no attribute or submodule {p!r}. Closest names: {', '.join(close) or '(none)'}"
        obj = nxt
        walked.append(p)
    where = ""
    try:
        f = inspect.getsourcefile(obj)
        _, ln = inspect.getsourcelines(obj)
        where = f" defined at {Path(f).resolve().relative_to(CTX.package_dir.parent).as_posix()}:{ln}"
    except (TypeError, OSError, ValueError):
        pass
    sig = ""
    if callable(obj):
        try:
            sig = f" signature {inspect.signature(obj)}"
        except (TypeError, ValueError):
            pass
    return _clip(f"{dotted} exists: {type(obj).__name__}{where}{sig}")


ALL_TOOLS = [doc_context, grep_source, read_source, cli_help, python_symbol]


# ---------------------------------------------------------------- submission tools
# Structured results travel as tool-call arguments: they are schema-checked by OpenMinion and are not rewritten by
# the closure step that can shorten a final JSON answer (see upstream issue #720).

SUBMITTED: dict[str, dict] = {}


@tool(min_scope="READ_ONLY", idempotent=True)
def submit_facts(doc_means: Literal["import_path", "cli_command", "name_or_identifier", "unclear"],
                 exists_as_documented: bool, working_alternative: str, explanation: str,
                 evidence: str) -> str:
    """Record your facts about the finding. doc_means: import_path | cli_command | name_or_identifier | unclear.
    exists_as_documented: true only if the code has it exactly as the doc says. working_alternative: the correct
    command or import path found in the code, or "none". explanation: one or two sentences. evidence: file:line refs."""
    SUBMITTED["facts"] = {"doc_means": doc_means, "exists_as_documented": exists_as_documented,
                          "working_alternative": working_alternative, "explanation": explanation, "evidence": evidence}
    CTX.calls.append(f"submit_facts(doc_means={doc_means!r}, exists={exists_as_documented})")
    return "recorded. Reply with the single word: done"


@tool(min_scope="READ_ONLY", idempotent=True)
def submit_issue(title: str, body: str) -> str:
    """Record a GitHub issue draft: title under 90 characters, body in Markdown."""
    SUBMITTED["issue"] = {"title": title, "body": body}
    CTX.calls.append("submit_issue(...)")
    return "recorded. Reply with the single word: done"
