"""Cloud backends are tested against mocked HTTP (no API keys on the build box)."""
import shutil
import unittest

import autocut_support as S

S.require_autocut()  # 缺少 autocut 依赖时整个模块跳过

import base64
import json
import cv2
import httpx
import numpy as np
from vcut.backends import BackendError, dashscope_base_url, get_backend
from vcut.backends.gemini import GeminiBackend
from vcut.backends.openai_compat import OpenAICompatBackend
from vcut.util import extract_json


def _make_jpg(tmp_path):
    p = tmp_path / "f.jpg"
    cv2.imwrite(str(p), np.full((720, 1280, 3), 128, np.uint8))
    return p


class AutocutBackendsTests(unittest.TestCase):
    tmp_path = S.tmp_path_factory
    monkeypatch = S.monkeypatch_factory

    def test_extract_json_variants(self):
        assert extract_json('{"a": 1}') == {"a": 1}
        assert extract_json('好的：\n```json\n{"a": [1, 2]}\n```') == {"a": [1, 2]}
        assert extract_json('前缀 {"a": "x}y"} 后缀') == {"a": "x}y"}
        with S.raises(ValueError):
            extract_json("没有 JSON")

    def test_openai_compat_request_shape(self):
        jpg = _make_jpg(self.tmp_path())
        seen = {}

        def handler(req: httpx.Request):
            seen["url"] = str(req.url)
            seen["auth"] = req.headers["authorization"]
            seen["body"] = json.loads(req.content)
            return httpx.Response(200, json={"choices": [{"message": {"content": '{"shots": []}'}}]})

        b = OpenAICompatBackend("dashscope", "https://example.com/compatible-mode/v1", "sk-test",
                                vision_model="qwen3-vl-flash", text_model="qwen3-vl-plus",
                                http_client=httpx.Client(transport=httpx.MockTransport(handler)),
                                extra_body={"enable_thinking": False})
        b.image_width = 256
        assert b.chat_json("描述", images=[jpg]) == {"shots": []}
        assert seen["url"] == "https://example.com/compatible-mode/v1/chat/completions"
        assert seen["auth"] == "Bearer sk-test"
        body = seen["body"]
        assert body["model"] == "qwen3-vl-flash"            # images -> vision model
        assert body["response_format"] == {"type": "json_object"}
        assert body["enable_thinking"] is False
        parts = body["messages"][-1]["content"]
        assert parts[0]["type"] == "image_url" and parts[0]["image_url"]["url"].startswith("data:image/jpeg;base64,")
        img = cv2.imdecode(np.frombuffer(base64.b64decode(parts[0]["image_url"]["url"].split(",", 1)[1]), np.uint8), 1)
        assert img.shape[1] == 256                           # downscaled before upload
        b.chat_json("纯文本")
        assert seen["body"]["model"] == "qwen3-vl-plus"     # text-only -> text model

    def test_openai_compat_retries_without_json_mode_on_400(self):
        calls = []

        def handler(req):
            body = json.loads(req.content)
            calls.append(body)
            if "response_format" in body:
                return httpx.Response(400, json={"error": "response_format not supported"})
            return httpx.Response(200, json={"choices": [{"message": {"content": '```json\n{"ok": true}\n```'}}]})

        b = OpenAICompatBackend("ollama", "http://localhost:11434/v1", "ollama", vision_model="v", text_model="t",
                                http_client=httpx.Client(transport=httpx.MockTransport(handler)))
        assert b.chat_json("hi") == {"ok": True}
        assert len(calls) == 2 and "response_format" not in calls[1]

    def test_openai_compat_http_error(self):
        b = OpenAICompatBackend("x", "http://h/v1", "k", vision_model="v", text_model="t",
                                http_client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(401, text="bad key"))))
        with S.raises(BackendError):
            b.chat("hi")

    def test_gemini_generate_and_video_upload(self):
        tmp_path = self.tmp_path()
        jpg = _make_jpg(self.tmp_path())
        video = tmp_path / "p.mp4"
        video.write_bytes(b"\x00" * 100)
        log = []

        def handler(req: httpx.Request):
            log.append((req.method, str(req.url), dict(req.headers)))
            url = str(req.url)
            if url.endswith("/upload/v1beta/files"):
                assert req.headers["x-goog-upload-command"] == "start"
                return httpx.Response(200, headers={"x-goog-upload-url": "https://upload.example/session1"})
            if url == "https://upload.example/session1":
                assert req.headers["x-goog-upload-command"] == "upload, finalize"
                return httpx.Response(200, json={"file": {"name": "files/abc", "uri": "https://g/files/abc",
                                                          "mimeType": "video/mp4", "state": "PROCESSING"}})
            if url.endswith("/v1beta/files/abc") and req.method == "GET":
                return httpx.Response(200, json={"name": "files/abc", "uri": "https://g/files/abc", "mimeType": "video/mp4",
                                                 "state": "ACTIVE"})
            if url.endswith("/v1beta/files/abc") and req.method == "DELETE":
                return httpx.Response(200, json={})
            if ":generateContent" in url:
                body = json.loads(req.content)
                assert req.headers["x-goog-api-key"] == "g-key"
                assert body["generationConfig"]["responseMimeType"] == "application/json"
                kinds = [list(p)[0] for p in body["contents"][0]["parts"]]
                text = json.dumps({"kinds": kinds, "shots": [{"idx": 0, "category": "demo"}]})
                return httpx.Response(200, json={"candidates": [{"content": {"parts": [
                    {"text": "thinking...", "thought": True}, {"text": text}]}}]})
            return httpx.Response(404)

        import vcut.backends.gemini as gm
        gm.time.sleep = lambda s: None  # no real waiting in tests
        b = GeminiBackend("g-key", vision_mode="video", http_client=httpx.Client(transport=httpx.MockTransport(handler)))
        r = b.chat_json("看图", images=[jpg])
        assert r["kinds"] == ["inline_data", "text"]
        assert "gemini-3.8-flash:generateContent" in [u for _, u, _ in log][-1]
        out = b.describe_video(video, "分析")
        assert out["kinds"] == ["file_data", "text"]
        assert any(m == "DELETE" for m, _, _ in log)

    def test_get_backend_requires_keys(self):
        monkeypatch = self.monkeypatch()
        monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        assert get_backend("none") is None
        with S.raises(BackendError):
            get_backend("dashscope")
        with S.raises(BackendError):
            get_backend("gemini")
        assert get_backend("ollama").base_url.endswith(":11434/v1")
        with S.raises(BackendError):
            get_backend("nope")

    def test_dashscope_url(self):
        monkeypatch = self.monkeypatch()
        monkeypatch.delenv("DASHSCOPE_BASE_URL", raising=False)
        monkeypatch.delenv("DASHSCOPE_WORKSPACE_ID", raising=False)
        assert dashscope_base_url({}) == "https://dashscope.aliyuncs.com/compatible-mode/v1"
        monkeypatch.setenv("DASHSCOPE_WORKSPACE_ID", "ws123")
        assert dashscope_base_url({"region": "cn-beijing"}) == "https://ws123.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
        monkeypatch.setenv("DASHSCOPE_BASE_URL", "https://custom/v1/")
        assert dashscope_base_url({}) == "https://custom/v1"

