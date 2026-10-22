#!/usr/bin/env python3
"""Original title-card grain, bloom, vignette and a small particle layer.

These are not ports. three.quarks (MIT) and react-postprocessing (MIT wrapper
around the Zlib pmndrs/postprocessing shaders) were surveyed and left upstream.
Nothing from those repositories is copied here. See references/fx-sources.md.
"""
import argparse
import math
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter


class LookError(ValueError):
    pass


def unit_hash(n):
    n = int(n) & 0xFFFFFFFF
    n ^= (n >> 16)
    n = (n * 0x7FEB352D) & 0xFFFFFFFF
    n ^= (n >> 15)
    n = (n * 0x846CA68B) & 0xFFFFFFFF
    n ^= (n >> 16)
    return n / 4294967296


def _rgb(image):
    if image.mode != "RGB":
        return image.convert("RGB")
    return image


def grain(image, amount=0.08, seed=1):
    """Add the same luma noise for a given seed. amount is a fraction of full scale."""
    if amount < 0 or amount > 1:
        raise LookError("grain amount must be between 0 and 1")
    source = _rgb(image)
    output = source.copy()
    src, dst = source.load(), output.load()
    width, height = source.size
    scale = amount * 255
    for y in range(height):
        for x in range(width):
            jitter = (unit_hash(seed * 1_000_003 + y * width + x) * 2 - 1) * scale
            dst[x, y] = tuple(max(0, min(255, int(channel + jitter))) for channel in src[x, y])
    return output


def bloom(image, threshold=200, radius=6, strength=0.65):
    """Add a blurred copy of the highlights back onto the picture."""
    source = _rgb(image)
    luma = source.convert("L")
    mask = luma.point(lambda value: 255 if value >= threshold else 0)
    black = Image.new("RGB", source.size, 0)
    highlights = Image.composite(source, black, mask)
    blurred = highlights.filter(ImageFilter.GaussianBlur(radius=radius))
    if strength != 1:
        blurred = blurred.point(lambda value: int(max(0, min(255, value * strength))))
    return ImageChops.add(source, blurred)


def vignette(image, strength=0.45):
    """Darken toward the corners. strength 0 leaves the picture unchanged."""
    if strength < 0 or strength > 1:
        raise LookError("vignette strength must be between 0 and 1")
    source = _rgb(image)
    output = source.copy()
    src, dst = source.load(), output.load()
    width, height = source.size
    cx, cy = (width - 1) / 2, (height - 1) / 2
    reach = math.hypot(cx, cy) or 1
    for y in range(height):
        for x in range(width):
            falloff = 1 - strength * (math.hypot(x - cx, y - cy) / reach) ** 2
            dst[x, y] = tuple(max(0, min(255, int(channel * falloff))) for channel in src[x, y])
    return output


def particle_points(width, height, t, count=36, seed=1):
    """Deterministic rising motes. Each point is x, y, radius, alpha."""
    if count < 0 or count > 400:
        raise LookError("particle count must be between 0 and 400")
    points = []
    for index in range(count):
        life = 0.8 + unit_hash(seed + index * 17) * 1.7
        age = (t + unit_hash(seed + index * 29) * life) % life
        progress = age / life
        x = unit_hash(seed + index * 3) * (width - 1)
        y = (unit_hash(seed + index * 5) - progress) % 1 * (height - 1)
        radius = 1 + int(unit_hash(seed + index * 7) * 2.2)
        alpha = int(255 * (1 - progress) * 0.8)
        points.append((x, y, radius, alpha))
    return points


def particle_layer(size, t, count=36, seed=1, color=(255, 214, 150)):
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    width, height = size
    for x, y, radius, alpha in particle_points(width, height, t, count, seed):
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=color + (alpha,))
    return layer


def composite_particles(image, t, count=36, seed=1, color=(255, 214, 150)):
    base = _rgb(image).convert("RGBA")
    layer = particle_layer(image.size, t, count, seed, color)
    return Image.alpha_composite(base, layer).convert("RGB")


def apply_looks(image, spec):
    """Apply a dict of grain, bloom, vignette and particles. Missing keys are skipped."""
    if not isinstance(spec, dict):
        raise LookError("look spec must be an object")
    result = _rgb(image)
    if "grain" in spec:
        grain_spec = spec["grain"]
        if isinstance(grain_spec, dict):
            result = grain(result, grain_spec.get("amount", 0.08), grain_spec.get("seed", 1))
        else:
            result = grain(result, float(grain_spec))
    if "bloom" in spec:
        bloom_spec = spec["bloom"] if isinstance(spec["bloom"], dict) else {}
        result = bloom(
            result,
            bloom_spec.get("threshold", 200),
            bloom_spec.get("radius", 6),
            bloom_spec.get("strength", 0.65),
        )
    if "vignette" in spec:
        vignette_spec = spec["vignette"]
        strength = vignette_spec.get("strength", 0.45) if isinstance(vignette_spec, dict) else float(vignette_spec)
        result = vignette(result, strength)
    if "particles" in spec:
        particle_spec = spec["particles"] if isinstance(spec["particles"], dict) else {}
        result = composite_particles(
            result,
            particle_spec.get("time", 0),
            particle_spec.get("count", 36),
            particle_spec.get("seed", 1),
            tuple(particle_spec.get("color", (255, 214, 150))),
        )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--look", default="grain,bloom,vignette", help="comma list: grain,bloom,vignette,particles")
    parser.add_argument("--time", type=float, default=0.0)
    args = parser.parse_args()
    names = [part.strip() for part in args.look.split(",") if part.strip()]
    spec = {}
    for name in names:
        if name == "particles":
            spec[name] = {"time": args.time}
        elif name in {"grain", "bloom", "vignette"}:
            spec[name] = {} if name == "bloom" else (0.08 if name == "grain" else 0.45)
        else:
            raise LookError(f"unknown look {name}")
    image = Image.open(args.image.expanduser())
    apply_looks(image, spec).save(args.output.expanduser())
    print(args.output)


if __name__ == "__main__":
    main()
