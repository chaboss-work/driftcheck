"""The OpenMinion part.

For each static mismatch:
1. an investigator `Agent` with read-only tools gets a deterministic evidence pack, may call up to three more
   tools, and writes short notes;
2. a judge `subagent` records its conclusion by calling `submit_facts(...)`; the verdict is then derived from those
   facts by code, not chosen by the model;
3. for confirmed drift, a reporter `subagent` records a GitHub-issue draft with `submit_issue(...)`.

Why tool calls instead of `output_type`: on qwen2.5 7B the closure step sometimes rewrote a valid JSON answer into a
shorter, invalid one (upstream issue #720), and the freshness verifier sometimes replaced it with a refusal.
Tool-call arguments are schema-checked by OpenMinion and are not rewritten.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from openminion import Agent, ProviderError, TurnTimeoutError, subagent

from . import tools as T
from .checks import Mismatch

STATIC_TASK = ("This is a static code-reading task about files on disk. It does not depend on dates, news or "
               "live data; answer only from the material and tool output.")
TOOL_BUDGET = 3  # investigator tool calls per finding; the tools refuse politely after that

INVESTIGATOR_INSTRUCTIONS = f"""You check one documentation claim against the source code of a Python package.
{STATIC_TASK}
An evidence pack is provided. You may call up to 3 tools, then answer: grep_source for literal strings,
python_symbol for dotted paths, cli_help for CLI commands, read_source to read code around a hit.
Answer in at most 6 short bullet points:
- how the doc uses the text: as something to import, as a command to run, or only as a name/identifier
  (event or schema name such as pkg.x.v1, entry-point group, config key, placeholder);
- what the code has, with file:line;
- if the documented thing is missing, the working command or import path the code does have, if any."""

JUDGE_INSTRUCTIONS = f"""You record facts about one documentation finding by calling the submit_facts tool exactly once.
{STATIC_TASK}
doc_means:
  "import_path" - the doc tells readers to import or call it in Python;
  "cli_command" - the doc tells readers to run it in a shell;
  "name_or_identifier" - it is only a name the code uses as a string (schema/event version like
     pkg.token_usage.v1, entry-point group, config key, log field), even if it looks like a dotted path;
  "unclear" - none of the above is clear.
exists_as_documented: true only if the code has it exactly as the doc says.
working_alternative: the correct import path or command found in the code, or "none".
Examples:
- doc "uses the `openminion.token_usage.v1` envelope", code TOKEN_USAGE_SCHEMA_VERSION = "openminion.token_usage.v1"
  -> doc_means="name_or_identifier", exists_as_documented=true
- doc "run `tool sync`", cli_help says 'sync' is not a subcommand, grep finds sync only in another program's CLI
  -> doc_means="cli_command", exists_as_documented=false, working_alternative="the other program's command"
After calling submit_facts, reply with the single word: done"""

REPORTER_INSTRUCTIONS = f"""You write a short GitHub issue for a confirmed documentation drift and record it by calling
submit_issue exactly once. {STATIC_TASK}
title: under 90 characters. body: Markdown with sections Summary, Where, Steps to reproduce, Expected, Actual,
Suggested fix, Environment. Use only the facts given. No greetings. After calling submit_issue, reply: done"""


class Facts(BaseModel):
    doc_means: Literal["import_path", "cli_command", "name_or_identifier", "unclear"]
    exists_as_documented: bool
    working_alternative: str
    explanation: str = Field(description="one or two sentences")
    evidence: str = Field(description="file:line references")


class IssueDraft(BaseModel):
    title: str
    body: str


_CATEGORY = {"cli_unknown_command": "stale_command", "cli_unknown_option": "stale_option",
             "missing_symbol": "stale_import_path", "missing_attribute": "missing_api", "bad_call": "wrong_signature",
             "broken_link": "broken_link", "missing_anchor": "broken_link", "syntax": "other"}


class Verdict(BaseModel):
    verdict: Literal["confirmed_drift", "false_positive", "needs_human"]
    category: str
    explanation: str
    evidence: str
    suggested_fix: str
    facts: Facts

    guardrail: str = ""
    source: str = "agent"  # "agent" (model facts + guardrails) or "signals" (model failed, deterministic signal only)

    @classmethod
    def derive(cls, m: Mismatch, f: Facts, sig: "Signals | None" = None, known_fix: str | None = None) -> "Verdict":
        sig = sig or Signals()
        if f.doc_means == "name_or_identifier":
            v, cat = "false_positive", "not_an_api_reference"
        elif f.exists_as_documented or f.doc_means == "unclear":
            # the static checker proved it is missing as written; disagreement means a human should look
            v, cat = "needs_human", _CATEGORY.get(m.kind, "other")
        else:
            v, cat = "confirmed_drift", _CATEGORY.get(m.kind, "other")
        guard = ""
        # guardrails: the model may not overrule a strong deterministic signal; conflicts go to a human
        if v == "confirmed_drift" and sig.literal and not sig.defined_at:
            v, guard = "needs_human", "model says drift, but the exact text is a string value in the code"
        if v == "false_positive" and (sig.defined_at or sig.other_entry_point):
            v, cat = "needs_human", _CATEGORY.get(m.kind, "other")
            guard = "model says not an API, but the name exists elsewhere in the code"
        alt = f.working_alternative.strip().strip("`")
        if v == "false_positive":
            fix = "none"
        elif known_fix:
            fix = f"use `{known_fix}`"
        elif _looks_like_code(alt):
            fix = f"use `{alt}`"
        elif v == "confirmed_drift":
            fix = "remove or rewrite the passage; the installed version has no equivalent"
        else:
            fix = "none"
        return cls(verdict=v, category=cat, explanation=f.explanation, evidence=f.evidence, suggested_fix=fix,
                   facts=f, guardrail=guard)


def _looks_like_code(alt: str) -> bool:
    """A command or import path, not prose like 'None of the subcommands match'."""
    if not alt or alt.lower().startswith(("none", "no ", "n/a", "not ")) or len(alt) > 120:
        return False
    return bool(re.fullmatch(r"[\w.\-/:]+(?:\s+[\w.\-/<>=:\"'\[\]]+){0,8}", alt))


@dataclass
class Triage:
    mismatch: Mismatch
    verdict: Verdict | None
    error: str | None
    tool_calls: list[str]
    seconds: float
    notes: str = ""
    issue: IssueDraft | None = None

    def to_json(self) -> dict:
        return {
            "mismatch": asdict(self.mismatch),
            "verdict": self.verdict.model_dump() if self.verdict else None,
            "notes": self.notes,
            "error": self.error,
            "tool_calls": self.tool_calls,
            "seconds": round(self.seconds, 1),
            "issue": self.issue.model_dump() if self.issue else None,
        }


def _call(fn, *args):
    target = getattr(fn, "__wrapped__", None) or fn
    return target(*args)


def _source_files():
    return sorted(T.CTX.package_dir.rglob("*.py"))


def _grep_files(needles: list[str], limit: int = 50) -> list[tuple[Path, int, str]]:
    hits = []
    for f in _source_files():
        try:
            for n, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if any(x in line for x in needles):
                    hits.append((f, n, line.strip()))
                    if len(hits) >= limit:
                        return hits
        except OSError:
            continue
    return hits


def _rel(f: Path) -> str:
    return f.relative_to(T.CTX.package_dir.parent).as_posix()


def _module_of(f: Path) -> str:
    parts = list(f.relative_to(T.CTX.package_dir.parent).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _console_scripts() -> list[tuple[str, str]]:
    import importlib.metadata as md
    try:
        eps = md.distribution(T.CTX.package).entry_points
    except md.PackageNotFoundError:
        return []
    return [(e.name, e.value) for e in eps if e.group == "console_scripts"]


@dataclass
class Signals:
    literal: str | None = None            # exact text appears as a quoted string in the code
    defined_at: str | None = None         # the final name is defined in another module
    other_entry_point: str | None = None  # the CLI subcommand belongs to another console script

    def lines(self) -> list[str]:
        out = []
        if self.literal:
            out.append(f"SIGNAL literal-string: {self.literal}")
        if self.defined_at:
            out.append(f"SIGNAL defined-elsewhere: {self.defined_at}")
        if self.other_entry_point:
            out.append(f"SIGNAL other-entry-point: {self.other_entry_point}")
        return out


def _script_has_subcommand(value: str, sub: str) -> bool:
    """Build the console script's own argparse parser in-process (no execution) and look for the subcommand."""
    import argparse
    import importlib
    import inspect
    try:
        mod = importlib.import_module(value.split(":")[0])
    except Exception:  # noqa: BLE001
        return False
    for name, fn in inspect.getmembers(mod, inspect.isfunction):
        if "parser" not in name.lower() or fn.__module__ != mod.__name__:
            continue
        try:
            if any(p.default is inspect.Parameter.empty for p in inspect.signature(fn).parameters.values()):
                continue
            parser = fn()
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(parser, argparse.ArgumentParser):
            continue
        stack = [parser]
        while stack:
            cur = stack.pop()
            for a in cur._actions:
                if isinstance(a, argparse._SubParsersAction):
                    if sub in a.choices:
                        return True
                    stack.extend(a.choices.values())
    return False


def compute_signals(m: Mismatch) -> tuple[Signals, str | None]:
    """Deterministic hints plus, when certain, the corrected command or import path."""
    sig, fix = Signals(), None
    if m.kind in ("missing_symbol", "missing_attribute"):
        claim = m.claim.strip("`() ")
        lit = _grep_files([f'"{claim}"', f"'{claim}'"], limit=5)
        if lit:
            f, n, _ = lit[0]
            sig.literal = (f"the exact text {claim!r} appears as a quoted string at {_rel(f)}:{n} "
                           f"({len(lit)} place(s)); the code uses it as a name or value, not as an import path")
        last = claim.split(".")[-1]
        if re.fullmatch(r"[A-Z][A-Za-z0-9]{3,}|[a-z][a-z0-9]*_[a-z0-9_]{3,}", last):
            defs = _grep_files([f"class {last}(", f"class {last}:", f"def {last}("], limit=5)
            if defs:
                f, n, _ = defs[0]
                mod = _module_of(f)
                sig.defined_at = f"{last} is defined at {_rel(f)}:{n}, so it is importable as {mod}.{last}"
                fix = f"{mod}.{last}"
    elif m.kind == "cli_unknown_command":
        bad = re.search(r"no subcommand '([\w-]+)'", m.evidence)
        if bad:
            sub = bad.group(1)
            files = {f for f, _, _ in _grep_files([f'"{sub}"', f"'{sub}'"], limit=20)}
            mods = sorted(_module_of(f) for f in files)
            for name, value in sorted(_console_scripts(), key=lambda e: not e[0].endswith("ctl")):
                if name == T.CTX.prog:
                    continue
                ep_mod = value.split(":")[0]
                ep_pkg = ep_mod.rsplit(".", 1)[0]
                if (ep_pkg.count(".") >= 2 and any(mm == ep_mod or mm.startswith(ep_pkg + ".") for mm in mods)
                        and _script_has_subcommand(value, sub)):
                    sig.other_entry_point = (f"'{sub}' is a subcommand of the console script `{name}` ({value}), "
                                             f"checked in its own argparse parser; `{T.CTX.prog}` does not have it")
                    tail = m.claim.split(sub, 1)[1].strip()
                    fix = f"{name} {sub} {tail}".strip()
                    break
    return sig, fix


def evidence_pack(m: Mismatch) -> str:
    """Deterministic first look, so a small model starts from facts instead of guessing."""
    parts = [f"Doc text around the claim:\n{_call(T.doc_context, m.doc, m.line, 4)}"]
    sig, _ = compute_signals(m)
    if sig.lines():
        parts.append("Deterministic signals:\n" + "\n".join(sig.lines()))
    if m.kind.startswith("cli_"):
        words = [w for w in m.claim.split()[1:] if not w.startswith("-")][:1]
        parts.append(f"cli_help('{words[0] if words else ''}'):\n{_call(T.cli_help, words[0] if words else '')}")
        bad = re.search(r"no (?:subcommand|option) '?([\w-]+)'?", m.evidence)
        if bad:
            parts.append(f"grep_source('{bad.group(1)}'):\n{_call(T.grep_source, bad.group(1), 8)}")
    if m.kind in ("missing_symbol", "missing_attribute"):
        dotted = m.claim.strip("`()")
        parts.append(f"python_symbol('{dotted}'):\n{_call(T.python_symbol, dotted)}")
        tail = ".".join(dotted.split(".")[-2:])
        parts.append(f"grep_source('{tail}'):\n{_call(T.grep_source, tail, 8)}")
    return "\n\n".join(parts)


def _mismatch_text(m: Mismatch) -> str:
    return (f"Candidate mismatch (kind={m.kind})\ndoc: {m.doc}\nline: {m.line}\n"
            f"doc says: {m.claim}\nstatic checker evidence: {m.evidence}")


def _facts_from_text(text: str) -> Facts | None:
    """Fallback when the model wrote the facts as JSON text instead of calling submit_facts."""
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        return Facts.model_validate(json.loads(m.group(0)))
    except (ValueError, ValidationError):
        return None


_DOC_MEANS_SYNONYMS = {
    "import": "import_path", "python": "import_path", "api": "import_path", "module": "import_path",
    "command": "cli_command", "cli": "cli_command", "shell": "cli_command",
    "name": "name_or_identifier", "identifier": "name_or_identifier", "entry_point": "name_or_identifier",
    "entrypoint": "name_or_identifier", "event": "name_or_identifier", "schema": "name_or_identifier",
    "config": "name_or_identifier", "string": "name_or_identifier",
}


def _normalize_doc_means(value: str) -> str:
    v = value.strip().lower().replace("-", "_").replace(" ", "_")
    if v in ("import_path", "cli_command", "name_or_identifier", "unclear"):
        return v
    for key, mapped in _DOC_MEANS_SYNONYMS.items():
        if key in v:
            return mapped
    return "unclear"


def _run_judge(judge: Agent, material: str, timeout_seconds: float) -> tuple[Facts | None, str | None]:
    last_err = None
    for attempt in range(3):
        T.SUBMITTED.pop("facts", None)
        prompt = material if attempt == 0 else material + "\n\nYou must call submit_facts now."
        text = judge.run(prompt, timeout_seconds=timeout_seconds).text
        raw = T.SUBMITTED.get("facts")
        if raw is not None:
            raw = dict(raw, doc_means=_normalize_doc_means(str(raw.get("doc_means", ""))))
            try:
                return Facts.model_validate(raw), None
            except ValidationError as exc:
                last_err = f"submit_facts arguments invalid: {exc.errors()[0]['msg']}"
                continue
        facts = _facts_from_text(text)
        if facts:
            return facts, None
        last_err = f"no submit_facts call; reply was: {text[:200]!r}"
    return None, last_err


def triage_all(mismatches: list[Mismatch], *, agent_id: str | None, config_path: str | None, session_id: str,
               timeout_seconds: float = 240, write_issues: bool = True, log=print) -> list[Triage]:
    results: list[Triage] = []
    with Agent(
        name="driftcheck-investigator",
        agent_id=agent_id,
        config_path=config_path,
        instructions=INVESTIGATOR_INSTRUCTIONS,
        tools=list(T.ALL_TOOLS),
        forced_tools=["grep_source"],  # not enforced on Ollama (no tool_choice); the tool budget bounds the loop
        session_id=session_id,
    ) as investigator:
        judge = subagent(investigator, name="driftcheck-judge", instructions=JUDGE_INSTRUCTIONS,
                         tools=[T.submit_facts], timeout_seconds=int(timeout_seconds))
        reporter = subagent(investigator, name="driftcheck-reporter", instructions=REPORTER_INSTRUCTIONS,
                            tools=[T.submit_issue], timeout_seconds=int(timeout_seconds)) if write_issues else None
        for i, m in enumerate(mismatches, 1):
            T.CTX.calls.clear()
            t0 = time.monotonic()
            pack = evidence_pack(m)
            n_pack = len(T.CTX.calls)
            verdict, error, notes = None, None, ""
            try:
                T.start_investigation(TOOL_BUDGET)
                try:
                    notes = investigator.run(f"{_mismatch_text(m)}\n\nEvidence pack:\n{pack}\n\n{STATIC_TASK} Investigate.",
                                             timeout_seconds=timeout_seconds).text
                finally:
                    T.end_investigation()
                material = f"{_mismatch_text(m)}\n\nEvidence pack:\n{pack}\n\nInvestigator notes:\n{notes}\n\n{STATIC_TASK}"
                facts, error = _run_judge(judge, material, timeout_seconds)
                if facts:
                    sig, known_fix = compute_signals(m)
                    verdict = Verdict.derive(m, facts, sig, known_fix)
            except TurnTimeoutError as exc:
                error = f"turn timeout: {exc}"
            except ProviderError as exc:
                error = f"provider error: {exc.code}: {exc.message}"
            if verdict is None:
                sig, known_fix = compute_signals(m)
                if known_fix and (sig.defined_at or sig.other_entry_point):
                    f = Facts(doc_means="cli_command" if m.kind.startswith("cli_") else "import_path",
                              exists_as_documented=False, working_alternative=known_fix,
                              explanation=f"Agent did not finish ({error}); decided from the deterministic signal: "
                                          f"{(sig.defined_at or sig.other_entry_point)}.",
                              evidence=(sig.defined_at or sig.other_entry_point or "")[:300])
                    verdict = Verdict.derive(m, f, sig, known_fix).model_copy(update={"source": "signals"})
            calls = [f"pack:{c}" for c in T.CTX.calls[:n_pack]] + T.CTX.calls[n_pack:]
            tr = Triage(m, verdict, error, calls, time.monotonic() - t0, notes=notes)
            if reporter and verdict and verdict.verdict == "confirmed_drift":
                T.SUBMITTED.pop("issue", None)
                try:
                    facts_txt = (f"{_mismatch_text(m)}\nverdict: {verdict.model_dump_json()}\n"
                                 f"environment: {T.CTX.package} {_version()} installed from PyPI")
                    reporter.run(facts_txt, timeout_seconds=timeout_seconds)
                    if "issue" in T.SUBMITTED:
                        tr.issue = IssueDraft.model_validate(T.SUBMITTED["issue"])
                except (TurnTimeoutError, ProviderError, ValidationError) as exc:
                    tr.error = (tr.error or "") + f" reporter failed: {str(exc)[:200]}"
            used = sum(1 for c in calls if not c.startswith("pack:") and not c.startswith("submit_"))
            log(f"[{i}/{len(mismatches)}] {m.kind} {m.doc}:{m.line} -> "
                f"{verdict.verdict if verdict else 'ERROR'} ({tr.seconds:.0f}s, {used} investigator tool calls)")
            results.append(tr)
    return results


def _version() -> str:
    import importlib.metadata as md
    try:
        return md.version(T.CTX.package)
    except md.PackageNotFoundError:
        return "unknown"
