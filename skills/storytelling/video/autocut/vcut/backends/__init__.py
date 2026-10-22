"""Pluggable vision/LLM backends.

  none       离线：不调用任何模型（启发式）
  dashscope  阿里云百炼 Qwen-VL（OpenAI 兼容接口）
  gemini     Google Gemini（REST generateContent + Files API 上传视频）
  ollama     本地 Ollama（OpenAI 兼容接口），如 qwen3-vl:8b-instruct
"""
from __future__ import annotations

import os

from .. import config
from .base import Backend, BackendError
from .gemini import GeminiBackend
from .openai_compat import OpenAICompatBackend

__all__ = ["Backend", "BackendError", "get_backend", "backend_name_for"]


def backend_name_for(project_data: dict | None = None, override: str | None = None) -> str:
    if override:
        return override
    if project_data and project_data.get("backend"):
        return str(project_data["backend"])
    return str(config.settings().get("backend") or "none")


def dashscope_base_url(cfg: dict) -> str:
    if os.environ.get("DASHSCOPE_BASE_URL"):
        return os.environ["DASHSCOPE_BASE_URL"].rstrip("/")
    ws = os.environ.get("DASHSCOPE_WORKSPACE_ID")
    region = os.environ.get("DASHSCOPE_REGION") or cfg.get("region") or "cn-beijing"
    if ws:
        return f"https://{ws}.{region}.maas.aliyuncs.com/compatible-mode/v1"
    return "https://dashscope.aliyuncs.com/compatible-mode/v1"


def get_backend(name: str, http_client=None) -> Backend | None:
    """Return a backend instance, or None for 'none'. Raises BackendError if misconfigured."""
    name = (name or "none").lower()
    if name in ("none", "", "off", "heuristic"):
        return None
    bcfg = (config.settings().get("backends") or {}).get(name) or {}
    if name == "dashscope":
        key = os.environ.get(bcfg.get("api_key_env", "DASHSCOPE_API_KEY"), "")
        if not key:
            raise BackendError("没有找到 DASHSCOPE_API_KEY 环境变量（PowerShell: setx DASHSCOPE_API_KEY \"sk-...\"，然后重开终端）")
        return OpenAICompatBackend(
            "dashscope", dashscope_base_url(bcfg), key,
            vision_model=os.environ.get("VCUT_VISION_MODEL") or bcfg.get("vision_model", "qwen3-vl-flash"),
            text_model=os.environ.get("VCUT_TEXT_MODEL") or bcfg.get("text_model", "qwen3-vl-plus"),
            json_mode=bcfg.get("json_mode", True), http_client=http_client,
            extra_body={"enable_thinking": False},
        )
    if name == "ollama":
        base = bcfg.get("base_url", "http://localhost:11434/v1")
        host = os.environ.get("OLLAMA_HOST")
        if host:
            host = host if host.startswith("http") else f"http://{host}"
            base = host.rstrip("/") + "/v1"
        return OpenAICompatBackend(
            "ollama", base, "ollama",
            vision_model=os.environ.get("VCUT_VISION_MODEL") or bcfg.get("vision_model", "qwen3-vl:8b-instruct"),
            text_model=os.environ.get("VCUT_TEXT_MODEL") or bcfg.get("text_model", "qwen3-vl:8b-instruct"),
            json_mode=bcfg.get("json_mode", True), http_client=http_client, timeout=600,
        )
    if name == "gemini":
        key = os.environ.get(bcfg.get("api_key_env", "GEMINI_API_KEY"), "") or os.environ.get("GOOGLE_API_KEY", "")
        if not key:
            raise BackendError("没有找到 GEMINI_API_KEY 环境变量（PowerShell: setx GEMINI_API_KEY \"...\"，然后重开终端）")
        return GeminiBackend(
            key, base_url=bcfg.get("base_url", "https://generativelanguage.googleapis.com"),
            vision_model=os.environ.get("VCUT_VISION_MODEL") or bcfg.get("vision_model", "gemini-3.8-flash"),
            text_model=os.environ.get("VCUT_TEXT_MODEL") or bcfg.get("text_model", "gemini-3.8-flash"),
            vision_mode=bcfg.get("vision_mode", "frames"), http_client=http_client,
        )
    raise BackendError(f"未知后端：{name}（可选 none / dashscope / gemini / ollama）")
