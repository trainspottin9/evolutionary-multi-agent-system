"""Provider boundary: only course-permitted DeepSeek or HKGAI endpoints."""
import json
import time
import urllib.error
import urllib.request
from typing import Dict

from .credentials import load_key


class LLMError(RuntimeError):
    pass


class ChatProvider:
    def __init__(self, provider="deepseek", base_url=None, model=None, timeout=90):
        if provider not in ("deepseek", "hkgai"):
            raise ValueError("Only DeepSeek and HKGAI providers are permitted")
        self.provider = provider
        default_url = "https://api.deepseek.com" if provider == "deepseek" else "https://api1.hkgai.net/v1"
        self.base_url = (base_url or default_url).rstrip("/")
        if not self.base_url.startswith("https://"):
            raise ValueError("An HTTPS provider base URL is required")
        self.model = model or ("deepseek-chat" if provider == "deepseek" else "t2_hkgai-v3_fp8_1m_e7")
        self.timeout = timeout
        self.api_key = load_key(provider)
        if not self.api_key:
            raise LLMError("Missing %s_API_KEY; run 'python3 -m evo setup-hkgai-key' for HKGAI" % provider.upper())

    def complete_json(self, system: str, user: str, max_tokens=2000) -> Dict:
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system + "\nRespond with one valid JSON object."},
                         {"role": "user", "content": user}],
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
            "max_tokens": max_tokens,
            "stream": False,
        }
        data = json.dumps(payload).encode("utf-8")
        url = self.base_url + "/chat/completions"
        request = urllib.request.Request(url, data=data, headers={
            "Authorization": "Bearer " + self.api_key,
            "Content-Type": "application/json",
        })
        for attempt in range(3):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    body = json.load(response)
                choice = body["choices"][0]
                if choice.get("finish_reason") == "length":
                    raise LLMError("Model response was truncated")
                content = choice["message"].get("content") or ""
                if not content.strip():
                    raise LLMError("Model returned empty JSON")
                result = json.loads(content)
                if not isinstance(result, dict):
                    raise LLMError("Model returned non-object JSON")
                return result
            except urllib.error.HTTPError as exc:
                detail = exc.read(500).decode("utf-8", "replace")
                if exc.code not in (429, 500, 502, 503, 504) or attempt == 2:
                    raise LLMError("Provider HTTP %s: %s" % (exc.code, detail)) from exc
            except (urllib.error.URLError, TimeoutError) as exc:
                if attempt == 2:
                    raise LLMError("Provider unavailable: %s" % exc) from exc
            time.sleep(2 ** attempt)
        raise LLMError("Provider failed after retries")
