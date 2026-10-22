"""Google Gemini via REST (no SDK needed).

* generateContent (v1beta) for text + inline images; the Interactions API is the newer
  recommended surface, but generateContent "remains fully supported" per Google docs (2026-06).
* Files API resumable upload for short low-res proxy videos (vision_mode: video).
"""
from __future__ import annotations

import base64
import mimetypes
import time
from pathlib import Path
from typing import Any, Sequence

import httpx

from .base import Backend, BackendError, load_image_jpeg


class GeminiBackend(Backend):
    name = "gemini"

    def __init__(self, api_key: str, *, base_url: str = "https://generativelanguage.googleapis.com",
                 vision_model: str = "gemini-3.8-flash", text_model: str = "gemini-3.8-flash",
                 vision_mode: str = "frames", http_client: httpx.Client | None = None, timeout: float = 300):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.vision_model = vision_model
        self.text_model = text_model
        self.vision_mode = vision_mode
        self.client = http_client or httpx.Client(timeout=timeout)

    @property
    def _headers(self) -> dict:
        return {"x-goog-api-key": self.api_key, "Content-Type": "application/json"}

    def _generate(self, model: str, parts: list[dict], system: str, json_mode: bool, temperature: float) -> str:
        body: dict[str, Any] = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"temperature": temperature},
        }
        if json_mode:
            body["generationConfig"]["responseMimeType"] = "application/json"
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        url = f"{self.base_url}/v1beta/models/{model}:generateContent"
        for attempt in range(3):
            try:
                r = self.client.post(url, json=body, headers=self._headers)
            except httpx.HTTPError as e:
                if attempt == 2:
                    raise BackendError(f"gemini 请求失败：{e}") from e
                time.sleep(2 * (attempt + 1))
                continue
            if r.status_code in (429, 500, 503) and attempt < 2:
                time.sleep(4 * (attempt + 1))
                continue
            if r.status_code >= 400:
                raise BackendError(f"gemini HTTP {r.status_code}: {r.text[:500]}")
            data = r.json()
            try:
                cand = data["candidates"][0]
                texts = [p.get("text", "") for p in cand["content"]["parts"] if not p.get("thought")]
                return "".join(texts)
            except (KeyError, IndexError, TypeError) as e:
                raise BackendError(f"gemini 返回格式异常：{str(data)[:300]}") from e
        raise BackendError("gemini 多次重试失败")

    def chat(self, prompt: str, *, system: str = "", images: Sequence[Path | bytes] = (),
             model: str | None = None, json_mode: bool = True, temperature: float = 0.3) -> str:
        parts: list[dict] = []
        for img in images:
            parts.append({"inline_data": {"mime_type": "image/jpeg",
                                          "data": base64.b64encode(load_image_jpeg(img, self.image_width)).decode("ascii")}})
        parts.append({"text": prompt})
        return self._generate(model or (self.vision_model if images else self.text_model), parts, system, json_mode, temperature)

    # ---------- video ----------
    def supports_video(self) -> bool:
        return self.vision_mode == "video"

    def upload_file(self, path: Path) -> dict:
        path = Path(path)
        mime = mimetypes.guess_type(path.name)[0] or "video/mp4"
        size = path.stat().st_size
        start = self.client.post(
            f"{self.base_url}/upload/v1beta/files",
            headers={"x-goog-api-key": self.api_key, "X-Goog-Upload-Protocol": "resumable",
                     "X-Goog-Upload-Command": "start", "X-Goog-Upload-Header-Content-Length": str(size),
                     "X-Goog-Upload-Header-Content-Type": mime, "Content-Type": "application/json"},
            json={"file": {"display_name": path.name}},
        )
        if start.status_code >= 400:
            raise BackendError(f"gemini 上传初始化失败 HTTP {start.status_code}: {start.text[:300]}")
        upload_url = start.headers.get("x-goog-upload-url")
        if not upload_url:
            raise BackendError("gemini 上传初始化没有返回 upload url")
        r = self.client.post(upload_url, content=path.read_bytes(),
                             headers={"Content-Length": str(size), "X-Goog-Upload-Offset": "0",
                                      "X-Goog-Upload-Command": "upload, finalize"})
        if r.status_code >= 400:
            raise BackendError(f"gemini 上传失败 HTTP {r.status_code}: {r.text[:300]}")
        f = r.json().get("file", {})
        # wait for ACTIVE
        for _ in range(60):
            if f.get("state") in (None, "ACTIVE"):
                break
            if f.get("state") == "FAILED":
                raise BackendError("gemini 文件处理失败")
            time.sleep(3)
            g = self.client.get(f"{self.base_url}/v1beta/{f['name']}", headers=self._headers)
            f = g.json()
        f.setdefault("mimeType", mime)
        return f

    def describe_video(self, video: Path, prompt: str, *, system: str = "") -> Any:
        from ..util import extract_json

        f = self.upload_file(video)
        parts = [{"file_data": {"mime_type": f.get("mimeType", "video/mp4"), "file_uri": f["uri"]}}, {"text": prompt}]
        text = self._generate(self.vision_model, parts, system, True, 0.2)
        try:
            self.client.delete(f"{self.base_url}/v1beta/{f['name']}", headers=self._headers)
        except Exception:  # noqa: BLE001 - cleanup is best-effort (files expire after 48h anyway)
            pass
        return extract_json(text)
