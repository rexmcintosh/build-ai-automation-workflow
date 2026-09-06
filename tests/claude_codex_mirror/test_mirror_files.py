import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).parents[2] / "setup" / "claude-codex-mirror" / "mirror_files.py"
SPEC = importlib.util.spec_from_file_location("mirror_files", MODULE_PATH)
mirror = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = mirror
SPEC.loader.exec_module(mirror)


def make_skill(path: Path, name: str = "sample") -> None:
    path.mkdir(parents=True)
    (path / "SKILL.md").write_text(f"---\nname: {name}\ndescription: Test.\n---\n", encoding="utf-8")


def tree_hash(root: Path) -> str:
    sha = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file():
            sha.update(str(path.relative_to(root)).encode())
            sha.update(path.read_bytes())
    return sha.hexdigest()


def inventory(skill: Path, projects: Path, command: Path) -> dict:
    repo = projects / "demo"
    project_command = repo / ".claude" / "commands" / "build.md"
    project_command.parent.mkdir(parents=True)
    project_command.write_text("Build the project.\n", encoding="utf-8")
    project_skill = repo / ".claude" / "skills" / "verify"
    make_skill(project_skill, "verify")
    return {
        "claude_global": {
            "skills": [
                {"name": "portable", "path": str(skill), "classification": "needs-adaptation"},
                {"name": "cloudflare", "path": "/unused", "classification": "already-present"},
            ],
            "commands": [command.stem],
        },
        "plugins": {"enabled": {}, "active_paths": {}, "plugin_skill_names": {}},
        "project_scoped_all_direct_projects": {
            "project_claude_commands": {"demo": ["build.md"]},
            "project_claude_skills": {"demo": ["verify"]},
        },
    }


def test_plan_apply_and_reapply_leave_sources_unchanged(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(fake_home))
    source = fake_home / ".claude" / "skills" / "portable"
    make_skill(source, "portable")
    (source / ".env").write_text("TOKEN=do-not-copy\n", encoding="utf-8")
    command = fake_home / ".claude" / "commands" / "close.md"
    command.parent.mkdir(parents=True)
    command.write_text("Close safely.\n", encoding="utf-8")
    projects = tmp_path / "projects"
    data = inventory(source, projects, command)
    codex_home = fake_home / ".codex"
    ownership = codex_home / "claude-mirror-owned.json"
    before = tree_hash(fake_home / ".claude")

    plan = mirror.build_plan(data, codex_home, projects, ownership)
    assert {item.status for item in plan} == {"create"}
    result = mirror.apply_plan(plan, ownership, codex_home / "backups")
    assert result["created"] == 4
    target = codex_home / "skills" / "portable"
    assert target.is_symlink()
    assert os.readlink(target) == str(source)
    wrapper = codex_home / "skills" / "claude-command-close" / "SKILL.md"
    assert str(command) in wrapper.read_text()
    assert "do-not-copy" not in ownership.read_text()
    assert tree_hash(fake_home / ".claude") == before

    second = mirror.build_plan(data, codex_home, projects, ownership)
    assert {item.status for item in second} == {"unchanged"}
    result = mirror.apply_plan(second, ownership, codex_home / "backups")
    assert result["unchanged"] == 4


def test_unmanaged_target_is_preserved(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(fake_home))
    source = fake_home / ".claude" / "skills" / "portable"
    make_skill(source)
    command = fake_home / ".claude" / "commands" / "close.md"
    command.parent.mkdir(parents=True)
    command.write_text("source\n")
    projects = tmp_path / "projects"
    data = inventory(source, projects, command)
    codex_home = fake_home / ".codex"
    target = codex_home / "skills" / "portable"
    make_skill(target, "owner-copy")

    plan = mirror.build_plan(data, codex_home, projects, codex_home / "owned.json")
    item = next(item for item in plan if item.target == str(target))
    assert item.status == "preserve-unmanaged"
    mirror.apply_plan(plan, codex_home / "owned.json", codex_home / "backups")
    assert not target.is_symlink()
    assert "owner-copy" in (target / "SKILL.md").read_text()


def test_manually_edited_owned_wrapper_is_preserved(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(fake_home))
    source = fake_home / ".claude" / "skills" / "portable"
    make_skill(source)
    command = fake_home / ".claude" / "commands" / "close.md"
    command.parent.mkdir(parents=True)
    command.write_text("source\n")
    projects = tmp_path / "projects"
    data = inventory(source, projects, command)
    codex_home = fake_home / ".codex"
    ownership = codex_home / "owned.json"
    mirror.apply_plan(mirror.build_plan(data, codex_home, projects, ownership), ownership, codex_home / "backups")
    target = codex_home / "skills" / "claude-command-close" / "SKILL.md"
    target.write_text("owner-edited\n")

    plan = mirror.build_plan(data, codex_home, projects, ownership)
    item = next(item for item in plan if item.target == str(target))
    assert item.status == "preserve-owned-modified"
    result = mirror.apply_plan(plan, ownership, codex_home / "backups")
    assert result["preserved"] == 1
    assert target.read_text() == "owner-edited\n"


def test_owned_link_source_change_is_backed_up(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(fake_home))
    first = fake_home / ".claude" / "skills" / "portable"
    second = fake_home / ".claude" / "skills" / "portable-v2"
    make_skill(first)
    make_skill(second)
    command = fake_home / ".claude" / "commands" / "close.md"
    command.parent.mkdir(parents=True)
    command.write_text("source\n")
    projects = tmp_path / "projects"
    data = inventory(first, projects, command)
    codex_home = fake_home / ".codex"
    ownership = codex_home / "owned.json"
    mirror.apply_plan(mirror.build_plan(data, codex_home, projects, ownership), ownership, codex_home / "backups")
    data["claude_global"]["skills"][0]["path"] = str(second)

    plan = mirror.build_plan(data, codex_home, projects, ownership)
    item = next(item for item in plan if item.target.endswith("/portable"))
    assert item.status == "replace-owned"
    mirror.apply_plan(plan, ownership, codex_home / "backups")
    assert Path(item.target).resolve() == second.resolve()
    assert list((codex_home / "backups").rglob("portable"))


def test_discovers_frontend_skill_from_active_plugin(tmp_path):
    plugin = tmp_path / "frontend-active"
    make_skill(plugin / "skills" / "frontend-design", "frontend-design")
    inventory_data = {
        "claude_global": {"skills": [], "commands": []},
        "plugins": {
            "enabled": {"frontend-design@official": True},
            "active_paths": {"frontend-design": str(plugin)},
            "plugin_skill_names": {},
        },
        "project_scoped_all_direct_projects": {},
    }
    codex_home = tmp_path / "codex"
    plan = mirror.build_plan(inventory_data, codex_home, tmp_path / "projects", codex_home / "owned.json")
    assert [(item.source, item.target, item.status) for item in plan] == [
        (str(plugin / "skills" / "frontend-design"), str(codex_home / "skills" / "frontend-design"), "create")
    ]


def test_traversal_skill_name_is_rejected_and_nothing_written(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(fake_home))
    source = fake_home / ".claude" / "skills" / "portable"
    make_skill(source)
    command = fake_home / ".claude" / "commands" / "close.md"
    command.parent.mkdir(parents=True)
    command.write_text("source\n")
    projects = tmp_path / "projects"
    data = inventory(source, projects, command)
    data["claude_global"]["skills"].append(
        {"name": "../../escaped", "path": str(source), "classification": "needs-adaptation"}
    )
    codex_home = fake_home / ".codex"
    ownership = codex_home / "owned.json"

    plan = mirror.build_plan(data, codex_home, projects, ownership)
    rejected = [item for item in plan if item.status == "rejected-invalid-name"]
    assert any("escaped" in item.description for item in rejected)
    assert all(item.target == "" for item in rejected)

    result = mirror.apply_plan(plan, ownership, codex_home / "backups")
    assert result["rejected"] >= 1
    assert not list(tmp_path.rglob("escaped"))


def test_traversal_repo_name_and_command_filename_are_rejected(tmp_path):
    codex_home = tmp_path / "codex"
    projects = tmp_path / "projects"
    data = {
        "claude_global": {"skills": [], "commands": []},
        "plugins": {"enabled": {}, "active_paths": {}, "plugin_skill_names": {}},
        "project_scoped_all_direct_projects": {
            "project_claude_commands": {"../../etc": ["passwd.md"], "demo": ["../escape.md", "ok.md"]},
            "project_claude_skills": {},
        },
    }
    (projects / "demo" / ".claude" / "commands").mkdir(parents=True)
    (projects / "demo" / ".claude" / "commands" / "ok.md").write_text("Ok.\n")

    plan = mirror.build_plan(data, codex_home, projects, codex_home / "owned.json")
    rejected_descriptions = " ".join(item.description for item in plan if item.status == "rejected-invalid-name")
    assert "../../etc" in rejected_descriptions
    assert "../escape.md" in rejected_descriptions
    assert any(item.status != "rejected-invalid-name" for item in plan if "ok" in item.target)
    assert not (tmp_path / "etc").exists()


def test_plugin_name_with_separator_is_rejected(tmp_path):
    plugin = tmp_path / "frontend-active"
    make_skill(plugin / "skills" / "frontend-design", "frontend-design")
    inventory_data = {
        "claude_global": {"skills": [], "commands": []},
        "plugins": {
            "enabled": {"../escape@official": True},
            "active_paths": {"../escape": str(plugin)},
            "plugin_skill_names": {},
        },
        "project_scoped_all_direct_projects": {},
    }
    codex_home = tmp_path / "codex"
    plan = mirror.build_plan(inventory_data, codex_home, tmp_path / "projects", codex_home / "owned.json")
    assert {item.status for item in plan} == {"rejected-invalid-name"}


def test_symlinked_parent_cannot_redirect_wrapper_write(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(fake_home))
    source = fake_home / ".claude" / "skills" / "portable"
    make_skill(source)
    command = fake_home / ".claude" / "commands" / "close.md"
    command.parent.mkdir(parents=True)
    command.write_text("source\n")
    projects = tmp_path / "projects"
    data = inventory(source, projects, command)
    codex_home = fake_home / ".codex"
    ownership = codex_home / "owned.json"

    outside = tmp_path / "outside-escape"
    outside.mkdir()
    skills_root = codex_home / "skills"
    skills_root.mkdir(parents=True)
    (skills_root / "claude-command-close").symlink_to(outside, target_is_directory=True)

    plan = mirror.build_plan(data, codex_home, projects, ownership)
    result = mirror.apply_plan(plan, ownership, codex_home / "backups")

    assert result["rejected"] >= 1
    assert not (outside / "SKILL.md").exists()


def test_stale_plan_does_not_overwrite_concurrent_owner_edit(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(fake_home))
    source = fake_home / ".claude" / "skills" / "portable"
    make_skill(source)
    command = fake_home / ".claude" / "commands" / "close.md"
    command.parent.mkdir(parents=True)
    command.write_text("source\n")
    projects = tmp_path / "projects"
    data = inventory(source, projects, command)
    codex_home = fake_home / ".codex"
    ownership = codex_home / "owned.json"

    plan = mirror.build_plan(data, codex_home, projects, ownership)  # computed as all "create"

    target = codex_home / "skills" / "portable"
    target.parent.mkdir(parents=True, exist_ok=True)
    make_skill(target, "someone-elses-copy")  # a concurrent owner claims the target first

    result = mirror.apply_plan(plan, ownership, codex_home / "backups")

    assert not target.is_symlink()
    assert "someone-elses-copy" in (target / "SKILL.md").read_text()
    assert result["preserved"] >= 1
    assert str(target) not in mirror.owned_entries(ownership)


def test_recovery_finalizes_ownership_after_crash_before_manifest_write(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(fake_home))
    source = fake_home / ".claude" / "skills" / "portable"
    make_skill(source)
    command = fake_home / ".claude" / "commands" / "close.md"
    command.parent.mkdir(parents=True)
    command.write_text("source\n")
    projects = tmp_path / "projects"
    data = inventory(source, projects, command)
    codex_home = fake_home / ".codex"
    ownership = codex_home / "owned.json"
    target = codex_home / "skills" / "portable"

    # Simulate a crash: the symlink was created (and journaled) but the
    # ownership manifest write never ran.
    target.parent.mkdir(parents=True, exist_ok=True)
    target.symlink_to(source, target_is_directory=True)
    journal_path = ownership.with_suffix(ownership.suffix + ".journal")
    owned_record = {"kind": "symlink", "source": str(source), "target": str(target), "content_sha256": None}
    mirror.atomic_write_json(journal_path, {
        "target": str(target),
        "prior_fingerprint": ["missing"],
        "new_fingerprint": ["symlink", str(source)],
        "owned_record": owned_record,
    })
    assert not ownership.exists()

    mirror.recover_journal(journal_path, ownership)

    assert not journal_path.exists()
    assert mirror.owned_entries(ownership)[str(target)]["source"] == str(source)

    second_plan = mirror.build_plan(data, codex_home, projects, ownership)
    item = next(i for i in second_plan if i.target == str(target))
    assert item.status == "unchanged"


def test_recovery_leaves_foreign_edit_untouched(tmp_path):
    codex_home = tmp_path / "codex"
    ownership = codex_home / "owned.json"
    journal_path = ownership.with_suffix(ownership.suffix + ".journal")
    target = codex_home / "skills" / "portable"
    target.parent.mkdir(parents=True)
    other_source = tmp_path / "someone-elses-source"
    other_source.mkdir()
    target.symlink_to(other_source)  # neither the recorded prior nor new state

    expected_source = tmp_path / "expected-source"
    mirror.atomic_write_json(journal_path, {
        "target": str(target),
        "prior_fingerprint": ["missing"],
        "new_fingerprint": ["symlink", str(expected_source)],
        "owned_record": {"kind": "symlink", "source": str(expected_source), "target": str(target), "content_sha256": None},
    })

    mirror.recover_journal(journal_path, ownership)

    assert not journal_path.exists()
    assert not ownership.exists()
    assert os.readlink(target) == str(other_source)


def test_recovery_noop_when_mutation_never_happened(tmp_path):
    codex_home = tmp_path / "codex"
    ownership = codex_home / "owned.json"
    journal_path = ownership.with_suffix(ownership.suffix + ".journal")
    target = codex_home / "skills" / "portable"
    # target never got created before the crash.

    mirror.atomic_write_json(journal_path, {
        "target": str(target),
        "prior_fingerprint": ["missing"],
        "new_fingerprint": ["symlink", "/some/source"],
        "owned_record": {"kind": "symlink", "source": "/some/source", "target": str(target), "content_sha256": None},
    })

    mirror.recover_journal(journal_path, ownership)

    assert not journal_path.exists()
    assert not ownership.exists()
    assert not target.exists()


def test_concurrent_apply_is_serialized_by_lock(tmp_path):
    lock_path = tmp_path / "owned.json.lock"
    holder = mirror.MirrorLock(lock_path, timeout=1)
    with holder:
        contender = mirror.MirrorLock(lock_path, timeout=0.2)
        with pytest.raises(TimeoutError):
            with contender:
                pass  # pragma: no cover - must not be reached


def test_refresh_uses_saved_inventory_when_original_was_temporary(tmp_path, capsys):
    codex_home = tmp_path / "codex"
    source = tmp_path / "portable"
    make_skill(source)
    data = {"claude_global": {"skills": [{"name": "portable", "path": str(source), "classification": "needs-adaptation"}], "commands": []}}
    mirror.persist_inventory(data, codex_home / "mirrors" / "claude" / "inventory.json")
    assert mirror.main(["--codex-home", str(codex_home), "--projects-root", str(tmp_path / "projects")]) == 0
    result = json.loads(capsys.readouterr().out)
    assert len(result["operations"]) == 1
    assert result["operations"][0]["source"] == str(source)
    assert result["operations"][0]["status"] == "create"


def test_non_utf8_owned_wrapper_is_preserved(tmp_path):
    target=tmp_path/"SKILL.md"
    target.write_bytes(b"\xff\xfeowner edit")
    before=target.read_bytes()
    owned={str(target):{"content_sha256":mirror.digest("original")}}
    assert mirror.classify(target,"wrapper",tmp_path/"source", "replacement",owned)=="preserve-owned-modified"
    assert mirror.fingerprint(target)==("unreadable",)
    assert target.read_bytes()==before


def test_bad_inventory_has_controlled_error(tmp_path,capsys):
    inventory_path=tmp_path/"invalid.json"
    inventory_path.write_text("{broken")
    assert mirror.main(["--inventory",str(inventory_path),"--codex-home",str(tmp_path/"codex")])==2
    error=capsys.readouterr().err
    assert "Mirror stopped:" in error
    assert "Traceback" not in error
