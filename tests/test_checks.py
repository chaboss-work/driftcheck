"""Static checks against the real installed openminion package. No model calls."""

from __future__ import annotations

from pathlib import Path

import pytest

from driftcheck.checks import check_cli, check_inline_ref, check_python_block, cli_commands_in, scan_doc
from driftcheck.extract import Block, InlineRef, extract
from openminion.cli.parser.base import build_parser

FACTORY = lambda sel: build_parser(selected_command=sel)  # noqa: E731


def py(code: str) -> list:
    return check_python_block(Block("doc.md", 1, "python", code), "openminion")


def test_valid_sdk_snippet_passes():
    assert py(
        "from openminion import Agent, tool\n"
        "@tool(min_scope='READ_ONLY', idempotent=True)\n"
        "def f(x: str) -> str:\n    return x\n"
        "with Agent(instructions='hi', tools=[f], session_id='s') as agent:\n"
        "    result = agent.run('go', timeout_seconds=30)\n"
        "    print(result.text, result.session_id)\n"
    ) == []


def test_unknown_keyword_is_reported():
    out = py("from openminion import Agent\nAgent(instruction='typo')\n")
    assert [m.kind for m in out] == ["bad_call"]
    assert "instruction" in out[0].evidence and "instructions" in out[0].evidence


def test_unknown_method_keyword_is_reported():
    out = py("from openminion import Agent\nwith Agent() as a:\n    a.run('x', timeout=5)\n")
    assert [m.kind for m in out] == ["bad_call"]


def test_missing_import_is_reported():
    out = py("from openminion import Agnet\n")
    assert out and out[0].kind == "missing_symbol"


def test_missing_result_attribute_is_reported():
    out = py("from openminion import Agent\nwith Agent() as a:\n    r = a.run('x')\n    r.answer\n")
    assert [m.kind for m in out] == ["missing_attribute"]


@pytest.mark.parametrize("cmd,ok", [
    ("setup --provider ollama --no-chat", True),
    ("--dir . --add-dir ../x", True),
    ("agent status --agent-id default", True),
    ("cron tick", False),
    ("setup --bogus", False),
    ("nosuch", False),
])
def test_cli_walk(cmd, ok):
    assert (check_cli(cmd.split(), "openminion", FACTORY) is None) is ok


def test_cli_lines_found_inside_shell_constructs():
    code = 'out="$(openminion \\\n  --config c.json \\\n  room create --name x)"\nFOO=1 openminion run "hi"\npip install openminion\n'
    found = [t for _, t in cli_commands_in(Block("d.md", 1, "bash", code), "openminion")]
    assert found[0][:4] == ["--config", "c.json", "room", "create"]
    assert found[1] == ["run", "hi"]
    assert len(found) == 2  # "pip install openminion" is not an invocation


def test_inline_refs():
    assert check_inline_ref(InlineRef("d.md", 1, "Agent.run_stream", True), "openminion") is None
    bad = check_inline_ref(InlineRef("d.md", 1, "Agent.run_streamz", True), "openminion")
    assert bad and bad.kind == "missing_symbol"
    assert check_inline_ref(InlineRef("d.md", 1, "result.text", False), "openminion") is None  # not resolvable: skipped


def test_links_and_anchors(tmp_path: Path):
    (tmp_path / "a.md").write_text("# Title\n\n## Real Section\n\n[ok](b.md#other) [bad](missing.md) [anchor](#real-section) [x](#nope)\n", encoding="utf-8")
    (tmp_path / "b.md").write_text("# B\n\n## Other\n", encoding="utf-8")
    out, stats = scan_doc(extract(tmp_path / "a.md", tmp_path), tmp_path, "openminion", None, None)
    assert stats["links"] == 4
    assert sorted(m.kind for m in out) == ["broken_link", "missing_anchor"]
