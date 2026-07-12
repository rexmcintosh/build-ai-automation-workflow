import pytest
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
    with pytest.raises(llm.LLMError):
        llm.run("prompt", model="opus")


class _Proc:
    def __init__(self, returncode, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_build_argv_disables_plugins_via_settings():
    argv = llm.build_argv("sonnet")
    assert "--settings" in argv
    assert argv[argv.index("--settings") + 1].endswith("headless-settings.json")


def test_run_raises_usage_limit_error_on_session_limit(monkeypatch):
    def fake_run(argv, **kwargs):
        return _Proc(1, stdout="You've hit your session limit · resets 5:10am (Europe/Lisbon)")
    monkeypatch.setattr(llm.subprocess, "run", fake_run)
    with pytest.raises(llm.UsageLimitError):
        llm.run("hi", model="sonnet")


def test_run_raises_plain_llmerror_with_stdout_on_generic_failure(monkeypatch):
    def fake_run(argv, **kwargs):
        return _Proc(1, stdout="some diagnostic on stdout", stderr="")
    monkeypatch.setattr(llm.subprocess, "run", fake_run)
    with pytest.raises(llm.LLMError) as ei:
        llm.run("hi", model="sonnet")
    assert not isinstance(ei.value, llm.UsageLimitError)
    assert "some diagnostic on stdout" in str(ei.value)
