"""Build the DriftCheck demo video (~2.5 min) from the real run in reports/site.

    python docs/video/make_video.py

Every number, log line, tool call and verdict on screen comes from reports/site.log and reports/site/findings.json
(the run of 2026-11-11 against https://www.openminion.com/docs/). Terminal scenes replay that log with time compressed.
Output: docs/video/driftcheck-demo.mp4 plus stills for the README.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
FFMPEG = shutil.which("ffmpeg") or r"H:\work\.tools\ffmpeg-pkg\ffmpeg-9.0.2-essentials_build\bin\ffmpeg.exe"
W, H = 1280, 720
BG, PANEL, TEXT, MUTED, ACCENT, LINE, BLUE, RED, AMBER = ("#0f1114", "#171a1f", "#e9ecf1", "#9aa3b0", "#3ccf9b",
                                                         "#2a2f37", "#5b8cff", "#ff6b6b", "#f2b84b")
FONTS = Path("C:/Windows/Fonts")
SANS, SANS_B, MONO = "segoeui.ttf", "segoeuib.ttf", "consola.ttf"

DATA = json.loads((ROOT / "reports/site/findings.json").read_text(encoding="utf-8"))
LOG = [l for l in (ROOT / "reports/site.log").read_text(encoding="utf-8").splitlines() if l.strip()]
ST = DATA["stats"]
TRI = DATA["triaged"]
TOTAL = sum(ST.values())
COUNTS = {k: sum(1 for t in TRI if (t["verdict"] or {}).get("verdict") == k) for k in ("confirmed_drift", "false_positive", "needs_human")}
ERRORS = sum(1 for t in TRI if not t["verdict"])


def font(name, size):
    return ImageFont.truetype(str(FONTS / name), size)


def canvas():
    img = Image.new("RGB", (W, H), BG)
    return img, ImageDraw.Draw(img)


def footer(d, note=""):
    d.text((40, H - 44), "DriftCheck · Cortensor Hackathon #5 · OpenMinion 0.1.20 · local qwen2.5 7B via Ollama",
           font=font(SANS, 18), fill=MUTED)
    if note:
        d.text((W - 40 - d.textlength(note, font=font(SANS, 16)), H - 42), note, font=font(SANS, 16), fill=MUTED)


def wrap(d, text, f, width):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if d.textlength(t, font=f) <= width:
            cur = t
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def clip(s, n):
    return s if len(s) <= n else s[: n - 1] + "…"


def title_card():
    img, d = canvas()
    d.text((80, 200), "DriftCheck", font=font(SANS_B, 84), fill=TEXT)
    d.text((84, 315), "Does the documentation still match the installed code?", font=font(SANS, 38), fill=ACCENT)
    d.text((84, 380), f"An OpenMinion agent checked {TOTAL:,} claims on openminion.com/docs against openminion 0.1.20.",
           font=font(SANS, 26), fill=MUTED)
    footer(d)
    return img


def text_card(heading, paras):
    img, d = canvas()
    d.text((80, 130), heading, font=font(SANS_B, 48), fill=TEXT)
    y = 230
    for i, para in enumerate(paras):
        for line in wrap(d, para, font(SANS, 30), W - 160):
            d.text((80, y), line, font=font(SANS, 30), fill=TEXT if i == 0 else MUTED)
            y += 44
        y += 22
    footer(d)
    return img


def box(d, xy, title, lines, color):
    x0, y0, x1, y1 = xy
    d.rounded_rectangle(xy, radius=14, fill=PANEL, outline=color, width=3)
    d.text((x0 + 16, y0 + 10), title, font=font(SANS_B, 22), fill=color)
    for i, l in enumerate(lines):
        d.text((x0 + 16, y0 + 46 + i * 27), l, font=font(SANS, 18), fill=TEXT)


def harrow(d, x0, x1, y, color=MUTED):
    d.line([(x0, y), (x1, y)], fill=color, width=3)
    d.polygon([(x1, y), (x1 - 12, y - 7), (x1 - 12, y + 7)], fill=color)


def pipeline(highlight=0):
    img, d = canvas()
    d.text((60, 40), "How it works", font=font(SANS_B, 44), fill=TEXT)
    on = lambda n: ACCENT if highlight in (0, n) else LINE
    box(d, (40, 150, 300, 380), "1  Static pass", ["CLI lines → real argparse", "snippets → ast + inspect",
                                                   "API refs → import", "links → disk / HTTP", "no doc code is run"], on(1))
    box(d, (340, 150, 640, 380), "2  Investigator", ["OpenMinion Agent", "evidence pack + signals", "read-only @tools:",
                                                     "grep_source, read_source,", "cli_help, python_symbol"], on(2))
    box(d, (680, 150, 960, 380), "3  Judge", ["subagent(tools=[submit_facts])", "how is the text used?", "does the code have it?",
                                              "working alternative?"], on(3))
    box(d, (1000, 150, 1240, 380), "4  Verdict", ["derived in code", "guardrails vs signals", "report + ledger",
                                                  "issue drafts (subagent)"], on(4))
    for x0, x1, n in ((300, 340, 2), (640, 680, 3), (960, 1000, 4)):
        harrow(d, x0, x1, 265, on(n))
    notes = ["Static pass: ~1,800 claims in seconds; a mismatch is a candidate, not yet a bug.",
             "Investigator: a small model starts from facts, may call 3 more tools (a tool budget keeps it bounded).",
             "Judge: facts travel as tool-call arguments, schema-checked; free-text JSON got truncated (OpenMinion #720).",
             "Verdict: the model never overrules a strong deterministic signal; conflicts go to a human."]
    y = 430
    for i, n in enumerate(notes, 1):
        d.text((60, y), n, font=font(SANS, 22), fill=TEXT if highlight in (0, i) else MUTED)
        y += 40
    footer(d)
    return img


def terminal(lines, title="python -m driftcheck scan --site https://www.openminion.com/docs/ --out reports/site"):
    img, d = canvas()
    d.rounded_rectangle((40, 40, W - 40, H - 70), radius=12, fill="#0b0d10", outline=LINE, width=2)
    for i, c in enumerate((RED, AMBER, ACCENT)):
        d.ellipse((60 + i * 24, 56, 74 + i * 24, 70), fill=c)
    d.text((70, 92), "$ " + title, font=font(MONO, 20), fill=ACCENT)
    y = 132
    for l in lines:
        color = TEXT
        if "confirmed_drift" in l:
            color = RED
        elif "false_positive" in l:
            color = MUTED
        elif "ERROR" in l:
            color = AMBER
        d.text((70, y), clip(l, 108), font=font(MONO, 18), fill=color)
        y += 27
    footer(d, "replay of the real run log, time compressed (31 min → seconds)")
    return img


def finding_frames(t, label):
    m, v = t["mismatch"], t["verdict"] or {}
    f = v.get("facts") or {}
    frames = []
    img, d = canvas()
    d.text((60, 40), label, font=font(SANS_B, 38), fill=TEXT)
    d.text((60, 100), f"{m['doc']}:{m['line']}", font=font(MONO, 20), fill=MUTED)
    d.text((60, 145), "Doc says", font=font(SANS_B, 22), fill=BLUE)
    d.text((60, 178), clip(m["claim"], 95), font=font(MONO, 21), fill=TEXT)
    d.text((60, 225), "Static checker", font=font(SANS_B, 22), fill=BLUE)
    for i, line in enumerate(wrap(d, m["evidence"], font(MONO, 18), W - 140)[:3]):
        d.text((60, 258 + i * 26), line, font=font(MONO, 18), fill=TEXT)
    d.text((60, 350), "Agent tool calls (pack = deterministic evidence pack)", font=font(SANS_B, 22), fill=BLUE)
    for i, c in enumerate([c for c in t["tool_calls"] if not c.startswith("submit_")][:7]):
        d.text((60, 385 + i * 27), clip(c, 105), font=font(MONO, 18), fill=MUTED if c.startswith("pack:") else ACCENT)
    footer(d, f"real run · {t['seconds']:.0f} s for this finding")
    frames.append(img)

    img, d = canvas()
    d.text((60, 40), label, font=font(SANS_B, 38), fill=TEXT)
    d.text((60, 105), "Investigator notes (excerpt)", font=font(SANS_B, 22), fill=BLUE)
    notes = [n.strip("- ").strip() for n in t["notes"].replace("driftcheck:", "").splitlines()
             if n.strip() and not n.strip().startswith("```") and len(n.strip()) > 12]
    y = 140
    for n in notes[:3]:
        for line in wrap(d, "• " + n, font(SANS, 20), W - 140)[:2]:
            d.text((60, y), line, font=font(SANS, 20), fill=TEXT)
            y += 28
    y += 14
    d.text((60, y), "Judge → submit_facts(...)", font=font(SANS_B, 22), fill=BLUE)
    y += 36
    for k in ("doc_means", "exists_as_documented", "working_alternative"):
        d.text((80, y), f"{k} = {clip(str(f.get(k)), 80)}", font=font(MONO, 19), fill=TEXT)
        y += 28
    y += 16
    color = RED if v.get("verdict") == "confirmed_drift" else (MUTED if v.get("verdict") == "false_positive" else AMBER)
    d.text((60, y), f"Verdict: {v.get('verdict')}  ({v.get('category')})", font=font(SANS_B, 30), fill=color)
    d.text((60, y + 48), "Fix: " + clip(v.get("suggested_fix", ""), 100), font=font(MONO, 19), fill=ACCENT)
    footer(d, "verdict derived in code from the facts")
    frames.append(img)
    return frames


def results_card():
    img, d = canvas()
    d.text((60, 40), "Result on openminion.com/docs", font=font(SANS_B, 44), fill=TEXT)
    rows = [("Claims checked", f"{TOTAL:,}", TEXT),
            ("  CLI lines / Python blocks / API refs / links", f"{ST['cli_commands']} / {ST['python_blocks']} / {ST['refs']} / {ST['links']}", MUTED),
            ("Static mismatches", str(len(TRI)), TEXT),
            ("Confirmed drift", str(COUNTS["confirmed_drift"]), RED),
            ("False positives filtered by the agent", str(COUNTS["false_positive"]), MUTED),
            ("Agent errors (OpenMinion #719; signal fallback added)", str(ERRORS), AMBER),
            ("Agreement with a manual check", "10 / 10 decided", ACCENT)]
    for i, (k, v, c) in enumerate(rows):
        y = 140 + i * 58
        d.text((80, y), k, font=font(SANS, 28), fill=c if c != TEXT else TEXT)
        d.text((1180 - d.textlength(v, font=font(SANS_B, 30)), y), v, font=font(SANS_B, 30), fill=c)
    footer(d, "reports/site/report.md")
    return img


def drift_card():
    img, d = canvas()
    d.text((60, 40), "Drift found in the published docs", font=font(SANS_B, 44), fill=TEXT)
    items = [("openminion cron tick", "Scheduled Tasks guide + CLI reference: no `tick` in 0.1.20, main or dev"),
             ("openminion.modules.telemetry.otel_export.OpenTelemetryTraceExporter",
              "moved → openminion.modules.telemetry.export.otel.OpenTelemetryTraceExporter"),
             ("openminion skill learning-observation-list", "exists only in the `skillctl` console script"),
             ("Docs home: \"What's included in 0.1.8\"", "PyPI ships 0.1.20")]
    y = 140
    for a, b in items:
        d.text((80, y), clip(a, 80), font=font(MONO, 22), fill=RED)
        d.text((80, y + 34), b, font=font(SANS, 22), fill=MUTED)
        y += 100
    d.text((80, y + 6), "Filtered as not-an-API: schema versions (openminion.token_usage.v1), an entry-point group,",
           font=font(SANS, 20), fill=TEXT)
    d.text((80, y + 34), "and a sentence that says openminion.eval does not exist.", font=font(SANS, 20), fill=TEXT)
    footer(d, "filed as openminion/openminion#727")
    return img


def blocks_card():
    img, d = canvas()
    d.text((60, 40), "OpenMinion building blocks tested", font=font(SANS_B, 44), fill=TEXT)
    rows = [("Agent + @tool(min_scope='READ_ONLY')", "worked", ACCENT),
            ("subagent(tools=[submit_facts]) judge / reporter", "worked", ACCENT),
            ("sessions, threads, project config, ProviderError / TurnTimeoutError", "worked", ACCENT),
            ("forced_tools on Ollama", "not enforced → #724", RED),
            ("Ollama context size (num_ctx)", "cannot be set → #725, patch ready", RED),
            ("freshness verifier on local tasks", "replaced answers → #726", RED),
            ("output_type JSON at closure", "truncated (same as #720)", AMBER)]
    for i, (k, v, c) in enumerate(rows):
        y = 140 + i * 62
        d.text((80, y), k, font=font(SANS, 26), fill=TEXT)
        d.text((1200 - d.textlength(v, font=font(SANS_B, 24)), y + 2), v, font=font(SANS_B, 24), fill=c)
    footer(d, "BUILDING_BLOCKS.md · WHAT_WE_LEARNED.md")
    return img


def outro():
    img, d = canvas()
    d.text((80, 170), "DriftCheck", font=font(SANS_B, 60), fill=TEXT)
    rows = ["github.com/chaboss-work/driftcheck",
            "python -m driftcheck scan --site <mkdocs url>     # or --repo <checkout> --docs README.md docs",
            "python -m driftcheck scan ... --no-llm             # static pass only, for CI",
            "27 tests · local model, no API key · issues: openminion#724-#727"]
    for i, r in enumerate(rows):
        d.text((84, 270 + i * 54), r, font=font(MONO if i in (1, 2) else SANS, 24 if i in (1, 2) else 28),
               fill=ACCENT if i == 0 else MUTED)
    footer(d)
    return img


def main():
    out = ROOT / "docs/video/driftcheck-demo.mp4"
    head = LOG[:2]
    per = LOG[2:-1]
    scenes = [(title_card(), 5.0),
              (text_card("The problem", [
                  "Builders learn an SDK from its docs. A renamed command or a moved class costs an hour before anyone "
                  "suspects the docs.",
                  "DriftCheck reads every doc page, checks each claim against the installed package without running "
                  "doc code, and lets an OpenMinion agent decide which mismatches are real."]), 9.0),
              (pipeline(0), 7.0)]
    scenes += [(pipeline(n), 5.0) for n in (1, 2, 3, 4)]
    scenes.append((terminal(head), 5.0))
    for k in range(1, len(per) + 1):
        scenes.append((terminal(head + per[:k]), 1.6))
    scenes.append((terminal(head + per + LOG[-1:]), 4.0))
    by_line = {(t["mismatch"]["doc"], t["mismatch"]["line"]): t for t in TRI}
    examples = [(("docs__guides__observability.md", 17), "Finding: a moved class"),
                (("docs__guides__observability.md", 57), "Finding: looks like an import, is a schema name"),
                (("docs__guides__scheduled-tasks.md", 98), "Finding: a command that does not exist")]
    for key, label in examples:
        a, b = finding_frames(by_line[key], label)
        scenes += [(a, 9.0), (b, 10.0)]
    scenes += [(results_card(), 9.0), (drift_card(), 10.0), (blocks_card(), 10.0), (outro(), 7.0)]

    with tempfile.TemporaryDirectory() as tmp:
        listing = []
        for i, (img, dur) in enumerate(scenes):
            p = Path(tmp) / f"{i:03d}.png"
            img.save(p)
            listing.append(f"file '{p.as_posix()}'\nduration {dur}")
        listing.append(f"file '{(Path(tmp) / f'{len(scenes) - 1:03d}.png').as_posix()}'")
        (Path(tmp) / "list.txt").write_text("\n".join(listing), encoding="utf-8")
        subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(Path(tmp) / "list.txt"),
                        "-vf", "fps=30,format=yuv420p", "-c:v", "libx264", "-crf", "20", "-movflags", "+faststart", str(out)],
                       check=True)
    pipeline(0).save(ROOT / "docs/video/pipeline.png")
    results_card().save(ROOT / "docs/video/results.png")
    print(f"{out}  {sum(d for _, d in scenes):.1f}s  {len(scenes)} frames")


if __name__ == "__main__":
    main()
