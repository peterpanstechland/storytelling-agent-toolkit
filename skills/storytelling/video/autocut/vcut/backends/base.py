from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Sequence

import cv2
import numpy as np


class BackendError(RuntimeError):
    pass


def load_image_jpeg(img: Path | bytes, max_width: int = 512, quality: int = 80) -> bytes:
    """Downscale + re-encode an image as JPEG to keep request cost low."""
    if isinstance(img, (bytes, bytearray)):
        arr = cv2.imdecode(np.frombuffer(img, np.uint8), cv2.IMREAD_COLOR)
    else:
        arr = cv2.imdecode(np.fromfile(str(img), dtype=np.uint8), cv2.IMREAD_COLOR)  # unicode-path safe
    if arr is None:
        raise BackendError(f"无法读取图片：{img if not isinstance(img, (bytes, bytearray)) else '<bytes>'}")
    h, w = arr.shape[:2]
    if w > max_width:
        arr = cv2.resize(arr, (max_width, int(h * max_width / w)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", arr, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise BackendError("JPEG 编码失败")
    return buf.tobytes()


class Backend(ABC):
    name: str = "base"
    vision_model: str = ""
    text_model: str = ""
    image_width: int = 512

    @abstractmethod
    def chat(self, prompt: str, *, system: str = "", images: Sequence[Path | bytes] = (),
             model: str | None = None, json_mode: bool = True, temperature: float = 0.3) -> str:
        """Return raw text reply."""

    def chat_json(self, prompt: str, *, system: str = "", images: Sequence[Path | bytes] = (),
                  model: str | None = None, temperature: float = 0.3, retries: int = 1) -> Any:
        from ..util import extract_json

        last_err: Exception | None = None
        for attempt in range(retries + 1):
            text = self.chat(prompt if attempt == 0 else prompt + "\n\n只输出合法 JSON，不要任何解释。",
                             system=system, images=images, model=model, json_mode=True, temperature=temperature)
            try:
                return extract_json(text)
            except ValueError as e:
                last_err = e
        raise BackendError(f"{self.name} 返回的不是合法 JSON：{last_err}")

    def supports_video(self) -> bool:
        return False

    def describe_video(self, video: Path, prompt: str, *, system: str = "") -> Any:  # pragma: no cover
        raise NotImplementedError
