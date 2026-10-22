"""Map render-timeline times (with xfade overlaps) onto a gapless 'NLE' timeline (clips back to back)."""
from __future__ import annotations

from ..edl import EDL, RAMP_SPLIT, RAMP_FACTOR


def nle_layout(edl: EDL) -> list[tuple[float, float]]:
    out, t = [], 0.0
    for c in edl.clips:
        out.append((t, t + c.duration))
        t += c.duration
    return out


def remap(edl: EDL, t: float) -> float:
    tl = edl.timeline()
    nle = nle_layout(edl)
    for i in range(len(tl) - 1, -1, -1):
        if t >= tl[i][0] - 1e-6:
            return nle[i][0] + min(t - tl[i][0], nle[i][1] - nle[i][0])
    return t


def ramp_parts(c) -> list[tuple[float, float, float]]:
    """(src_in, src_out, speed) parts for a clip (speed ramp = two parts)."""
    if getattr(c, "ramp", None) is not None:  # v2 eased ramp → constant average speed (NLEs can't take the curve)
        return [(c.in_, c.out, c.src_duration / max(0.01, c.base_duration))]
    if "speed_ramp" not in c.effects:
        return [(c.in_, c.out, c.speed)]
    split = c.in_ + c.src_duration * RAMP_SPLIT
    return [(c.in_, split, c.speed), (split, c.out, c.speed * RAMP_FACTOR)]
