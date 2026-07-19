"""Venice per-key trailing-7-day usage (admin key). Mirrors balance.py:
injectable get, Bearer header, dedicated *Unavailable. Read-only cross-check
for the ledger — never gates anything, so failure just degrades the report."""
from __future__ import annotations
import requests

API_KEYS_URL = "https://api.venice.ai/api/v1/api_keys"

class UsageUnavailable(RuntimeError):
    pass

class UsageClient:
    def __init__(self, admin_key: str, *, get=None, timeout: int = 30):
        self.admin_key = admin_key
        self.timeout = timeout
        self._get = get or requests.get

    def per_key_usage(self) -> list[dict]:
        try:
            r = self._get(API_KEYS_URL,
                          headers={"Authorization": f"Bearer {self.admin_key}"},
                          timeout=self.timeout)
        except Exception as e:  # noqa: BLE001
            raise UsageUnavailable(f"api_keys unreachable: {e}") from e
        if getattr(r, "status_code", 200) != 200:
            raise UsageUnavailable(f"api_keys HTTP {r.status_code}")
        try:
            body = r.json()
        except Exception as e:  # noqa: BLE001
            raise UsageUnavailable(f"api_keys non-JSON: {e}") from e
        return self._parse_keys(body)

    @staticmethod
    def _parse_keys(body) -> list[dict]:
        items = body.get("data") if isinstance(body, dict) else body
        if not isinstance(items, list):
            raise UsageUnavailable(f"unexpected api_keys envelope: {body!r:.200}")
        out = []
        for it in items:
            try:
                seven = (it.get("usage", {}) or {}).get("trailingSevenDays", {}) or {}
                out.append({
                    "key_id": str(it.get("id", "")),
                    "key_name": str(it.get("description") or it.get("name") or ""),
                    "usd": float(seven.get("usd") or 0.0),
                    "diem": float(seven.get("diem") or 0.0),
                })
            except Exception as e:  # noqa: BLE001 — any malformed row = unavailable
                raise UsageUnavailable(f"unparseable key row: {e}") from e
        return out
