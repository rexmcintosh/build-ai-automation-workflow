from loom.weave_lint import is_trailing_append, is_excessive_rewrite

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


def test_small_integration_is_not_excessive():
    before = "# Liam\n\n## Swimming\nSwims for Bullsharks.\n\n## Mobility\nTrains weekly.\n"
    after = "# Liam\n\n## Swimming\nSwims competitively for Bullsharks; mobility tracked.\n\n## Mobility\nTrains weekly.\n"
    assert is_excessive_rewrite(before, after) is False

def test_full_restructure_is_excessive():
    before = "# Liam\n\n" + "\n".join(f"Original line {i}." for i in range(20)) + "\n"
    after = "# Liam (rewritten)\n\n" + "\n".join(f"Totally new sentence {i}." for i in range(20)) + "\n"
    assert is_excessive_rewrite(before, after) is True

def test_pure_append_is_not_excessive():
    before = "# Liam\n\nSwims for Bullsharks.\n"
    after = before + "\nA new integrated paragraph about training.\n"
    assert is_excessive_rewrite(before, after) is False

def test_new_article_is_not_excessive():
    assert is_excessive_rewrite("", "# New\n\nbody\n") is False
