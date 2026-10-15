"""v2 motion & effects engine (frame-level, NumPy/OpenCV).

sphere     equirectangular 360° reprojection (rectilinear ↔ stereographic ↔ crystal-ball, smooth blends)
ease       easing curves + keyframe tracks
moves360   X5 auto camera moves (follow / orbit / hero / whip / tiny planet / rabbit hole / crystal ball)
camera2d   camera moves on flat footage (pan/tilt, eased push/pull, beat punch-in, shake, roll, subject reframing)
effects    per-frame looks (glitch, light leak, flare, flash, speed lines, grain+weave, VHS, motion blur, freeze pop)
transitions custom transitions (whip, spin, zoom-through, glitch, flash, light-leak)
track      subject detection/tracking (YOLO-onnx → YuNet → HOG/Haar → motion → fixed)
engine     per-clip decode → process → encode pipe
sfx        procedural sound effects (whoosh/hit/riser/glitch/shutter) + local SFX library
"""
ENGINE_VERSION = "2.0.0"  # bump to invalidate cached engine mezzanines
