"""Pull checkable claims out of Markdown docs: fenced code blocks, inline API references, relative links."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

PY_LANGS = {"python", "py", "python3", "pycon"}
SHELL_LANGS = {"bash", "sh", "shell", "console", "zsh", "powershell", "ps1", "pwsh", "text", ""}

FENCE = re.compile(r"^(?P<indent>[ \t]*)(?P<fence>`{3,}|~{3,})(?P<lang>[^\s`]*)")
INLINE_REF = re.compile(r"`(?P<ref>[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+)(?P<call>\(\))?`")
LINK = re.compile(r"\[[^\]]*\]\((?P<target>[^)\s]+)(?:\s+\"[^\"]*\")?\)")


@dataclass
class Block:
    doc: str
    line: int  # 1-based line of the opening fence
    lang: str
    code: str


@dataclass
class InlineRef:
    doc: str
    line: int
    ref: str
    is_call: bool


@dataclass
class Link:
    doc: str
    line: int
    target: str


@dataclass
class DocClaims:
    doc: str
    blocks: list[Block] = field(default_factory=list)
    refs: list[InlineRef] = field(default_factory=list)
    links: list[Link] = field(default_factory=list)


def extract(path: Path, root: Path) -> DocClaims:
    rel = path.relative_to(root).as_posix()
    claims = DocClaims(doc=rel)
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    i = 0
    while i < len(lines):
        m = FENCE.match(lines[i])
        if m:
            fence, lang, start = m.group("fence"), m.group("lang").lower(), i
            body: list[str] = []
            i += 1
            while i < len(lines) and not lines[i].lstrip().startswith(fence):
                body.append(lines[i])
                i += 1
            indent = len(m.group("indent"))
            code = "\n".join(b[indent:] if b[:indent].strip() == "" else b for b in body)
            claims.blocks.append(Block(rel, start + 1, lang, code))
            i += 1
            continue
        for rm in INLINE_REF.finditer(lines[i]):
            claims.refs.append(InlineRef(rel, i + 1, rm.group("ref"), bool(rm.group("call"))))
        for lm in LINK.finditer(lines[i]):
            claims.links.append(Link(rel, i + 1, lm.group("target")))
        i += 1
    return claims


def iter_docs(root: Path, targets: list[str]) -> list[Path]:
    out: list[Path] = []
    for t in targets:
        p = (root / t).resolve()
        if p.is_dir():
            out.extend(sorted(p.rglob("*.md")))
        elif p.suffix.lower() == ".md" and p.exists():
            out.append(p)
    return out
