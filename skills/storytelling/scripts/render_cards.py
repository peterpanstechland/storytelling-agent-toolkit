#!/usr/bin/env python3
"""Render portable editorial card specs to PNG and a local HTML contact sheet.

Requires Pillow. The JSON contract is documented in references/visual-editorial.md.
No network access or asset generation is performed.
"""
from __future__ import annotations

import argparse
import html
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any

try:
    from PIL import Image, ImageDraw, ImageFont, ImageOps
except ImportError as exc:
    raise SystemExit("Pillow is required. Install it with: python -m pip install Pillow") from exc

TOOL = "storytelling-card-renderer"
LAYOUTS = {"cover", "photo-overlay", "stat", "quote", "process"}
COLORS = {"background": "#101019", "foreground": "#f6f3eb", "muted": "#bcb7c9", "accent": "#64d8ee"}
CJK = re.compile(r"[\u2e80-\u9fff\uac00-\ud7ff\uf900-\ufaff\U00020000-\U0002ffff]")
ID = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}\Z")


class CardError(ValueError):
    pass


def text(value: Any, key: str, required: bool = False) -> str:
    if value is None and not required:
        return ""
    if not isinstance(value, str) or (required and not value.strip()):
        raise CardError(f"{key} must be {'a nonempty' if required else 'a'} string")
    if len(value) > 4000 or any(ord(c) < 32 and c not in "\n\t" for c in value):
        raise CardError(f"{key}: maximum 4000 characters; control characters are unsupported")
    return value.replace("\t", "  ")


def dimension(value: Any, key: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 320 <= value <= 8192:
        raise CardError(f"{key} must be an integer from 320 to 8192")
    return value


def color(value: Any, key: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        raise CardError(f"{key} must be a six-digit hex color")
    return value


def resolve_asset(value: Any, base: Path, key: str) -> Path:
    value = text(value, key, True)
    rel = Path(value)
    if rel.is_absolute() or re.match(r"[a-zA-Z]+:", value):
        raise CardError(f"{key} must be a local path relative to the JSON file")
    resolved = (base / rel).resolve()
    if not resolved.is_relative_to(base.resolve()):
        raise CardError(f"{key} must remain inside the JSON file's directory")
    if not resolved.is_file():
        raise CardError(f"{key} not found: {value}")
    return resolved


def load_spec(path: Path) -> dict[str, Any]:
    try:
        spec = json.loads(path.read_text(encoding="utf-8"), parse_constant=lambda x: (_ for _ in ()).throw(CardError(f"non-finite JSON value {x}")))
    except (OSError, json.JSONDecodeError) as exc:
        raise CardError(f"Cannot read card spec: {exc}") from exc
    if not isinstance(spec, dict) or type(spec.get("version")) is not int or spec.get("version") != 1:
        raise CardError("Card spec must be an object with version: 1")
    defaults = spec.get("defaults", {})
    if not isinstance(defaults, dict):
        raise CardError("defaults must be an object")
    spec["title"] = text(spec.get("title", "Story cards"), "title", True)
    spec["author"] = text(spec.get("author", ""), "author")
    cards = spec.get("cards")
    if not isinstance(cards, list) or not 1 <= len(cards) <= 50:
        raise CardError("cards must contain 1 to 50 card objects")
    seen, total_pixels = set(), 0
    for index, card in enumerate(cards):
        prefix = f"cards[{index}]"
        if not isinstance(card, dict):
            raise CardError(f"{prefix} must be an object")
        cid = card.get("id")
        if not isinstance(cid, str) or not ID.fullmatch(cid) or cid in seen:
            raise CardError(f"{prefix}.id must be a unique, safe filename identifier")
        seen.add(cid)
        if card.get("layout") not in LAYOUTS:
            raise CardError(f"{prefix}.layout must be one of {', '.join(sorted(LAYOUTS))}")
        for key in ("width", "height"):
            card[key] = dimension(card.get(key, defaults.get(key, 1080 if key == "width" else 1440)), f"{prefix}.{key}")
        pixels = card["width"] * card["height"]
        total_pixels += pixels
        if pixels > 32_000_000 or total_pixels > 128_000_000:
            raise CardError("Render limit: 32 megapixels per card, 128 megapixels per batch; split this batch")
        for key, default in COLORS.items():
            card[key] = color(card.get(key, defaults.get(key, default)), f"{prefix}.{key}")
        for key in ("title", "body", "eyebrow", "footnote", "alt", "value", "meaning", "source", "attribution"):
            required = key == "title" or (card["layout"] == "stat" and key in {"value", "meaning", "source"})
            card[key] = text(card.get(key), f"{prefix}.{key}", required)
        if card["layout"] == "photo-overlay":
            card["_image"] = resolve_asset(card.get("image"), path.parent, f"{prefix}.image")
            focus = card.get("image_focus", [0.5, 0.5])
            if not isinstance(focus, list) or len(focus) != 2 or any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) or not 0 <= x <= 1 for x in focus):
                raise CardError(f"{prefix}.image_focus must be [x, y], each from 0 to 1")
            card["image_focus"] = focus
        if card["layout"] == "process":
            nodes = card.get("nodes")
            if not isinstance(nodes, list) or not 2 <= len(nodes) <= 5:
                raise CardError(f"{prefix}.nodes must contain 2 to 5 nodes")
            for ni, node in enumerate(nodes):
                if not isinstance(node, dict):
                    raise CardError(f"{prefix}.nodes[{ni}] must be an object")
                node["title"] = text(node.get("title"), f"{prefix}.nodes[{ni}].title", True)
                node["body"] = text(node.get("body"), f"{prefix}.nodes[{ni}].body")
    return spec


def _glyph(font: ImageFont.FreeTypeFont, ch: str) -> tuple:
    mask = font.getmask(ch)
    return mask.size, bytes(mask)


def has_glyphs(font_path: Path, content: str) -> bool:
    try:
        font = ImageFont.truetype(str(font_path), 32)
        missing = _glyph(font, "\U0010ffff")
        return all(_glyph(font, ch) != missing for ch in set(content) if CJK.match(ch))
    except (OSError, ValueError):
        return False


def choose_font(explicit: str | None, content: str) -> Path:
    need_cjk = bool(CJK.search(content))
    if explicit:
        path = Path(explicit).expanduser().resolve()
        if not path.is_file():
            raise CardError(f"Font not found: {path}")
        try:
            ImageFont.truetype(str(path), 32)
        except OSError as exc:
            raise CardError(f"Cannot load font: {path}") from exc
        if need_cjk and not has_glyphs(path, content):
            raise CardError("Selected font lacks required CJK glyphs. Use --font with Noto Sans CJK / Source Han Sans or another font covering this text.")
        return path
    candidates = []
    try:
        query = "sans:lang=zh" if need_cjk else "sans"
        result = subprocess.run(["fc-match", "-f", "%{file}\n", query], capture_output=True, text=True, timeout=3, check=False)
        candidates += [Path(p) for p in result.stdout.splitlines() if p]
    except (OSError, subprocess.TimeoutExpired):
        pass
    candidates += [Path(p) for p in [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/PingFang.ttc",
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/arial.ttf",
    ]]
    for path in candidates:
        if path.is_file() and (not need_cjk or has_glyphs(path, content)):
            try:
                ImageFont.truetype(str(path), 32)
                return path
            except OSError:
                continue
    raise CardError("No suitable font found. Install Noto Sans CJK (Ubuntu: fonts-noto-cjk) for Chinese, or pass --font /path/to/font.ttf or .ttc.")


def wrap_text(draw: ImageDraw.ImageDraw, value: str, font: ImageFont.FreeTypeFont, width: int) -> list[str]:
    lines = []
    for paragraph in value.split("\n"):
        # Keep Latin words whole when possible; Chinese characters are break opportunities.
        tokens = re.findall(r"[A-Za-z0-9_]+(?:['’.-][A-Za-z0-9_]+)*|[^A-Za-z0-9_]", paragraph)
        current = ""
        for token in tokens:
            trial = current + token
            if draw.textlength(trial, font=font) <= width:
                current = trial
                continue
            if current.strip():
                lines.append(current.rstrip())
                current = ""
            token = token.lstrip()
            for ch in token:
                if draw.textlength(current + ch, font=font) > width:
                    if not current:
                        raise CardError("Text column is narrower than a glyph")
                    lines.append(current.rstrip())
                    current = ""
                current += ch
        lines.append(current.rstrip())
    return lines


class Painter:
    def __init__(self, image: Image.Image, card: dict, font_path: Path):
        self.im, self.draw, self.card, self.font_path = image, ImageDraw.Draw(image), card, font_path
        self.scale = card["width"] / 1080
        self.boxes = []

    def block(self, value: str, box: tuple[int, int, int, int], size: int, minimum: int, fill: str | None = None, align: str = "left"):
        if not value:
            return
        x, y, w, h = [round(v) for v in box]
        chosen = None
        for fs in range(max(1, round(size * self.scale)), max(1, round(minimum * self.scale)) - 1, -1):
            font = ImageFont.truetype(str(self.font_path), fs)
            try:
                lines = wrap_text(self.draw, value, font, w)
            except CardError:
                continue
            # Font metrics reserve descenders even for short Latin lines.
            ascent, descent = font.getmetrics()
            step = math.ceil((ascent + descent) * 1.12)
            height = step * len(lines)
            if height <= h and all(self.draw.textlength(line, font=font) <= w for line in lines):
                chosen = (font, lines, step, fs, height)
                break
        if chosen is None:
            raise CardError(f"Card '{self.card['id']}' text overflows: {value[:55]!r}. Shorten the copy, split the card or increase its height.")
        font, lines, step, fs, height = chosen
        for line in lines:
            line_x = x + (w - self.draw.textlength(line, font=font)) / 2 if align == "center" else x
            self.draw.text((round(line_x), y), line, font=font, fill=fill or self.card["foreground"], anchor="lt")
            y += step
        self.boxes.append({"text": value, "box": [x, box[1], w, h], "font_size": fs, "line_count": len(lines), "used_height": height})


def render_card(card: dict, spec: dict, font_path: Path, index: int) -> tuple[Image.Image, list]:
    w, h = card["width"], card["height"]
    im = Image.new("RGB", (w, h), card["background"])
    p = Painter(im, card, font_path)
    m, cw = round(w * .065), round(w * .87)
    footer_y = round(h * .915)
    s = w / 1080
    if card["layout"] == "photo-overlay":
        try:
            with Image.open(card["_image"]) as src:
                if src.width * src.height > 80_000_000:
                    raise CardError(f"Card '{card['id']}' source image exceeds 80 megapixels")
                im.paste(ImageOps.fit(ImageOps.exif_transpose(src).convert("RGB"), (w, h), centering=tuple(card["image_focus"])))
        except (OSError, Image.DecompressionBombError) as exc:
            raise CardError(f"Cannot open image for '{card['id']}': {exc}") from exc
        shade = Image.new("RGBA", (1, h))
        for y in range(h):
            opacity = int(20 + 220 * min(1, max(0, (y / h - .25) / .55)))
            shade.putpixel((0, y), (5, 7, 15, opacity))
        im = Image.alpha_composite(im.convert("RGBA"), shade.resize((w, h))).convert("RGB")
        p = Painter(im, card, font_path)
    else:
        # Geometric hierarchy is intentionally decorative, never represented as measured data.
        p.draw.line([(m, .21*h), (w-m, .21*h)], fill=card["accent"], width=max(1, round(2*s)))
        if card["layout"] == "cover":
            for radius in (.40, .32, .24):
                x, y, r = .88*w, .40*h, radius*w
                p.draw.ellipse((x-r, y-r, x+r, y+r), outline=card["accent"], width=max(1, round(2*s)))
            p.draw.rectangle((0, .24*h, w*.73, .76*h), fill=card["background"])
    p.block(card["eyebrow"], (m, h*.055, cw, h*.07), 26, 20, card["accent"])
    layout = card["layout"]
    if layout == "cover":
        p.block(card["title"], (m, h*.25, cw*.85, h*.32), 82, 48)
        p.block(card["body"], (m, h*.63, cw, h*.18), 35, 27, card["muted"])
    elif layout == "photo-overlay":
        p.block(card["title"], (m, h*.51, cw, h*.21), 70, 44)
        p.block(card["body"], (m, h*.75, cw, h*.13), 32, 25)
    elif layout == "stat":
        p.block(card["title"], (m, h*.12, cw, h*.085), 40, 28)
        p.block(card["value"], (m, h*.27, cw, h*.22), 150, 75, card["accent"])
        p.block(card["meaning"], (m, h*.53, cw, h*.20), 39, 28)
        p.block(card["source"], (m, h*.77, cw, h*.11), 25, 20, card["muted"])
    elif layout == "quote":
        p.block("“", (m, h*.24, cw, h*.15), 120, 80, card["accent"])
        p.block(card["title"], (m, h*.38, cw, h*.32), 64, 39)
        p.block(card["attribution"] or card["body"], (m, h*.76, cw, h*.10), 28, 22, card["muted"])
    elif layout == "process":
        p.block(card["title"], (m, h*.12, cw, h*.085), 40, 28)
        nodes = card["nodes"]
        top, bottom = h*.26, h*.86
        span = (bottom-top)/len(nodes)
        gutter = w*.10
        for i, node in enumerate(nodes):
            ny = top+i*span
            p.block(f"{i+1:02d}", (m, ny, gutter*.85, span*.4), 30, 20, card["accent"])
            p.block(node["title"], (m+gutter, ny, cw-gutter, span*.36), 35, 25)
            p.block(node["body"], (m+gutter, ny+span*.40, cw-gutter, span*.48), 27, 20, card["muted"])
            if i < len(nodes)-1:
                p.draw.line((m+gutter, ny+span*.93, w-m, ny+span*.93), fill=card["muted"], width=1)
    p.draw.line((m, footer_y-12*s, w-m, footer_y-12*s), fill=card["muted"], width=1)
    footer = card["footnote"] or spec["author"]
    p.block(footer, (m, footer_y, cw*.88, h*.06), 21, 17, card["muted"])
    p.block(f"{index+1:02d}", (w-m-w*.07, footer_y, w*.07, h*.06), 22, 17, card["accent"], "center")
    return im, p.boxes


def export(spec_path: Path, output: Path, font: str | None = None, force: bool = False) -> dict:
    spec_path, output = spec_path.resolve(), output.resolve()
    spec = load_spec(spec_path)
    content = json.dumps(spec, ensure_ascii=False, default=str)
    font_path = choose_font(font, content)
    files = [f"{c['id']}.png" for c in spec["cards"]] + ["index.html", "manifest.json"]
    owned = set()
    previous = output / "manifest.json"
    if previous.is_file():
        try:
            old = json.loads(previous.read_text(encoding="utf-8"))
            if old.get("generator") == TOOL:
                owned = set(old.get("files", []))
        except (ValueError, OSError, TypeError):
            pass
    if output.exists() and not output.is_dir():
        raise CardError(f"Output is not a directory: {output}")
    for filename in files:
        dest = output / filename
        if dest.exists() and (not force or filename not in owned or not dest.is_file() or dest.is_symlink()):
            raise CardError(f"Refusing to overwrite {dest.name}. Use a fresh output directory, or --force only for files owned by a previous render.")
    manifest = {"generator": TOOL, "version": 1, "title": spec["title"], "font": font_path.name, "files": files, "cards": []}
    with tempfile.TemporaryDirectory(prefix="storytelling-cards-") as tmp:
        stage = Path(tmp)
        for i, card in enumerate(spec["cards"]):
            image, boxes = render_card(card, spec, font_path, i)
            image.save(stage / f"{card['id']}.png", optimize=True)
            manifest["cards"].append({"id": card["id"], "file": f"{card['id']}.png", "width": card["width"], "height": card["height"], "alt": card["alt"] or card["title"], "text_boxes": boxes})
        preview = "<!doctype html><html lang='zh-CN'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>" + html.escape(spec["title"]) + "</title><style>body{background:#20202a;color:#fff;font:16px system-ui;margin:24px}main{display:flex;flex-wrap:wrap;gap:24px}figure{margin:0;max-width:420px}img{width:100%;height:auto;display:block}figcaption{padding:10px 0;line-height:1.5}</style><h1>" + html.escape(spec["title"]) + "</h1><main>"
        for c in manifest["cards"]:
            preview += f"<figure><img src='{c['file']}' alt='{html.escape(c['alt'], quote=True)}'><figcaption>{html.escape(c['alt'])}</figcaption></figure>"
        preview += "</main></html>"
        (stage / "index.html").write_text(preview, encoding="utf-8")
        (stage / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        output.mkdir(parents=True, exist_ok=True)
        for filename in files:
            dest = output / filename
            # Each file is replaced atomically on the destination filesystem.
            with tempfile.NamedTemporaryFile(dir=output, prefix=".card-", delete=False) as handle:
                temporary = Path(handle.name)
            try:
                shutil.copyfile(stage / filename, temporary)
                os.replace(temporary, dest)
            finally:
                temporary.unlink(missing_ok=True)
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec", type=Path, help="cards JSON file")
    parser.add_argument("--output", type=Path, required=True, help="destination directory")
    parser.add_argument("--font", help="font file with all required glyphs")
    parser.add_argument("--force", action="store_true", help="replace only files owned by a previous renderer manifest")
    args = parser.parse_args(argv)
    try:
        manifest = export(args.spec, args.output, args.font, args.force)
    except (CardError, OSError) as exc:
        parser.exit(2, f"error: {exc}\n")
    print(f"Rendered {len(manifest['cards'])} cards: {args.output.resolve() / 'index.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
