"""DeepSeek API transport. The offline fixture exists only for smoke tests."""
from __future__ import annotations

import json
import os
import urllib.request


class DeepSeek:
    def __init__(self, api_key: str | None = None, model: str = "deepseek-chat"):
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        if not self.api_key:
            raise ValueError("Set DEEPSEEK_API_KEY for live runs")
        self.model = model

    def complete(self, system: str, user: str) -> str:
        payload = json.dumps({"model": self.model, "messages": [
            {"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0.2, "response_format": {"type": "json_object"}}).encode()
        req = urllib.request.Request("https://api.deepseek.com/chat/completions", data=payload,
                                     headers={"Authorization": f"Bearer {self.api_key}",
                                              "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as response:
            data = json.load(response)
        return data["choices"][0]["message"]["content"]
