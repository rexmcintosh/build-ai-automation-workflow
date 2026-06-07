from loom.transcript import extract_text

def test_extracts_user_and_assistant_text(tmp_path):
    f = tmp_path / "t.jsonl"
    f.write_text(
        '{"type":"user","message":{"content":"hello"}}\n'
        '{"type":"assistant","message":{"content":[{"type":"text","text":"hi back"}]}}\n'
    )
    out = extract_text(f)
    assert "[user] hello" in out
    assert "[assistant] hi back" in out

def test_truncates_large_tool_result(tmp_path):
    f = tmp_path / "t.jsonl"
    big = "X" * 5000
    f.write_text(
        '{"type":"user","message":{"content":[{"type":"tool_result","content":"%s"}]}}\n' % big
    )
    out = extract_text(f, max_tool_chars=100)
    assert "X" * 100 in out
    assert "X" * 200 not in out  # truncated

def test_skips_blank_and_malformed_lines(tmp_path):
    f = tmp_path / "t.jsonl"
    f.write_text('\n{not json}\n{"type":"user","message":{"content":"ok"}}\n')
    assert extract_text(f).strip() == "[user] ok"
