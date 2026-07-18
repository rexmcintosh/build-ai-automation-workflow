from venice_usage.pricing import estimate_usd

def test_known_text_model_priced_from_tokens():
    # claude-opus-4-8 seeded at (15.0, 75.0) $/Mtok -> 1M in + 1M out = 15 + 75
    assert estimate_usd("claude-opus-4-8", 1_000_000, 1_000_000) == 90.0

def test_rounds_to_six_places():
    assert estimate_usd("claude-opus-4-8", 1000, 0) == round(1000/1e6*15.0, 6)

def test_unknown_model_returns_none():
    assert estimate_usd("flux-2-max", 0, 0) is None
