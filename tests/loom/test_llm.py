from loom import llm


def test_build_argv_uses_model_and_print(monkeypatch):
    argv = llm.build_argv("do the thing", model="sonnet")
    assert argv[0].endswith("claude")
    assert "-p" in argv
    assert "do the thing" in argv
    assert "sonnet" in argv
    assert "--dangerously-skip-permissions" not in argv  # distill/weave need no tools by default


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
