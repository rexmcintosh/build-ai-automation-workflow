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
    # Config loads without any network/secret; the client is built lazily so
    # local-only commands (e.g. `panels`) don't require VENICE_API_KEY.
    settings, panels = load_panels(panels_path)
    return settings, panels, None


def _gather_context(question: str, files: list[str], cap: int) -> str:
    parts = [question] if question else []
    for fp in files or []:
        if fp == "-":
            parts.append("--- stdin ---\n" + sys.stdin.read())
        else:
            try:
                parts.append(f"--- {fp} ---\n" + Path(fp).read_text(errors="ignore"))
            except OSError as e:
                print(f"error: cannot read --file {fp}: {e}", file=sys.stderr)
                raise SystemExit(2)
    return truncate("\n\n".join(parts), cap)


def _looks_binary(path: Path) -> bool:
    try:
        with open(path, "rb") as fh:
            return b"\x00" in fh.read(4096)
    except OSError:
        return True


def _read_for_review(path_arg: str, cap: int) -> str:
    """Read a file or directory into review text. Skips dotfiles (.env/.git),
    binary and unreadable files, and enforces the byte budget DURING collection
    so a huge tree can't build a giant string before truncation."""
    pth = Path(path_arg)
    files = sorted(pth.rglob("*")) if pth.is_dir() else [pth]
    parts, used = [], 0
    for f in files:
        if f.is_symlink():
            continue  # never follow a symlink out of the tree to the API
        if not f.is_file() or any(p.startswith(".") for p in f.parts):
            continue
        if _looks_binary(f):
            continue
        try:
            content = f.read_text(errors="ignore")
        except OSError:
            continue
        chunk = f"--- {f} ---\n{content}"
        parts.append(chunk)
        used += len(chunk.encode("utf-8", errors="ignore"))
        if used >= cap:
            parts.append(f"\n... [stopped collecting at {cap} bytes] ...")
            break
    return "\n\n".join(parts)


def _run(context, panel_name, settings, panels, client, rigor, fmt):
    if panel_name is None:
        panel_name = pick_panel(context, panels, client,
                                router_model=settings.router_model,
                                default=settings.default_panel)
    if panel_name not in panels:
        print(f"error: unknown panel '{panel_name}'. Available: "
              f"{', '.join(panels)}.", file=sys.stderr)
        raise SystemExit(2)
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

    # ask / review actually call Venice — build the client now (needs the key).
    if client is None:
        client = VeniceClient(get_api_key(), timeout=settings.timeout)

    if args.cmd == "ask":
        ctx = _gather_context(args.question, args.file, settings.byte_cap)
        return _run(ctx, args.panel, settings, panels, client, args.rigor, args.format)

    if args.cmd == "review":
        import subprocess
        if args.diff:
            proc = subprocess.run(["git", "diff"], capture_output=True, text=True)
            if proc.returncode != 0:
                print(f"error: `git diff` failed: {proc.stderr.strip()}", file=sys.stderr)
                return 2
            text = proc.stdout
        elif args.path == "-" or args.path is None:
            text = sys.stdin.read()
        else:
            text = _read_for_review(args.path, settings.byte_cap)
        if not text.strip():
            print("Nothing to review (empty diff / no readable files).", file=sys.stderr)
            return 0
        ctx = truncate(f"Review this:\n\n{text}", settings.byte_cap)
        return _run(ctx, args.panel, settings, panels, client, args.rigor, args.format)

    return 1
