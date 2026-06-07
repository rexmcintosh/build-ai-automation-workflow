from loom import cli

def test_default_config_paths():
    cfg = cli.default_config()
    assert str(cfg.projects_dir).endswith(".claude/projects")
    assert str(cfg.state_path).endswith("loom/state.json")
