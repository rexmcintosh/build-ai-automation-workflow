from __future__ import annotations
import argparse
import sys
from pathlib import Path

from .config import load_panels, get_api_key, Settings, truncate
from .venice import VeniceClient
from .engine import run_panel
from .router import pick_panel
from .synthesize import synthesize
from .render import render_markdown, render_terminal


def _build(panels_path=None):
    settings, panels = load_panels(panels_path)
    client = VeniceClient(get_api_key(), timeout=settings.timeout)
    return settings, panels, client


def _gather_context(question: str, files: list[str], cap: int) -> str:
    parts = [question] if question else []
    for fp in files or []:
        if fp == "-":
            parts.append("--- stdin ---\n" + sys.stdin.read())
        else:
            parts.append(f"--- {fp} ---\n" + Path(fp).read_text(errors="ignore"))
    return truncate("\n\n".join(parts), cap)


def _run(context, panel_name, settings, panels, client, rigor, fmt):
    if panel_name is None:
        panel_name = pick_panel(context, panels, client,
                                router_model=settings.router_model,
                                default=settings.default_panel)
    panel = panels[panel_name]
    rigor = rigor or panel.default_rigor
    results = run_panel(panel, context, client)
    syn = synthesize(context, results, client, chair_model=settings.chair_model)
    render = render_markdown if fmt == "md" else render_terminal
    print(f"[panel: {panel_name} · rigor: {rigor}]\n")
    print(render(context[:120], syn, results, rigor=rigor))
    return 0


def main(argv=None, *, _settings: Settings = None, _panels=None, _client=None) -> int:
    p = argparse.ArgumentParser(prog="council")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("ask", help="ask the council a question")
    a.add_argument("question")
    a.add_argument("--panel"); a.add_argument("--file", action="append")
    a.add_argument("--rigor", choices=["daily", "deep"]); a.add_argument("--format", default="term")
    a.add_argument("--panels")

    r = sub.add_parser("review", help="review a file / dir / diff")
    r.add_argument("path", nargs="?")
    r.add_argument("--diff", action="store_true")
    r.add_argument("--panel", default="code-review")
    r.add_argument("--rigor", choices=["daily", "deep"]); r.add_argument("--format", default="term")
    r.add_argument("--panels")

    sub.add_parser("panels", help="list councils").add_argument("--panels", nargs="?")

    args = p.parse_args(argv)

    if _settings is not None:
        settings, panels, client = _settings, _panels, _client
    else:
        settings, panels, client = _build(getattr(args, "panels", None))

    if args.cmd == "panels":
        for name, panel in panels.items():
            seats = ", ".join(m.name for m in panel.members)
            print(f"{name:14} {panel.description}\n{'':14} seats: {seats}")
        return 0

    if args.cmd == "ask":
        ctx = _gather_context(args.question, args.file, settings.byte_cap)
        return _run(ctx, args.panel, settings, panels, client, args.rigor, args.format)

    if args.cmd == "review":
        import subprocess
        if args.diff:
            text = subprocess.run(["git", "diff"], capture_output=True, text=True).stdout
        elif args.path == "-" or args.path is None:
            text = sys.stdin.read()
        else:
            pth = Path(args.path)
            text = "\n\n".join(f"--- {f} ---\n{f.read_text(errors='ignore')}"
                               for f in (pth.rglob("*") if pth.is_dir() else [pth]) if f.is_file())
        ctx = truncate(f"Review this:\n\n{text}", settings.byte_cap)
        return _run(ctx, args.panel, settings, panels, client, args.rigor, args.format)

    return 1
