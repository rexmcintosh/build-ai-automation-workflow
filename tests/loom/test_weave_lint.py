from loom.weave_lint import is_trailing_append

def test_pure_trailing_append_is_flagged():
    before = "# Liam\n\nSwims for Bullsharks.\n"
    after = before + "\n## 2026-06-07\n- swims for Bullsharks\n"
    assert is_trailing_append(before, after) is True

def test_integrated_edit_is_ok():
    before = "# Liam\n\n## Swimming\nSwims for Bullsharks.\n"
    after = "# Liam\n\n## Swimming\nSwims competitively for Bullsharks; mobility tracked.\n"
    assert is_trailing_append(before, after) is False

def test_new_article_is_ok():
    assert is_trailing_append("", "# New\n\nbody\n") is False
