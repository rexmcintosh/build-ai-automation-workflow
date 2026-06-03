from __future__ import annotations
import time
import requests

VENICE_API = "https://api.venice.ai/api/v1/chat/completions"


class VeniceError(RuntimeError):
    pass


class VeniceClient:
    """Thin Venice chat client. `post` is injectable for tests."""

    def __init__(self, api_key, *, base_url=VENICE_API, timeout=180,
                 retries=2, backoff=1.5, post=None, temperature=0.2):
        if not api_key:
            raise VeniceError("VENICE_API_KEY is not set")
        self.api_key = api_key
        self.base_url = base_url
        self.timeout = timeout
        self.retries = retries
        self.backoff = backoff
        self.temperature = temperature
        self._post = post or requests.post

    def complete(self, model, system, user, *, json_mode=True):
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self.temperature,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        headers = {"Authorization": f"Bearer {self.api_key}",
                   "Content-Type": "application/json"}
        last = None
        for attempt in range(self.retries + 1):
            try:
                r = self._post(self.base_url, headers=headers, json=payload,
                               timeout=self.timeout)
                r.raise_for_status()
                return r.json()["choices"][0]["message"]["content"]
            except Exception as e:  # noqa: BLE001 — bounded retry on any failure
                last = e
                if attempt < self.retries:
                    time.sleep(self.backoff * (attempt + 1))
        raise VeniceError(f"Venice call failed after {self.retries + 1} tries: {last}")
