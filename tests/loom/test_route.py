# tests/loom/test_route.py
from loom.route import confirm_route


class _Backend:
    def __init__(self, reply): self._reply = reply
    def complete(self, role, system, user, json_mode=False):
        assert role == "route" and json_mode is True
        return self._reply


_LEARNING = {"type": "fact", "subject": "Liam", "learning": "swims for Bullsharks",
             "route": "wiki/people/liam"}


def test_parses_model_json():
    b = _Backend('{"target": "people/liam.md", "action": "update", "cross_links": ["portugal"]}')
    r = confirm_route(b, _LEARNING, index_listing="- [[liam]] ...")
    assert r == {"target": "people/liam.md", "action": "update", "cross_links": ["portugal"]}


def test_tolerates_json_in_code_fence():
    b = _Backend('```json\n{"target":"people/liam.md","action":"update","cross_links":[]}\n```')
    r = confirm_route(b, _LEARNING, index_listing="")
    assert r["target"] == "people/liam.md"


def test_falls_back_to_suggested_route_on_garbage():
    b = _Backend("not json at all")
    r = confirm_route(b, _LEARNING, index_listing="")
    assert r["target"] == "people/liam.md" and r["action"] == "update"


def test_returns_none_when_unparseable_and_no_suggestion():
    b = _Backend("garbage")
    r = confirm_route(b, {"type": "fact", "subject": "x", "learning": "y"}, index_listing="")
    assert r is None
