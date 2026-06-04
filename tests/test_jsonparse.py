import pytest
from council.jsonparse import loads_lenient


def test_plain_json_object():
    assert loads_lenient('{"a": 1}') == {"a": 1}


def test_strips_json_code_fence():
    # claude-opus-4-8 via Venice does this ~75% of the time despite json_object mode
    raw = '```json\n{"recommendation": "x", "confidence": 8}\n```'
    assert loads_lenient(raw)["confidence"] == 8


def test_strips_bare_code_fence():
    assert loads_lenient('```\n{"a": 1}\n```') == {"a": 1}


def test_extracts_object_from_surrounding_prose():
    raw = 'Here is the result:\n{"a": 1, "b": [2, 3]}\nHope that helps!'
    assert loads_lenient(raw) == {"a": 1, "b": [2, 3]}


def test_raises_on_no_json():
    with pytest.raises(ValueError):
        loads_lenient("no json here at all")


def test_raises_on_none():
    with pytest.raises(ValueError):
        loads_lenient(None)
