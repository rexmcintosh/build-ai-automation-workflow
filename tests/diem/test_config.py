import textwrap
from pathlib import Path
import pytest
from diem.config import DiemConfig, load_venice_key

TOML = textwrap.dedent("""
    daily_diem = 100.0
    repos = ["/home/dev/projects/swimtrack"]
    deadline = "00:50"
    reset = "01:00"
    state_dir = "{state}"
    outputs_dir = "{out}"
    loom_repo = "/home/dev/projects/build-ai-automation-workflow"
    loom_cmd = ["/home/dev/projects/build-ai-automation-workflow/.venv/bin/python", "-m", "loom.cli", "backfill"]

    [[checkpoints]]
    time = "21:00"
    floor = 0.40
    [[checkpoints]]
    time = "23:00"
    floor = 0.15
    [[checkpoints]]
    time = "00:15"
    floor = 0.0

    [seeds.images]
    cost = 2.0
    duration_s = 180
    [seeds.ask]
    cost = 0.5
    duration_s = 120

    [telegram]
    bot_token = "tok"
    chat_id = "123"

    [cmd_whitelist.teasers]
    repo = "/home/dev/projects/romance-empire"
    argv = ["python", "scripts/make_teasers.py"]
""")

def _write_cfg(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(TOML.format(state=tmp_path / "state", out=tmp_path / "out"))
    return p

def test_load_parses_all_sections(tmp_path):
    cfg = DiemConfig.load(_write_cfg(tmp_path))
    assert cfg.daily_diem == 100.0
    assert cfg.checkpoints[0].time == "21:00" and cfg.checkpoints[0].floor == 0.40
    assert cfg.checkpoints[2].floor == 0.0
    assert cfg.repos == [Path("/home/dev/projects/swimtrack")]
    assert cfg.seeds["images"]["cost"] == 2.0
    assert cfg.telegram["chat_id"] == "123"
    assert cfg.cmd_whitelist["teasers"]["argv"][0] == "python"
    assert cfg.state_dir == tmp_path / "state"

def test_load_defaults(tmp_path):
    p = tmp_path / "min.toml"
    p.write_text('daily_diem = 50.0\nrepos = []\n')
    cfg = DiemConfig.load(p)
    assert cfg.deadline == "00:50" and cfg.reset == "01:00"
    assert cfg.telegram is None
    assert cfg.backfill_max_per_night == 4 and cfg.backfill_chunk == 2
    assert cfg.state_dir == Path.home() / ".local/state/diem"

def test_load_missing_daily_diem_exits(tmp_path):
    p = tmp_path / "bad.toml"
    p.write_text("repos = []\n")
    with pytest.raises(SystemExit):
        DiemConfig.load(p)

@pytest.mark.parametrize("line", [
    'VENICE_API_KEY=sk-abc123',
    'VENICE_KEY="sk-abc123"',
    "export VENICE_API_KEY='sk-abc123'",
])
def test_load_venice_key_variants(tmp_path, line):
    env = tmp_path / ".env"
    env.write_text(f"OTHER=x\n{line}\n")
    assert load_venice_key(env) == "sk-abc123"

def test_load_venice_key_missing_exits(tmp_path):
    env = tmp_path / ".env"
    env.write_text("OTHER=x\n")
    with pytest.raises(SystemExit):
        load_venice_key(env)

def test_partial_seed_override_keeps_default_fields(tmp_path):
    p = tmp_path / "s.toml"
    p.write_text('daily_diem = 1.0\nrepos = []\n[seeds.images]\ncost = 5.0\n')
    cfg = DiemConfig.load(p)
    assert cfg.seeds["images"] == {"cost": 5.0, "duration_s": 180}
