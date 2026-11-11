"""Signals and verdict derivation against the real installed openminion package. No model calls."""

from __future__ import annotations

from pathlib import Path

import pytest

from driftcheck import tools as T
from driftcheck.agent import Facts, Signals, Verdict, _normalize_doc_means, compute_signals
from driftcheck.checks import Mismatch
from openminion.cli.parser.base import build_parser


@pytest.fixture(autouse=True, scope="module")
def _configure():
    T.configure("openminion", Path("."), "openminion", lambda s: build_parser(selected_command=s))


def sym(claim: str) -> Mismatch:
    return Mismatch("missing_symbol", "d.md", 1, f"`{claim}`", "missing")


def cli(cmd: str, sub: str, parent: str) -> Mismatch:
    return Mismatch("cli_unknown_command", "d.md", 1, cmd, f"`openminion {parent}` has no subcommand '{sub}'; available: x")


def test_schema_version_is_a_string_literal():
    sig, fix = compute_signals(sym("openminion.token_usage.v1"))
    assert sig.literal and not sig.defined_at and fix is None


def test_moved_class_gets_its_new_import_path():
    sig, fix = compute_signals(sym("openminion.modules.telemetry.otel_export.OpenTelemetryTraceExporter"))
    assert sig.defined_at
    assert fix == "openminion.modules.telemetry.export.otel.OpenTelemetryTraceExporter"


def test_subcommand_of_another_console_script():
    sig, fix = compute_signals(cli("openminion skill learning-observation-list --agent-id <id>",
                                   "learning-observation-list", "skill"))
    assert sig.other_entry_point
    assert fix == "skillctl learning-observation-list --agent-id <id>"


def test_word_that_only_appears_elsewhere_is_not_a_command():
    sig, fix = compute_signals(cli("openminion cron tick", "tick", "cron"))
    assert sig.other_entry_point is None and fix is None


def facts(doc_means: str, exists: bool = False, alt: str = "none") -> Facts:
    return Facts(doc_means=doc_means, exists_as_documented=exists, working_alternative=alt, explanation="e", evidence="f:1")


def test_name_or_identifier_is_false_positive():
    assert Verdict.derive(sym("x.y.v1"), facts("name_or_identifier")).verdict == "false_positive"


def test_model_cannot_call_a_string_literal_drift():
    v = Verdict.derive(sym("x.y.v1"), facts("import_path"), Signals(literal="appears as a string"))
    assert v.verdict == "needs_human" and v.guardrail


def test_model_cannot_dismiss_a_moved_class():
    v = Verdict.derive(sym("a.b.Cls"), facts("name_or_identifier"), Signals(defined_at="Cls at a/c.py:1"), "a.c.Cls")
    assert v.verdict == "needs_human" and v.guardrail


def test_confirmed_drift_uses_the_deterministic_fix():
    v = Verdict.derive(sym("a.b.Cls"), facts("import_path", alt="some prose"), Signals(defined_at="..."), "a.c.Cls")
    assert v.verdict == "confirmed_drift" and v.suggested_fix == "use `a.c.Cls`"


def test_prose_alternative_is_not_offered_as_a_fix():
    v = Verdict.derive(cli("openminion cron tick", "tick", "cron"),
                       facts("cli_command", alt="None of the available subcommands match"))
    assert v.verdict == "confirmed_drift" and v.suggested_fix.startswith("remove or rewrite")


@pytest.mark.parametrize("raw,expected", [("entry_point", "name_or_identifier"), ("CLI command", "cli_command"),
                                          ("import_path", "import_path"), ("whatever", "unclear")])
def test_doc_means_synonyms(raw, expected):
    assert _normalize_doc_means(raw) == expected
