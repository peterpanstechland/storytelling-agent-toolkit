from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from rich.console import Console

console = Console()


def info(msg: str) -> None:
    console.print(msg)


def warn(msg: str) -> None:
    console.print(f"[yellow]⚠ {msg}[/yellow]")


def ok(msg: str) -> None:
    console.print(f"[green]✓[/green] {msg}")


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def short_hash(*parts: Any, n: int = 10) -> str:
    h = hashlib.sha1("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()
    return h[:n]


def slugify(name: str) -> str:
    s = re.sub(r"[\\/:*?\"<>|\s]+", "_", name.strip())
    return s.strip("._") or "project"


def fmt_time(t: float) -> str:
    t = max(0.0, t)
    m, s = divmod(t, 60)
    return f"{int(m):02d}:{s:05.2f}"


def extract_json(text: str) -> Any:
    """Parse JSON from an LLM reply (tolerates ```json fences and leading prose)."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # find the first balanced {...} or [...]
    for open_c, close_c in (("{", "}"), ("[", "]")):
        start = text.find(open_c)
        if start < 0:
            continue
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            c = text[i]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
                continue
            if c == '"':
                in_str = True
            elif c == open_c:
                depth += 1
            elif c == close_c:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        break
    raise ValueError("模型回复里没有找到合法 JSON")
