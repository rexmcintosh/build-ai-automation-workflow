import pytest
from diem.usage import UsageClient, UsageUnavailable

class FakeResp:
    def __init__(self, status=200, body=None):
        self.status_code = status; self._body = body or {}
    def json(self):
        return self._body

def _client(resp=None, exc=None):
    def get(url, headers=None, timeout=None):
        assert headers["Authorization"].startswith("Bearer ")
        assert "api_keys" in url
        if exc: raise exc
        return resp
    return UsageClient("sk-admin", get=get)

def test_parses_per_key_trailing_usage():
    body = {"data": [
        {"id": "k1", "description": "proj-romance",
         "usage": {"trailingSevenDays": {"usd": "1.23", "diem": "4.5"}}},
        {"id": "k2", "description": "proj-swimtrack",
         "usage": {"trailingSevenDays": {"usd": "0.10", "diem": "0.4"}}},
    ]}
    keys = _client(FakeResp(body=body)).per_key_usage()
    by = {k["key_name"]: k for k in keys}
    assert by["proj-romance"]["usd"] == 1.23 and by["proj-romance"]["key_id"] == "k1"
    assert by["proj-swimtrack"]["diem"] == 0.4

def test_http_error_raises_unavailable():
    with pytest.raises(UsageUnavailable):
        _client(FakeResp(status=500)).per_key_usage()

def test_network_error_raises_unavailable():
    with pytest.raises(UsageUnavailable):
        _client(exc=ConnectionError("down")).per_key_usage()

@pytest.mark.parametrize("body", [
    {"data": None},
    ["not", "a", "dict"],
    {"data": ["not-a-dict-item"]},
    {"data": [{"id": "k1", "description": "x",
               "usage": {"trailingSevenDays": {"usd": "not-a-number", "diem": "1"}}}]},
])
def test_malformed_200_bodies_raise_unavailable(body):
    with pytest.raises(UsageUnavailable):
        _client(FakeResp(body=body)).per_key_usage()
