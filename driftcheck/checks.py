"""Deterministic checks: each one turns a doc claim into PASS or a concrete mismatch with evidence.

Nothing here executes doc code. Python snippets are parsed with `ast` and compared with the installed
package by introspection; CLI lines are walked through the real argparse tree; links are resolved on disk.
"""

from __future__ import annotations

import argparse
import ast
import dataclasses
import importlib
import inspect
import re
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .extract import PY_LANGS, SHELL_LANGS, Block, DocClaims, InlineRef, Link


@dataclass
class Mismatch:
    kind: str  # broken_link, missing_anchor, missing_symbol, bad_call, missing_attribute, cli_unknown_command, cli_unknown_option, syntax
    doc: str
    line: int
    claim: str  # what the doc says, verbatim-ish
    evidence: str  # what the installed package / repo actually has

    @property
    def key(self) -> str:
        return f"{self.kind}|{self.doc}|{self.claim}"


# ---------------------------------------------------------------- links

def _slug(heading: str) -> str:
    s = heading.strip().lower()
    s = re.sub(r"<[^>]+>", "", s)
    s = re.sub(r"[`*_~\[\]()]", lambda m: "_" if m.group(0) == "_" else "", s)
    s = re.sub(r"[^\w\- ]", "", s)
    return s.replace(" ", "-")


def anchors_of(md: Path) -> set[str]:
    seen: dict[str, int] = {}
    out: set[str] = set()
    in_fence = False
    for line in md.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            in_fence = not in_fence
            continue
        m = re.match(r"^#{1,6}\s+(.*?)\s*#*\s*$", line)
        if m and not in_fence:
            base = _slug(m.group(1))
            n = seen.get(base, 0)
            seen[base] = n + 1
            out.add(base if n == 0 else f"{base}-{n}")
        for a in re.findall(r"<a\s+(?:name|id)=\"([^\"]+)\"", line):
            out.add(a)
    return out


def check_link(link: Link, root: Path) -> Mismatch | None:
    t = link.target
    if re.match(r"^[a-z][a-z0-9+.-]*:", t, re.I) or t.startswith("//"):
        return None  # external URL, mailto, etc.
    path_part, _, anchor = t.partition("#")
    doc_path = root / link.doc
    target = doc_path if not path_part else (doc_path.parent / path_part).resolve()
    if not target.exists():
        return Mismatch("broken_link", link.doc, link.line, t, f"{target.relative_to(root.resolve()).as_posix() if target.is_relative_to(root.resolve()) else target} does not exist")
    if anchor and target.suffix.lower() == ".md":
        if anchor.lower() not in anchors_of(target):
            near = sorted(a for a in anchors_of(target) if a[:6] == anchor.lower()[:6])[:3]
            hint = f"; closest: {', '.join(near)}" if near else ""
            return Mismatch("missing_anchor", link.doc, link.line, t, f"no heading with anchor #{anchor} in {target.name}{hint}")
    return None


# ---------------------------------------------------------------- python symbols

class _Inst:
    def __init__(self, cls: type) -> None:
        self.cls = cls


def _class_attrs(cls: type) -> set[str]:
    names = set(dir(cls))
    for klass in inspect.getmro(cls):
        names |= set(getattr(klass, "__annotations__", {}))
        if dataclasses.is_dataclass(klass):
            names |= {f.name for f in dataclasses.fields(klass)}
        names |= set(getattr(klass, "model_fields", {}) or {})
        try:
            names |= set(re.findall(r"self\.(\w+)\s*[:=]", inspect.getsource(klass)))
        except (OSError, TypeError):
            pass
    return names


def _return_class(func: Any) -> type | None:
    ann = inspect.signature(func).return_annotation
    if ann is inspect.Signature.empty:
        return None
    if isinstance(ann, str):
        base = ann.strip("'\"").split("[", 1)[0].strip()
        ann = getattr(inspect.getmodule(func), base, None)
        if ann is None:
            return None
    ann = getattr(ann, "__origin__", ann)
    if ann is Any or ann is object:
        return None  # untyped return: we know nothing about the result
    return ann if inspect.isclass(ann) else None


def _call_problem(func: Any, call: ast.Call, drop_self: bool) -> str | None:
    if any(isinstance(a, ast.Starred) for a in call.args) or any(k.arg is None for k in call.keywords):
        return None
    try:
        sig = inspect.signature(func)
    except (TypeError, ValueError):
        return None
    params = list(sig.parameters.values())
    if drop_self and params:
        params = params[1:]
    sig = sig.replace(parameters=params)
    try:
        sig.bind_partial(*[None] * len(call.args), **{k.arg: None for k in call.keywords})
    except TypeError as exc:
        accepted = ", ".join(p.name for p in params if p.kind not in (p.VAR_POSITIONAL, p.VAR_KEYWORD))
        return f"{exc}; accepted parameters: {accepted}"
    return None


def check_python_block(block: Block, package: str) -> list[Mismatch]:
    out: list[Mismatch] = []
    src = block.code
    if block.lang == "pycon" or src.lstrip().startswith(">>>"):
        src = "\n".join(l[4:] for l in src.splitlines() if l.startswith((">>> ", "... ")))
    try:
        tree = ast.parse(src)
    except SyntaxError as exc:
        if "..." in src or "<" in src:
            return []  # deliberately elided snippet
        return [Mismatch("syntax", block.doc, block.line + (exc.lineno or 0), (exc.text or "").strip(), f"SyntaxError: {exc.msg}")]

    env: dict[str, Any] = {}

    def line_of(node: ast.AST) -> int:
        return block.line + getattr(node, "lineno", 1)

    def text_of(node: ast.AST) -> str:
        return (ast.get_source_segment(src, node) or "").split("\n")[0][:160]

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.split(".")[0] == package and node.level == 0:
            try:
                mod = importlib.import_module(node.module)
            except Exception as exc:  # noqa: BLE001 - any import failure is evidence
                out.append(Mismatch("missing_symbol", block.doc, line_of(node), f"from {node.module} import ...", f"import failed: {type(exc).__name__}: {exc}"))
                continue
            for alias in node.names:
                if alias.name == "*":
                    continue
                if hasattr(mod, alias.name):
                    env[alias.asname or alias.name] = getattr(mod, alias.name)
                else:
                    try:
                        env[alias.asname or alias.name] = importlib.import_module(f"{node.module}.{alias.name}")
                    except Exception:  # noqa: BLE001
                        out.append(Mismatch("missing_symbol", block.doc, line_of(node), f"from {node.module} import {alias.name}", f"{node.module} has no attribute or submodule {alias.name!r}"))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] == package:
                    try:
                        mod = importlib.import_module(alias.name)
                        env[alias.asname or alias.name.split(".")[0]] = mod if alias.asname else importlib.import_module(package)
                    except Exception as exc:  # noqa: BLE001
                        out.append(Mismatch("missing_symbol", block.doc, line_of(node), f"import {alias.name}", f"import failed: {exc}"))

    def resolve(node: ast.AST, report: bool) -> Any:
        if isinstance(node, ast.Name):
            return env.get(node.id)
        if isinstance(node, ast.Attribute):
            base = resolve(node.value, report)
            if base is None:
                return None
            if isinstance(base, _Inst):
                if node.attr not in _class_attrs(base.cls):
                    if report:
                        out.append(Mismatch("missing_attribute", block.doc, line_of(node), text_of(node), f"{base.cls.__module__}.{base.cls.__qualname__} has no attribute {node.attr!r}"))
                    return None
                static = inspect.getattr_static(base.cls, node.attr, None)
                if inspect.isfunction(static):
                    return ("method", base.cls, node.attr)
                return None
            if inspect.ismodule(base) or inspect.isclass(base):
                if not hasattr(base, node.attr):
                    if report and (getattr(base, "__module__", None) or getattr(base, "__name__", "")).startswith(package):
                        out.append(Mismatch("missing_symbol", block.doc, line_of(node), text_of(node), f"{getattr(base, '__qualname__', getattr(base, '__name__', base))} has no attribute {node.attr!r}"))
                    return None
                return getattr(base, node.attr)
            return None
        if isinstance(node, ast.Call):
            target = resolve(node.func, report)
            if target is None:
                return None
            if isinstance(target, tuple) and target[0] == "method":
                _, cls, name = target
                func = getattr(cls, name)
                static = inspect.getattr_static(cls, name)
                drop = not isinstance(static, (staticmethod, classmethod))
                problem = _call_problem(func, node, drop_self=drop)
                if problem and report:
                    out.append(Mismatch("bad_call", block.doc, line_of(node), text_of(node), f"{cls.__qualname__}.{name}: {problem}"))
                rc = _return_class(func)
                return _Inst(rc) if rc else None
            if inspect.isclass(target):
                problem = _call_problem(target, node, drop_self=False)
                if problem and report:
                    out.append(Mismatch("bad_call", block.doc, line_of(node), text_of(node), f"{target.__qualname__}(): {problem}"))
                return _Inst(target)
            if callable(target):
                problem = _call_problem(target, node, drop_self=False)
                if problem and report:
                    out.append(Mismatch("bad_call", block.doc, line_of(node), text_of(node), f"{getattr(target, '__qualname__', target)}(): {problem}"))
                rc = _return_class(target) if not inspect.isbuiltin(target) else None
                return _Inst(rc) if rc else None
        return None

    # bind names in source order, then check every expression once
    stmts = sorted((n for n in ast.walk(tree) if isinstance(n, (ast.Assign, ast.With, ast.AnnAssign))), key=lambda n: n.lineno)
    for st in stmts:
        if isinstance(st, ast.With):
            for item in st.items:
                if isinstance(item.optional_vars, ast.Name):
                    v = resolve(item.context_expr, report=False)
                    if v is not None:
                        env[item.optional_vars.id] = v
        else:
            targets = st.targets if isinstance(st, ast.Assign) else [st.target]
            if st.value is not None:
                v = resolve(st.value, report=False)
                for t in targets:
                    if isinstance(t, ast.Name) and v is not None:
                        env[t.id] = v

    checked: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Call, ast.Attribute)) and id(node) not in checked:
            for sub in ast.walk(node):
                checked.add(id(sub))
            resolve(node, report=True)
    # de-duplicate (same claim reported via nested walks)
    seen: set[str] = set()
    uniq = []
    for m in out:
        if m.key + str(m.line) not in seen:
            seen.add(m.key + str(m.line))
            uniq.append(m)
    return uniq


def check_inline_ref(ref: InlineRef, package: str) -> Mismatch | None:
    root = importlib.import_module(package)
    parts = ref.ref.split(".")
    if parts[0] == package:
        obj: Any = root
        parts = parts[1:]
    elif hasattr(root, parts[0]) and parts[0][0].isupper():
        obj = getattr(root, parts[0])
        parts = parts[1:]
    else:
        return None  # not an API reference we can resolve (e.g. result.text, file names)
    walked = []
    for p in parts:
        if not hasattr(obj, p):
            try:
                if inspect.ismodule(obj):
                    obj = importlib.import_module(f"{obj.__name__}.{p}")
                    walked.append(p)
                    continue
            except Exception:  # noqa: BLE001
                pass
            if inspect.isclass(obj) and p in _class_attrs(obj):
                return None
            owner = ".".join([ref.ref.split(".")[0], *walked])
            return Mismatch("missing_symbol", ref.doc, ref.line, f"`{ref.ref}{'()' if ref.is_call else ''}`", f"{owner} has no attribute {p!r}")
        obj = getattr(obj, p)
        walked.append(p)
    if ref.is_call and not callable(obj):
        return Mismatch("missing_symbol", ref.doc, ref.line, f"`{ref.ref}()`", f"{ref.ref} exists but is not callable ({type(obj).__name__})")
    return None


# ---------------------------------------------------------------- CLI

_VALUELESS = (
    argparse._StoreTrueAction, argparse._StoreFalseAction, argparse._StoreConstAction,
    argparse._AppendConstAction, argparse._CountAction, argparse._HelpAction, argparse._VersionAction,
)


def _subparsers(p: argparse.ArgumentParser) -> argparse._SubParsersAction | None:
    for a in p._actions:
        if isinstance(a, argparse._SubParsersAction):
            return a
    return None


def cli_commands_in(block: Block, prog: str) -> list[tuple[int, list[str]]]:
    """Find `prog ...` invocations in a shell block, including inside $(...) and after env assignments."""
    out: list[tuple[int, list[str]]] = []
    lines = block.code.splitlines()
    joined: list[tuple[int, str]] = []
    buf, start = "", 0
    for i, raw in enumerate(lines):
        line = raw.rstrip()
        if not buf:
            start = i
        if line.endswith("\\") or line.endswith("`"):
            buf += line[:-1] + " "
            continue
        joined.append((start, buf + line))
        buf = ""
    if buf:
        joined.append((start, buf))
    # the program must start a command: line start, after $( or a shell operator, optionally after VAR=value prefixes
    pat = re.compile(rf"(?:^|\$\(|&&|\|\||[;|])\s*(?:[A-Za-z_]\w*=\S*\s+)*{re.escape(prog)}(?=\s|$)")
    for idx, line in joined:
        s = re.sub(r"^\s*(\$|>|PS>|PS [^>]*>)\s+", "", line)
        if s.lstrip().startswith("#"):
            continue
        for m in pat.finditer(s):
            rest = s[m.end():]
            rest = re.split(r"\)\s*\"?|\s\|\s|\s\|\||&&|;|\s#\s", rest)[0]
            try:
                tokens = shlex.split(rest, posix=True)
            except ValueError:
                tokens = rest.split()
            out.append((block.line + 1 + idx, tokens))
    return out


def check_cli(tokens: list[str], prog: str, parser_factory: Callable[[str | None], argparse.ArgumentParser]) -> str | None:
    root = parser_factory(None)
    # find the first subcommand token after root options
    i, selected = 0, None
    sub = _subparsers(root)
    while i < len(tokens):
        t = tokens[i]
        if t in ("-h", "--help"):
            return None
        if t.startswith("-") and t != "-":
            name = t.split("=", 1)[0]
            act = root._option_string_actions.get(name)
            if act is None:
                return f"`{prog}` has no option {name}"
            i += 1 if ("=" in t or isinstance(act, _VALUELESS) or act.nargs == 0) else 2
            continue
        if sub and t in sub.choices:
            selected = t
        elif sub and not t.startswith("$") and re.fullmatch(r"[a-z][a-z0-9-]*", t):
            return f"`{prog}` has no subcommand {t!r}; available: {', '.join(sorted(sub.choices))}"
        break
    if selected is None:
        return None
    parser = parser_factory(selected)
    cur = _subparsers(parser).choices[selected]  # type: ignore[union-attr]
    path = [prog, selected]
    i += 1
    positional_seen = False
    while i < len(tokens):
        t = tokens[i]
        if t in ("-h", "--help"):
            return None
        if t.startswith("-") and t != "-" and not re.fullmatch(r"-\d+(\.\d+)?", t):
            name = t.split("=", 1)[0]
            act = cur._option_string_actions.get(name) or parser._option_string_actions.get(name)
            if act is None:
                opts = sorted(o for o in cur._option_string_actions if o.startswith("--"))
                return f"`{' '.join(path)}` has no option {name}; available: {', '.join(opts)}"
            if "=" in t or isinstance(act, _VALUELESS) or act.nargs == 0:
                i += 1
            elif act.nargs in ("?",):
                i += 2 if i + 1 < len(tokens) and not tokens[i + 1].startswith("-") else 1
            elif act.nargs in ("*", "+"):
                i += 1
                while i < len(tokens) and not tokens[i].startswith("-"):
                    i += 1
            else:
                i += 1 + (act.nargs if isinstance(act, argparse.Action) and isinstance(act.nargs, int) else 1)
            continue
        s = _subparsers(cur)
        if s and t in s.choices:
            cur = s.choices[t]
            path.append(t)
        elif s and not positional_seen and re.fullmatch(r"[a-z][a-z0-9-]*", t) and not _has_leading_positional(cur):
            return f"`{' '.join(path)}` has no subcommand {t!r}; available: {', '.join(sorted(s.choices))}"
        else:
            positional_seen = True
        i += 1
    return None


def _has_leading_positional(p: argparse.ArgumentParser) -> bool:
    for a in p._actions:
        if isinstance(a, argparse._SubParsersAction):
            return False
        if not a.option_strings:
            return True
    return False


def scan_doc(claims: DocClaims, root: Path, package: str, prog: str | None,
             parser_factory: Callable[[str | None], argparse.ArgumentParser] | None) -> tuple[list[Mismatch], dict[str, int]]:
    stats = {"links": 0, "refs": 0, "python_blocks": 0, "cli_commands": 0}
    out: list[Mismatch] = []
    for link in claims.links:
        stats["links"] += 1
        m = check_link(link, root)
        if m:
            out.append(m)
    for ref in claims.refs:
        m = check_inline_ref(ref, package)
        if m is not None:
            out.append(m)
        stats["refs"] += 1
    for block in claims.blocks:
        if block.lang in PY_LANGS:
            stats["python_blocks"] += 1
            out.extend(check_python_block(block, package))
        elif block.lang in SHELL_LANGS and prog and parser_factory:
            for line, tokens in cli_commands_in(block, prog):
                stats["cli_commands"] += 1
                problem = check_cli(tokens, prog, parser_factory)
                if problem:
                    out.append(Mismatch("cli_unknown_option" if "no option" in problem else "cli_unknown_command",
                                        block.doc, line, " ".join([prog, *tokens])[:200], problem))
    return out, stats
