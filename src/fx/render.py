"""Simulate an .awp particle effect and composite it to sprite frames (2D).

Particles are camera-facing billboards, so we simulate them in 3D, project each
centre to 2D (front view: world X/Y -> screen), and composite the textured quad
with the layer's blend mode (additive / alpha). Output is a PNG frame sequence.

Core nodes supported: Time, Position, Velocity, Acceleration, Scale,
Segmented/Initial colour, RotationalVelocity, RotateToHeading, Billboard
(implicit). Orbit / Oscillator / SpriteSheet / UV / Follow are not yet modelled.
"""
from __future__ import annotations

import math
import os
import random
from dataclasses import dataclass

import numpy as np
from PIL import Image

from . import awp

T_TIME = "ParticleTimeNodeSubParser"
T_VEL = "ParticleVelocityNodeSubParser"
T_ACC = "ParticleAccelerationNodeSubParser"
T_POS = "ParticlePositionNodeSubParser"
T_SCALE = "ParticleScaleNodeSubParser"
T_SEGCOL = "ParticleSegmentedColorNodeSubParser"
T_INITCOL = "ParticleInitialColorNodeSubParser"
T_ROTVEL = "ParticleRotationalVelocityNodeSubParser"
T_ROT2HEAD = "ParticleRotateToHeadingNodeSubParser"


@dataclass
class Particle:
    start: float
    duration: float
    pos: tuple
    vel: tuple
    acc: tuple
    scale_min: float
    scale_max: float
    rot_speed: float


def _scale_min_max(scale_node) -> tuple[float, float]:
    """ParticleScaleNode: FourDCompositeWithOneD {x,y} -> (minScale, maxScale)."""
    if not scale_node:
        return (1.0, 1.0)
    d = scale_node.get("scale", {}).get("data", {})
    return (awp.sample1d(d.get("x"), random), awp.sample1d(d.get("y"), random))


def _build_particles(layer: awp.Layer, seed: int) -> list[Particle]:
    rng = random.Random(seed)
    time_d = layer.nodes.get(T_TIME, {})
    smin, smax = _scale_min_max(layer.nodes.get(T_SCALE))
    rot = layer.nodes.get(T_ROTVEL, {})
    rot_speed = awp.sample1d(rot.get("rotation", {}).get("data", {}).get("w"), rng) \
        if rot else 0.0

    out = []
    for _ in range(max(1, layer.num)):
        start = awp.sample1d(time_d.get("startTime"), rng)
        dur = awp.sample1d(time_d.get("duration"), rng) or layer.nodes and 1.0
        dur = dur or 1.0
        pos = awp.sample3d(layer.nodes.get(T_POS, {}).get("position"), rng) \
            if T_POS in layer.nodes else (0.0, 0.0, 0.0)
        vel = awp.sample3d(layer.nodes.get(T_VEL, {}).get("velocity"), rng) \
            if T_VEL in layer.nodes else (0.0, 0.0, 0.0)
        acc = awp.sample3d(layer.nodes.get(T_ACC, {}).get("acceleration"), rng) \
            if T_ACC in layer.nodes else (0.0, 0.0, 0.0)
        out.append(Particle(start, dur, pos, vel, acc, smin, smax,
                            rng.choice([-1, 1]) * rot_speed))
    return out


def _layer_transform(layer: awp.Layer):
    p = layer.prop
    pos = p.get("position", {}).get("data", {})
    sc = p.get("scale", {}).get("data", {})
    rot = p.get("rotation", {}).get("data", {})
    play = float(p.get("playSpeed", {}).get("data", {}).get("value", 1.0) or 1.0)
    return ((pos.get("x", 0.0), pos.get("y", 0.0), pos.get("z", 0.0)),
            (sc.get("x", 1.0), sc.get("y", 1.0)),
            rot.get("z", 0.0), play)


def _state(p: Particle, layer, inst, t):
    inst_pos, inst_scale, inst_rot, play = inst
    age = t * play - p.start
    if layer.nodes.get(T_TIME, {}).get("usesLooping") and p.duration > 0:
        age = age % p.duration
    if age < 0.0 or age > p.duration:
        return None
    life = age / p.duration if p.duration else 0.0

    x = inst_pos[0] + p.pos[0] + p.vel[0] * age + 0.5 * p.acc[0] * age * age
    y = inst_pos[1] + p.pos[1] + p.vel[1] * age + 0.5 * p.acc[1] * age * age
    s = p.scale_min + (p.scale_max - p.scale_min) * life

    if T_SEGCOL in layer.nodes:
        color = awp.segmented_color(layer.nodes[T_SEGCOL], life)
    elif T_INITCOL in layer.nodes:
        color = awp._color_mult(layer.nodes[T_INITCOL].get("color"))
    else:
        color = (1.0, 1.0, 1.0, 1.0)

    if T_ROT2HEAD in layer.nodes:
        angle = math.degrees(math.atan2(p.vel[1], p.vel[0]))
    else:
        angle = math.degrees(p.rot_speed * age) + inst_rot
    return x, y, s * inst_scale[0], s * inst_scale[1], color, angle


class TextureCache:
    def __init__(self, fx_dir, textures_dir):
        self.dirs = [fx_dir, textures_dir]
        self.cache = {}

    def get(self, url: str):
        if url in self.cache:
            return self.cache[url]
        base = os.path.splitext(os.path.basename(url))[0]
        img = None
        from src.atf import ATFError, decode_file
        for d in self.dirs:
            atf = os.path.join(d, base + ".atf")
            if os.path.exists(atf):
                try:
                    img = Image.fromarray(decode_file(atf), "RGBA")
                    break
                except (ATFError, Exception):
                    pass
            png = os.path.join(d, base + ".png")
            if os.path.exists(png):
                img = Image.open(png).convert("RGBA")
                break
        if img is None:  # soft white fallback so the effect still renders
            img = Image.new("RGBA", (32, 32), (255, 255, 255, 255))
        self.cache[url] = img
        return img


def _composite(canvas, sprite_rgba, cx, cy, additive):
    h, w = sprite_rgba.shape[:2]
    x0, y0 = int(round(cx - w / 2)), int(round(cy - h / 2))
    cx0, cy0 = max(0, x0), max(0, y0)
    cx1 = min(canvas.shape[1], x0 + w)
    cy1 = min(canvas.shape[0], y0 + h)
    if cx1 <= cx0 or cy1 <= cy0:
        return
    sp = sprite_rgba[cy0 - y0:cy1 - y0, cx0 - x0:cx1 - x0]
    a = sp[:, :, 3:4]
    region = canvas[cy0:cy1, cx0:cx1]
    if additive:
        rgb = sp[:, :, :3] * a
        region[:, :, :3] += rgb
        # additive output alpha from brightness, so black background stays transparent
        lum = rgb.max(axis=2, keepdims=True)
        region[:, :, 3:4] = np.clip(region[:, :, 3:4] + lum, 0.0, 1.0)
    else:
        region[:, :, :3] = region[:, :, :3] * (1 - a) + sp[:, :, :3] * a
        region[:, :, 3:4] = region[:, :, 3:4] * (1 - a) + a


def render_effect(effect: awp.Effect, out_dir: str, fx_dir: str, textures_dir: str,
                  frames: int = 30, resolution: int = 256, margin: float = 1.2):
    os.makedirs(out_dir, exist_ok=True)
    tex = TextureCache(fx_dir, textures_dir)
    sim = [( layer, _build_particles(layer, i), _layer_transform(layer))
           for i, layer in enumerate(effect.layers)]

    times = [effect.duration * f / max(1, frames - 1) for f in range(frames)]

    # pre-pass: world extent (positions +- half quad) to fit the canvas
    ext = 1.0
    for layer, parts, inst in sim:
        for p in parts:
            for t in times:
                st = _state(p, layer, inst, t)
                if not st:
                    continue
                x, y, sx, sy, _, _ = st
                ext = max(ext, abs(x) + layer.geom_w * sx / 2,
                          abs(y) + layer.geom_h * sy / 2)
    scale = (resolution / 2) / (ext * margin)
    half = resolution / 2

    written = []
    for fi, t in enumerate(times):
        canvas = np.zeros((resolution, resolution, 4), np.float32)
        for layer, parts, inst in sim:
            base = tex.get(layer.texture_url)
            additive = layer.blend_mode == "add"
            for p in parts:
                st = _state(p, layer, inst, t)
                if not st:
                    continue
                x, y, sx, sy, color, angle = st
                w_px = max(1, int(layer.geom_w * sx * scale))
                h_px = max(1, int(layer.geom_h * sy * scale))
                if w_px > 4 * resolution or h_px > 4 * resolution:
                    continue
                spr = base.resize((w_px, h_px), Image.BILINEAR)
                arr = np.asarray(spr, np.float32) / 255.0
                arr = arr * np.array(color, np.float32)        # colour multiplier
                spr = Image.fromarray(np.clip(arr * 255, 0, 255).astype(np.uint8), "RGBA")
                if abs(angle) > 0.5:
                    spr = spr.rotate(angle, expand=True, resample=Image.BILINEAR)
                arr = np.asarray(spr, np.float32) / 255.0
                _composite(canvas, arr, half + x * scale, half - y * scale, additive)

        out = (np.clip(canvas, 0.0, 1.0) * 255).astype(np.uint8)
        path = os.path.join(out_dir, f"{effect.name}_{fi + 1}.png")
        Image.fromarray(out, "RGBA").save(path)
        written.append(path)
    return written
