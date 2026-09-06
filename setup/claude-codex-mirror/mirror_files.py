#!/usr/bin/env python3
"""Plan and install a bounded, reversible Claude-to-Codex file mirror."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import shutil
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
PRESERVED_CODEX_SKILLS = {"delegate", "site-flow", "skill-creator"}
LOCK_TIMEOUT_SECONDS = 30.0


class MirrorSafetyError(ValueError):
    """Raised when an inventory-derived name or path would escape its intended root."""


@dataclass(frozen=True)
class Operation:
    kind: str
    source: str
    target: str
    status: str
    description: str = ""
    repo: str | None = None
    root: str = ""


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def slug(value: str) -> str:
    safe = "".join(char.lower() if char.isalnum() else "-" for char in value)
    return "-".join(part for part in safe.split("-") if part)


def validate_segment(value: str) -> str:
    """Reject inventory-derived names that could traverse or escape a path segment."""
    if not value or value in {".", ".."} or "/" in value or "\\" in value or "\x00" in value:
        raise MirrorSafetyError(f"invalid path segment: {value!r}")
    return value


def validate_command_filename(value: str) -> str:
    if not value.endswith(".md"):
        raise MirrorSafetyError(f"invalid command filename: {value!r}")
    validate_segment(value)
    validate_segment(value[: -len(".md")])
    return value


def ensure_within(root: Path, path: Path) -> Path:
    """Resolve `path` and confirm it stays under `root`, even through existing symlinked parents."""
    root_real = root.resolve()
    resolved = path.resolve()
    if resolved != root_real and root_real not in resolved.parents:
        raise MirrorSafetyError(f"{path} escapes required root {root}")
    return resolved


def fingerprint(target: Path) -> tuple[str, ...]:
    """A cheap, comparable snapshot of what a target currently is, used for crash recovery."""
    try:
        if target.is_symlink():
            return ("symlink", os.readlink(target))
        if target.is_dir():
            return ("dir",)
        if target.is_file():
            return ("file", digest(target.read_text(encoding="utf-8")))
        return ("missing",)
    except (OSError, UnicodeDecodeError):
        return ("unreadable",)


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.tmp-{os.getpid()}"
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    with temporary.open("w", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    fsync_dir(path.parent)


def fsync_dir(directory: Path) -> None:
    """Best-effort directory fsync so a rename is durable across power loss.

    This does not by itself guarantee crash consistency of everything under
    `directory` — only that the rename we just performed is recorded.
    """
    try:
        dir_fd = os.open(str(directory), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


class MirrorLock:
    """A single-writer lock for this mirror's ownership state, held across apply_plan."""

    def __init__(self, path: Path, timeout: float = LOCK_TIMEOUT_SECONDS) -> None:
        self.path = path
        self.timeout = timeout
        self._handle: Any = None

    def __enter__(self) -> "MirrorLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = open(self.path, "a+")
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                fcntl.flock(self._handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    self._handle.close()
                    raise TimeoutError(f"Could not acquire mirror lock: {self.path}")
                time.sleep(0.1)

    def __exit__(self, *exc_info: object) -> None:
        assert self._handle is not None
        fcntl.flock(self._handle, fcntl.LOCK_UN)
        self._handle.close()


def wrapper(name: str, description: str, source: Path, repo: Path | None = None) -> str:
    scope = ""
    if repo is not None:
        scope = f"\nUse only for `{repo}`, including its worktrees. Verify repository identity if unclear. Apply changes in the active checkout, not the source repository checkout.\n"
    adaptation = ""
    if source.parent.name == "commands" and repo is None:
        if source.stem == "setup-mcp":
            adaptation = "Use current Codex MCP configuration and `codex mcp` commands for this harness. Treat Claude CLI examples as intent; do not configure Claude again unless the user targets Claude. Consult the installed openai-docs and claude-connectors skills as needed.\n"
        elif source.stem in {"install-skill", "create-command", "export-skill"}:
            adaptation = "Default to Codex skills and command equivalents: global skills under ~/.codex/skills and project skills under .agents/skills. Use the installed skill-creator or skill-installer where appropriate. Preserve an explicitly requested Claude target; do not copy Claude-specific configuration syntax into Codex.\n"
    return (
        "---\n"
        f"name: {name}\n"
        f"description: {description}\n"
        "---\n\n"
        f"# {name}\n"
        f"{scope}\n"
        f"{adaptation}Read `{source}` in full, then follow its instructions for this request.\n"
        "Treat Claude-specific tool names as intent. Use the matching Codex tool when one exists.\n"
        "Keep the canonical source unchanged. This mirror does not copy secrets; use the source workflow existing credential loader.\n"
    )


def owned_entries(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    data = load_json(path)
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"Unsupported ownership manifest: {path}")
    return {entry["target"]: entry for entry in data.get("entries", [])}


def classify(target: Path, kind: str, source: Path, content: str | None, owned: dict[str, Any]) -> str:
    if not target.exists() and not target.is_symlink():
        return "create"
    prior = owned.get(str(target))
    if prior is None:
        return "preserve-unmanaged"
    if kind == "symlink":
        if target.is_symlink() and Path(os.readlink(target)) == source:
            return "unchanged"
        if target.is_symlink() and os.readlink(target) == prior.get("source"):
            return "replace-owned"
        return "preserve-owned-modified"
    if kind == "wrapper" and target.is_file() and content is not None:
        try:
            current_hash = digest(target.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            return "preserve-owned-modified"
        if current_hash == digest(content):
            return "unchanged"
        if current_hash == prior.get("content_sha256"):
            return "replace-owned"
    return "preserve-owned-modified"


def reject(ops: list[Operation], source: str, context: str, error: MirrorSafetyError) -> None:
    ops.append(Operation("rejected", source, "", "rejected-invalid-name", f"{context}: {error}"))


def safe_segment(value: str, ops: list[Operation], *, source: str, context: str) -> str | None:
    try:
        return validate_segment(value)
    except MirrorSafetyError as error:
        reject(ops, source, context, error)
        return None


def add_symlink(ops: list[Operation], source: Path, target: Path, owned: dict[str, Any],
                root: Path, repo: Path | None = None) -> None:
    status = "source-missing"
    if source.is_dir() and (source / "SKILL.md").is_file():
        status = classify(target, "symlink", source, None, owned)
    ops.append(Operation("symlink", str(source), str(target), status, repo=str(repo) if repo else None, root=str(root)))


def add_wrapper(ops: list[Operation], name: str, description: str, source: Path, target: Path,
                owned: dict[str, Any], root: Path, repo: Path | None = None) -> None:
    status = "source-missing"
    if source.is_file():
        status = classify(target, "wrapper", source, wrapper(name, description, source, repo), owned)
    ops.append(Operation("wrapper", str(source), str(target), status, description, str(repo) if repo else None, str(root)))


def build_plan(inventory: dict[str, Any], codex_home: Path, projects_root: Path, ownership: Path) -> list[Operation]:
    owned = owned_entries(ownership)
    ops: list[Operation] = []
    skills_root = codex_home / "skills"
    for skill in inventory["claude_global"]["skills"]:
        raw_name = skill["name"]
        if skill["classification"] == "already-present" or raw_name in PRESERVED_CODEX_SKILLS:
            continue
        name = safe_segment(raw_name, ops, source=str(skill.get("path", "")), context="claude_global skill name")
        if name is None:
            continue
        add_symlink(ops, Path(skill["path"]), skills_root / name, owned, skills_root)

    plugins = inventory.get("plugins", {})
    for plugin_ref, enabled in sorted(plugins.get("enabled", {}).items()):
        if not enabled:
            continue
        raw_plugin_name = plugin_ref.split("@", 1)[0]
        plugin_name = safe_segment(raw_plugin_name, ops, source=plugin_ref, context="plugin name")
        if plugin_name is None:
            continue
        active = plugins.get("active_paths", {}).get(plugin_name)
        if not active:
            continue
        declared = set(plugins.get("plugin_skill_names", {}).get(plugin_name, []))
        discovered = {path.parent.name for path in (Path(active) / "skills").glob("*/SKILL.md")}
        for raw_skill_name in sorted(declared | discovered):
            skill_name = safe_segment(raw_skill_name, ops, source=str(Path(active) / "skills" / raw_skill_name),
                                       context="plugin skill name")
            if skill_name is None:
                continue
            if plugin_name == "delegate" and skill_name == "delegate":
                continue
            target_name = skill_name
            if target_name in PRESERVED_CODEX_SKILLS:
                target_name = f"claude-plugin-{plugin_name}-{skill_name}"
            source = Path(active) / "skills" / skill_name
            if plugin_name == "delegate":
                add_wrapper(ops, target_name, f"Use the mirrored delegate {skill_name} workflow in Codex.",
                            source / "SKILL.md", skills_root / target_name / "SKILL.md", owned, skills_root)
            else:
                add_symlink(ops, source, skills_root / target_name, owned, skills_root)

    for raw_command in inventory["claude_global"].get("commands", []):
        command = safe_segment(raw_command, ops, source=raw_command, context="claude command name")
        if command is None:
            continue
        name = f"claude-command-{slug(command)}"
        source = Path.home() / ".claude" / "commands" / f"{command}.md"
        add_wrapper(ops, name, f"Run the mirrored Claude /{command} command in Codex.", source,
                    skills_root / name / "SKILL.md", owned, skills_root)

    projects = inventory.get("project_scoped_all_direct_projects", {})
    for raw_repo_name, commands in sorted(projects.get("project_claude_commands", {}).items()):
        repo_name = safe_segment(raw_repo_name, ops, source=raw_repo_name, context="project repo name")
        if repo_name is None:
            continue
        repo = projects_root / repo_name
        try:
            ensure_within(projects_root, repo)
        except MirrorSafetyError as error:
            reject(ops, str(repo), "project repo path", error)
            continue
        repo_root = repo / ".agents" / "skills"
        for command_file in commands:
            try:
                validate_command_filename(command_file)
            except MirrorSafetyError as error:
                reject(ops, command_file, "project command filename", error)
                continue
            command = Path(command_file).stem
            name = f"repo-command-{slug(command)}"
            source = repo / ".claude" / "commands" / command_file
            add_wrapper(ops, name, f"Run this repository's /{command} command in Codex.", source,
                        repo_root / name / "SKILL.md", owned, repo_root, repo)
    for raw_repo_name, skill_names in sorted(projects.get("project_claude_skills", {}).items()):
        repo_name = safe_segment(raw_repo_name, ops, source=raw_repo_name, context="project repo name")
        if repo_name is None:
            continue
        repo = projects_root / repo_name
        try:
            ensure_within(projects_root, repo)
        except MirrorSafetyError as error:
            reject(ops, str(repo), "project repo path", error)
            continue
        repo_root = repo / ".agents" / "skills"
        for raw_skill_name in skill_names:
            skill_name = safe_segment(raw_skill_name, ops, source=raw_skill_name, context="project skill name")
            if skill_name is None:
                continue
            name = f"repo-skill-{slug(skill_name)}"
            source = repo / ".claude" / "skills" / skill_name / "SKILL.md"
            add_wrapper(ops, name, f"Use this repository's {skill_name} skill in Codex.", source,
                        repo_root / name / "SKILL.md", owned, repo_root, repo)
    return ops


def backup_target(target: Path, backup_root: Path) -> None:
    relative = Path(*target.parts[1:]) if target.is_absolute() else target
    destination = backup_root / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink():
        destination.symlink_to(os.readlink(target))
    elif target.is_dir():
        shutil.copytree(target, destination, symlinks=True)
    else:
        shutil.copy2(target, destination, follow_symlinks=False)


def recompute_status(op: Operation, owned: dict[str, Any]) -> tuple[str, str | None]:
    """Classify `op` against the current, lock-held view of the world (not the stale plan)."""
    source = Path(op.source)
    target = Path(op.target)
    if op.kind == "symlink":
        if not (source.is_dir() and (source / "SKILL.md").is_file()):
            return "source-missing", None
        return classify(target, "symlink", source, None, owned), None
    if not source.is_file():
        return "source-missing", None
    repo = Path(op.repo) if op.repo else None
    content = wrapper(target.parent.name, op.description, source, repo)
    return classify(target, "wrapper", source, content, owned), content


def recover_journal(journal_path: Path, ownership: Path) -> None:
    """Finish an operation that mutated its target but crashed before the ownership update.

    Only ever merges the recorded new state; a target left in any other state
    (someone else's edit) is untouched and simply falls through to normal
    preserve-owned-modified / preserve-unmanaged handling on the next classify.
    """
    if not journal_path.exists():
        return
    try:
        entry = json.loads(journal_path.read_text(encoding="utf-8"))
        target = Path(entry["target"])
        new_fp = tuple(entry["new_fingerprint"])
    except (json.JSONDecodeError, OSError, KeyError, TypeError):
        journal_path.unlink(missing_ok=True)
        return
    if fingerprint(target) == new_fp:
        owned = owned_entries(ownership)
        owned[entry["target"]] = entry["owned_record"]
        atomic_write_json(ownership, {
            "schema_version": SCHEMA_VERSION,
            "entries": sorted(owned.values(), key=lambda item: item["target"]),
        })
    journal_path.unlink(missing_ok=True)


def replace_atomically(target: Path, kind: str, source: Path, content: str | None) -> None:
    temporary = target.parent / f".{target.name}.mirror-tmp-{os.getpid()}"
    if temporary.exists() or temporary.is_symlink():
        temporary.unlink()
    if kind == "symlink":
        temporary.symlink_to(source, target_is_directory=True)
    else:
        assert content is not None
        with temporary.open("w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    os.replace(temporary, target)
    fsync_dir(target.parent)


def apply_plan(ops: list[Operation], ownership: Path, backup_dir: Path) -> dict[str, int]:
    counts = {"created": 0, "replaced": 0, "unchanged": 0, "preserved": 0, "missing": 0, "rejected": 0}
    lock_path = ownership.with_suffix(ownership.suffix + ".lock")
    journal_path = ownership.with_suffix(ownership.suffix + ".journal")
    backup_root = backup_dir / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")

    with MirrorLock(lock_path):
        recover_journal(journal_path, ownership)
        owned = owned_entries(ownership)

        for op in ops:
            if op.kind == "rejected":
                counts["rejected"] += 1
                continue

            status, content = recompute_status(op, owned)
            if status == "source-missing":
                counts["missing"] += 1
                continue
            if status in {"preserve-unmanaged", "preserve-owned-modified"}:
                counts["preserved"] += 1
                continue
            if status == "unchanged":
                counts["unchanged"] += 1
                continue

            source, target = Path(op.source), Path(op.target)
            root = Path(op.root) if op.root else target.parent
            try:
                ensure_within(root, target.parent)
            except MirrorSafetyError:
                counts["rejected"] += 1
                continue

            if status == "replace-owned":
                backup_root.mkdir(parents=True, exist_ok=True, mode=0o700)
                backup_target(target, backup_root)

            target.parent.mkdir(parents=True, exist_ok=True)
            prior_fp = fingerprint(target)
            if op.kind == "symlink":
                new_fp = ("symlink", str(source))
                owned_record = {"kind": "symlink", "source": str(source), "target": str(target), "content_sha256": None}
            else:
                new_fp = ("file", digest(content or ""))
                owned_record = {"kind": "wrapper", "source": str(source), "target": str(target),
                                 "content_sha256": digest(content or "")}

            atomic_write_json(journal_path, {
                "target": str(target),
                "prior_fingerprint": list(prior_fp),
                "new_fingerprint": list(new_fp),
                "owned_record": owned_record,
            })

            replace_atomically(target, op.kind, source, content)

            owned[str(target)] = owned_record
            atomic_write_json(ownership, {
                "schema_version": SCHEMA_VERSION,
                "entries": sorted(owned.values(), key=lambda item: item["target"]),
            })
            journal_path.unlink(missing_ok=True)

            counts["created" if status == "create" else "replaced"] += 1

    return counts


def persist_inventory(inventory: dict[str, Any], path: Path) -> None:
    atomic_write_json(path, {"schema_version": SCHEMA_VERSION, "inventory": inventory})


def main(argv: list[str] | None = None) -> int:
    try:
        return run_main(argv)
    except (OSError, ValueError, RuntimeError) as error:
        print(f"Mirror stopped: {error}", file=sys.stderr)
        return 2


def run_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, help="Fresh inventory JSON; defaults to the saved installed inventory.")
    parser.add_argument("--codex-home", type=Path, default=Path.home() / ".codex")
    parser.add_argument("--projects-root", type=Path, default=Path.home() / "projects")
    parser.add_argument("--ownership", type=Path)
    parser.add_argument("--backup-dir", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    ownership = args.ownership or args.codex_home / "claude-mirror-owned.json"
    backup_dir = args.backup_dir or args.codex_home / "backups" / "claude-mirror"
    saved_inventory = args.codex_home / "mirrors" / "claude" / "inventory.json"
    inventory_path = args.inventory or (saved_inventory if saved_inventory.exists() else Path("/tmp/claude-skill-inventory.json"))
    data = load_json(inventory_path)
    if "inventory" in data:
        if data.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(f"Unsupported inventory schema: {inventory_path}")
        data = data["inventory"]
    ops = build_plan(data, args.codex_home, args.projects_root, ownership)
    result: dict[str, Any] = {"mode": "plan", "operations": [asdict(item) for item in ops]}
    if args.apply:
        result["mode"] = "apply"
        result["applied"] = apply_plan(ops, ownership, backup_dir)
        persist_inventory(data, saved_inventory)
    json.dump(result, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
