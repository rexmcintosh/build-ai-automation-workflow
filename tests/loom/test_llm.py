from loom import llm


def test_build_argv_uses_model_and_print(monkeypatch):
    # Prompt is fed via stdin ("-p -") so it must NOT appear in argv (ARG_MAX fix).
    argv = llm.build_argv(model="sonnet")
    assert argv[0].endswith("claude")
    assert "-p" in argv
    assert "-" in argv  # stdin placeholder
    assert "sonnet" in argv
    assert "--dangerously-skip-permissions" not in argv  # distill/weave need no tools by default


def test_build_argv_prompt_not_in_argv(monkeypatch):
    """Large prompts must never appear in argv to avoid ARG_MAX errors."""
    big_prompt = "x" * 4_000_000
    argv = llm.build_argv(model="sonnet")
    assert big_prompt not in argv


def test_run_returns_stdout(monkeypatch):
    class FakeProc:
        returncode = 0
        stdout = "RESULT TEXT"
        stderr = ""
    monkeypatch.setattr(llm.subprocess, "run", lambda *a, **k: FakeProc())
    assert llm.run("prompt", model="haiku") == "RESULT TEXT"


def test_run_raises_on_nonzero(monkeypatch):
    class FakeProc:
        returncode = 1
        stdout = ""
        stderr = "boom"
    monkeypatch.setattr(llm.subprocess, "run", lambda *a, **k: FakeProc())
    import pytest
    with pytest.raises(llm.LLMError):
        llm.run("prompt", model="opus")
