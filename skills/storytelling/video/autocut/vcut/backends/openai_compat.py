"""OpenAI-compatible chat/completions client (DashScope compatible-mode, Ollama /v1, etc.)."""
from __future__ import annotations

import base64
import time
from pathlib import Path
from typing import Sequence

import httpx

from .base import Backend, BackendError, load_image_jpeg


class OpenAICompatBackend(Backend):
    def __init__(self, name: str, base_url: str, api_key: str, *, vision_model: str, text_model: str,
                 json_mode: bool = True, http_client: httpx.Client | None = None, timeout: float = 180,
                 extra_body: dict | None = None):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.vision_model = vision_model
        self.text_model = text_model
        self.json_mode = json_mode
        self.extra_body = extra_body or {}
        self.client = http_client or httpx.Client(timeout=timeout)

    def _content(self, prompt: str, images: Sequence[Path | bytes]) -> list[dict] | str:
        if not images:
            return prompt
        parts: list[dict] = []
        for img in images:
            b64 = base64.b64encode(load_image_jpeg(img, self.image_width)).decode("ascii")
            parts.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})
        parts.append({"type": "text", "text": prompt})
        return parts

    def chat(self, prompt: str, *, system: str = "", images: Sequence[Path | bytes] = (),
             model: str | None = None, json_mode: bool = True, temperature: float = 0.3) -> str:
        model = model or (self.vision_model if images else self.text_model)
        messages: list[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": self._content(prompt, images)})
        body: dict = {"model": model, "messages": messages, "temperature": temperature, **self.extra_body}
        if json_mode and self.json_mode:
            body["response_format"] = {"type": "json_object"}
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        url = f"{self.base_url}/chat/completions"
        for attempt in range(3):
            try:
                r = self.client.post(url, json=body, headers=headers)
            except httpx.HTTPError as e:
                if attempt == 2:
                    raise BackendError(f"{self.name} 请求失败：{e}") from e
                time.sleep(2 * (attempt + 1))
                continue
            optional = [k for k in ("response_format", *self.extra_body) if k in body]
            if r.status_code == 400 and optional:
                # some servers/models reject json mode or vendor flags -> retry with a plain request
                for k in optional:
                    body.pop(k, None)
                continue
            if r.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(3 * (attempt + 1))
                continue
            if r.status_code >= 400:
                raise BackendError(f"{self.name} HTTP {r.status_code}: {r.text[:500]}")
            data = r.json()
            try:
                return data["choices"][0]["message"]["content"] or ""
            except (KeyError, IndexError, TypeError) as e:
                raise BackendError(f"{self.name} 返回格式异常：{str(data)[:300]}") from e
        raise BackendError(f"{self.name} 多次重试失败")
