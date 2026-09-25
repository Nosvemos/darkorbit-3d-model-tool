"""Simulate an .awp particle effect and composite it to sprite frames (2D).

Particles are camera-facing billboards, so we simulate them in 3D, project each
centre to 2D (front view: world X/Y -> screen), and composite the textured quad
with the layer's blend mode (additive / alpha). Output is a PNG frame sequence.

Supports the Away3D nodes used by the bundled effects, including segmented
scale/colour, colour animation, Bezier motion, orbit, oscillator, sprite-sheet
animation and oscillating UV transforms. Follow remains a no-op for a stationary
standalone emitter; billboard alignment is implicit because every sprite faces
the camera.
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
T_SEG_SCALE = "ParticleSegmentedScaleNodeSubParser"
T_SEGCOL = "ParticleSegmentedColorNodeSubParser"
T_COLOR = "ParticleColorNodeSubParser"
T_INITCOL = "ParticleInitialColorNodeSubParser"
T_ROTVEL = "ParticleRotationalVelocityNodeSubParser"
T_ROT2HEAD = "ParticleRotateToHeadingNodeSubParser"
T_ORBIT = "ParticleOrbitNodeSubParser"
T_OSC = "ParticleOscillatorNodeSubParser"
T_SHEET = "ParticleSpriteSheetNodeSubParser"
T_UV = "ParticleUVNodeSubParser"
T_BEZIER = "ParticleBezierCurveNodeSubParser"
# ParticleFollowNode follows the emitter; in standalone playback the emitter is
# fixed at the origin, so it has no displacement -> correctly a no-op here.

TWO_PI = 2.0 * math.pi


@dataclass
class Particle:
    start: float
    duration: float
    pos: tuple
    vel: tuple
    acc: tuple
    scale_min: float
    scale_max: float
    scale_cycle: float
    scale_phase: float
    rot_axis: tuple
    rot_cycle: float
    delay: float = 0.0
    orbit_r: float = 0.0
    orbit_cycle: float = 0.0
    orbit_uses_cycle: bool = False
    orbit_phase: float = 0.0
    orbit_eulers: tuple = (0.0, 0.0, 0.0)
    orbit_uses_eulers: bool = True
    osc: tuple = (0.0, 0.0, 0.0)
    osc_cycle: float = 0.0
    segmented_scale: tuple = ()
    initial_color: tuple = (1.0, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0)
    color_tracks: tuple = ()
    bezier_control: tuple | None = None
    bezier_end: tuple | None = None
    uv_cycle: float = 0.0
    uv_scale: float = 1.0
    sheet_cycle: float = 0.0
    sheet_phase: float = 0.0


def _scale_params(scale_node, rng):
    """Sample ParticleScaleNode min/max, cycle duration, and phase."""
    if not scale_node:
        return 1.0, 1.0, 0.0, 0.0
    d = scale_node.get("scale", {}).get("data", {})
    scale_min = awp.sample1d(d.get("x"), rng) if d.get("x") else 1.0
    scale_max = awp.sample1d(d.get("y"), rng) if d.get("y") else 1.0
    cycle = (awp.sample1d(d.get("z"), rng) if d.get("z") else 1.0) \
        if scale_node.get("usesCycle") else 0.0
    phase = awp.sample1d(d.get("w"), rng) if scale_node.get("usesPhase") else 0.0
    return scale_min, scale_max, cycle, math.radians(phase)


def _sample_segmented_scale(node, rng):
    if not node:
        return ()
    points = [(0.0, awp.sample3d(node.get("startScale"), rng))]
    points.extend((float(p.get("life", 0.0)), awp.sample3d(p.get("scale"), rng))
                  for p in node.get("segmentPoints", []))
    points.append((1.0, awp.sample3d(node.get("endScale"), rng)))
    return tuple(sorted(points, key=lambda item: item[0]))


def _masked_color_transform(node, rng, uses_multiplier=True, uses_offset=True):
    value = awp.color_transform(node, rng)
    return ((value[:4] if uses_multiplier else (1.0, 1.0, 1.0, 1.0)) +
            (value[4:] if uses_offset else (0.0, 0.0, 0.0, 0.0)))


def _sample_segmented_color(node, rng):
    if not node:
        return ()
    use_multiplier = node.get("usesMultiplier", True)
    use_offset = node.get("usesOffset", True)
    points = [(0.0, _masked_color_transform(node.get("startColor"), rng,
                                             use_multiplier, use_offset))]
    points.extend((float(p.get("life", 0.0)),
                   _masked_color_transform(p.get("color"), rng,
                                           use_multiplier, use_offset))
                  for p in node.get("segmentPoints", []))
    points.append((1.0, _masked_color_transform(node.get("endColor"), rng,
                                                use_multiplier, use_offset)))
    return tuple(sorted(points, key=lambda item: item[0]))


def _sample_color_node(node, rng):
    if not node:
        return None
    points = (
        (0.0, _masked_color_transform(node.get("startColor"), rng,
                                      node.get("usesMultiplier", True),
                                      node.get("usesOffset", True))),
        (1.0, _masked_color_transform(node.get("endColor"), rng,
                                      node.get("usesMultiplier", True),
                                      node.get("usesOffset", True))),
    )
    cycle_duration = 0.0
    if node.get("usesCycle"):
        cycle_node = node.get("cycleDuration") or node.get("cycle")
        cycle_duration = awp.sample1d(cycle_node, rng) if cycle_node else 1.0
    phase_degrees = awp.sample1d(node.get("cyclePhase") or node.get("phase"), rng) \
        if node.get("usesPhase") else 0.0
    return points, cycle_duration, math.radians(phase_degrees)


def _sample_curve(points, life):
    if not points:
        return ()
    life = max(0.0, min(1.0, life))
    for index in range(len(points) - 1):
        l0, v0 = points[index]
        l1, v1 = points[index + 1]
        if life <= l1 or index == len(points) - 2:
            factor = (life - l0) / (l1 - l0) if l1 > l0 else 0.0
            return tuple(v0[k] + (v1[k] - v0[k]) * factor for k in range(len(v0)))
    return points[-1][1]


def _build_particles(layer: awp.Layer, seed: int, cancel_check=None) -> list[Particle]:
    rng = random.Random(seed)
    time_d = layer.nodes.get(T_TIME, {})
    scale_node = layer.nodes.get(T_SCALE)
    segmented_scale_node = layer.nodes.get(T_SEG_SCALE)
    rot = layer.nodes.get(T_ROTVEL, {})
    orbit_node = layer.nodes.get(T_ORBIT, {})
    orbit = orbit_node.get("orbit", {}).get("data", {})
    osc = layer.nodes.get(T_OSC, {}).get("oscillator", {}).get("data", {})
    uv_node = layer.nodes.get(T_UV)
    sheet_node = layer.nodes.get(T_SHEET, {})
    color_node = layer.nodes.get(T_COLOR)
    segmented_color_node = layer.nodes.get(T_SEGCOL)
    initial_color_node = layer.nodes.get(T_INITCOL)
    bezier_node = layer.nodes.get(T_BEZIER)

    out = []
    for particle_index in range(max(1, layer.num)):
        if cancel_check and particle_index % 64 == 0:
            cancel_check()
        smin, smax, scale_cycle, scale_phase = _scale_params(scale_node, rng)
        segmented_scale = _sample_segmented_scale(segmented_scale_node, rng)
        rotation_data = rot.get("rotation", {}).get("data", {})
        rot_axis = awp.sample3d(rotation_data.get("x"), rng) if rot else (0.0, 0.0, 1.0)
        axis_length = math.sqrt(sum(value * value for value in rot_axis))
        rot_axis = tuple(value / axis_length for value in rot_axis) \
            if axis_length > 0.0 else (0.0, 0.0, 1.0)
        rot_cycle = awp.sample1d(rotation_data.get("w"), rng) if rot else 0.0
        start = awp.sample1d(time_d.get("startTime"), rng)
        dur = awp.sample1d(time_d.get("duration"), rng) or 1.0
        delay = awp.sample1d(time_d.get("delay"), rng) \
            if time_d.get("usesDelay") else 0.0
        pos = awp.sample3d(layer.nodes.get(T_POS, {}).get("position"), rng) \
            if T_POS in layer.nodes else (0.0, 0.0, 0.0)
        vel = awp.sample3d(layer.nodes.get(T_VEL, {}).get("velocity"), rng) \
            if T_VEL in layer.nodes else (0.0, 0.0, 0.0)
        acc = awp.sample3d(layer.nodes.get(T_ACC, {}).get("acceleration"), rng) \
            if T_ACC in layer.nodes else (0.0, 0.0, 0.0)
        # Orbit values are radius (x), cycle duration (y), and phase degrees (z).
        orbit_r = awp.sample1d(orbit.get("x"), rng) if orbit.get("x") else \
            (100.0 if orbit_node else 0.0)
        orbit_cycle = (awp.sample1d(orbit.get("y"), rng) if orbit.get("y") else 1.0) \
            if orbit_node.get("usesCycle") else 0.0
        orbit_phase = math.radians(awp.sample1d(orbit.get("z"), rng)) \
            if orbit_node.get("usesPhase") else 0.0
        eulers_node = orbit_node.get("eulers")
        orbit_eulers = awp.sample3d(eulers_node, rng) if eulers_node else (0.0, 0.0, 0.0)
        # oscillator: FourDCompositeWithThreeD {w:cycleDuration, x:amplitude vector}
        osc_vec = awp.sample3d(osc.get("x"), rng) if osc else (0.0, 0.0, 0.0)
        osc_cycle = awp.sample1d(osc.get("w"), rng) if osc else 0.0
        initial_color = _masked_color_transform(
            initial_color_node.get("color"), rng,
            initial_color_node.get("usesMultiplier", True),
            initial_color_node.get("usesOffset", True)) if initial_color_node else \
            (1.0, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0)
        color_tracks = []
        if color_node:
            track = _sample_color_node(color_node, rng)
            if track:
                color_tracks.append(track)
        if segmented_color_node:
            color_tracks.append((_sample_segmented_color(segmented_color_node, rng), 0.0, 0.0))
        bezier_control = awp.sample3d(bezier_node.get("control"), rng) if bezier_node else None
        bezier_end = awp.sample3d(bezier_node.get("end"), rng) if bezier_node else None
        uv_cycle = (awp.sample1d(uv_node.get("cycle"), rng) if uv_node.get("cycle") else 1.0) \
            if uv_node else 0.0
        uv_scale = awp.sample1d(uv_node.get("scale"), rng) \
            if uv_node and uv_node.get("scale") else 1.0
        sheet_scale = sheet_node.get("scale", {}).get("data", {})
        sheet_cycle = (awp.sample1d(sheet_scale.get("x"), rng) if sheet_scale.get("x") else 1.0) \
            if sheet_node.get("usesCycle") else 0.0
        sheet_phase = awp.sample1d(sheet_scale.get("y"), rng) \
            if sheet_node.get("usesPhase") else 0.0
        out.append(Particle(
            start=start, duration=dur, pos=pos, vel=vel, acc=acc,
            scale_min=smin, scale_max=smax, scale_cycle=scale_cycle,
            scale_phase=scale_phase, rot_axis=rot_axis, rot_cycle=rot_cycle,
            delay=delay,
            orbit_r=orbit_r, orbit_cycle=orbit_cycle,
            orbit_uses_cycle=bool(orbit_node.get("usesCycle")),
            orbit_phase=orbit_phase, orbit_eulers=orbit_eulers,
            orbit_uses_eulers=bool(eulers_node) and orbit_node.get("usesEulers", True),
            osc=osc_vec, osc_cycle=osc_cycle,
            segmented_scale=segmented_scale, initial_color=initial_color,
            color_tracks=tuple(color_tracks), bezier_control=bezier_control,
            bezier_end=bezier_end, uv_cycle=uv_cycle, uv_scale=uv_scale,
            sheet_cycle=sheet_cycle, sheet_phase=sheet_phase))
    return out


def _sheet(layer: awp.Layer):
    """ParticleSpriteSheetNode grid settings -> (rows, cols, frames, cycle), or None."""
    d = layer.nodes.get(T_SHEET)
    if not d:
        return None
    rows, cols = int(d.get("numRows", 1) or 1), int(d.get("numColumns", 1) or 1)
    total = min(rows * cols, int(d.get("totalFrames", rows * cols) or rows * cols))
    return (rows, cols, total, bool(d.get("usesCycle"))) if total > 1 else None


def _sheet_cell(base, sheet, life, age, particle):
    """Crop the active life- or time-driven flip-book cell."""
    if not sheet:
        return None
    rows, cols, total, uses_cycle = sheet
    if uses_cycle and particle.sheet_cycle > 0.0:
        idx = int(((age + particle.sheet_phase) % particle.sheet_cycle) /
                  particle.sheet_cycle * total)
    else:
        idx = int(max(0.0, min(1.0, life)) * total)
    idx = min(total - 1, max(0, idx))
    col, row = idx % cols, idx // cols
    w, h = base.size
    cw, ch = w // cols, h // rows
    return base.crop((col * cw, row * ch, col * cw + cw, row * ch + ch))


def _layer_transform(layer: awp.Layer):
    p = layer.prop
    pos = p.get("position", {}).get("data", {})
    sc = p.get("scale", {}).get("data", {})
    rot = p.get("rotation", {}).get("data", {})
    play_value = p.get("playSpeed", {}).get("data", {}).get("value", 1.0)
    offset_value = p.get("timeOffset", {}).get("data", {}).get("value", 0.0)
    play = float(1.0 if play_value is None else play_value)
    time_offset = float(0.0 if offset_value is None else offset_value)
    return ((pos.get("x", 0.0), pos.get("y", 0.0), pos.get("z", 0.0)),
            (sc.get("x", 1.0), sc.get("y", 1.0)),
            rot.get("z", 0.0), play, time_offset)


def _rotate_xyz(vector, eulers):
    x, y, z = vector
    ex, ey, ez = (math.radians(value) for value in eulers)
    y, z = y * math.cos(ex) - z * math.sin(ex), y * math.sin(ex) + z * math.cos(ex)
    x, z = x * math.cos(ey) + z * math.sin(ey), -x * math.sin(ey) + z * math.cos(ey)
    x, y = x * math.cos(ez) - y * math.sin(ez), x * math.sin(ez) + y * math.cos(ez)
    return x, y, z


def _state(p: Particle, layer, inst, t):
    inst_pos, inst_scale, inst_rot, play, time_offset = inst
    age = t * play + time_offset - p.start
    time_node = layer.nodes.get(T_TIME, {})
    if age < 0.0:
        return None
    if time_node.get("usesDuration"):
        if time_node.get("usesLooping"):
            period = p.duration + (p.delay if time_node.get("usesDelay") else 0.0)
            if period <= 0.0:
                return None
            age %= period
            if time_node.get("usesDelay") and age >= p.duration:
                return None
        elif age > p.duration:
            return None
    life = age / p.duration if p.duration else 0.0

    x = inst_pos[0] + p.pos[0] + p.vel[0] * age + 0.5 * p.acc[0] * age * age
    y = inst_pos[1] + p.pos[1] + p.vel[1] * age + 0.5 * p.acc[1] * age * age
    if p.bezier_control and p.bezier_end:
        u = life
        control_weight = 2.0 * u * (1.0 - u)
        end_weight = u * u
        x += control_weight * p.bezier_control[0] + end_weight * p.bezier_end[0]
        y += control_weight * p.bezier_control[1] + end_weight * p.bezier_end[1]
    if p.orbit_uses_cycle:
        th = TWO_PI * age / p.orbit_cycle + p.orbit_phase if p.orbit_cycle > 0.0 else 0.0
    else:
        th = TWO_PI * life
    orbit = (p.orbit_r * math.cos(th), p.orbit_r * math.sin(th), 0.0)
    if p.orbit_uses_eulers:
        # Away3D applies Euler rotations to the orbit plane in X, Y, Z order.
        orbit = _rotate_xyz(orbit, p.orbit_eulers)
    x += orbit[0]
    y += orbit[1]
    if p.osc_cycle > 0.0:
        sn = math.sin(TWO_PI * age / p.osc_cycle)
        x += p.osc[0] * sn
        y += p.osc[1] * sn
    s = p.scale_min + (p.scale_max - p.scale_min) * life
    if p.scale_cycle > 0.0:
        midpoint = (p.scale_min + p.scale_max) / 2.0
        amplitude = abs(p.scale_max - p.scale_min) / 2.0
        s = midpoint + amplitude * math.sin(TWO_PI * age / p.scale_cycle + p.scale_phase)
    scale_x = scale_y = s
    if p.segmented_scale:
        segmented = _sample_curve(p.segmented_scale, life)
        scale_x *= segmented[0]
        scale_y *= segmented[1]

    color = list(p.initial_color)
    for points, cycle_duration, cycle_phase in p.color_tracks:
        factor = life
        if cycle_duration > 0.0:
            factor = math.sin(TWO_PI * age / cycle_duration + cycle_phase)
            start_color, end_color = points[0][1], points[-1][1]
            transform = tuple(start_color[index] +
                              (end_color[index] - start_color[index]) * factor
                              for index in range(len(start_color)))
        else:
            transform = _sample_curve(points, factor)
        for index in range(4):
            color[index] *= transform[index]
            color[index + 4] += transform[index + 4]

    if T_ROT2HEAD in layer.nodes:
        vx, vy = p.vel[0], p.vel[1]
        vx += p.acc[0] * age
        vy += p.acc[1] * age
        if p.bezier_control and p.bezier_end:
            vx += 2.0 * ((1.0 - 2.0 * life) * p.bezier_control[0] +
                         life * p.bezier_end[0]) / p.duration
            vy += 2.0 * ((1.0 - 2.0 * life) * p.bezier_control[1] +
                         life * p.bezier_end[1]) / p.duration
        if p.orbit_r:
            orbit_rate = TWO_PI / p.orbit_cycle if p.orbit_uses_cycle and p.orbit_cycle > 0.0 \
                else TWO_PI / p.duration
            orbit_velocity = (-p.orbit_r * math.sin(th) * orbit_rate,
                              p.orbit_r * math.cos(th) * orbit_rate, 0.0)
            if p.orbit_uses_eulers:
                orbit_velocity = _rotate_xyz(orbit_velocity, p.orbit_eulers)
            vx += orbit_velocity[0]
            vy += orbit_velocity[1]
        if p.osc_cycle > 0.0:
            oscillator_rate = TWO_PI / p.osc_cycle
            oscillator_velocity = math.cos(oscillator_rate * age) * oscillator_rate
            vx += p.osc[0] * oscillator_velocity
            vy += p.osc[1] * oscillator_velocity
        angle = math.degrees(math.atan2(vy, vx))
    else:
        angle = 0.0
    if p.rot_cycle > 0.0:
        angle += math.degrees(math.pi * age / p.rot_cycle * p.rot_axis[2])
    angle += inst_rot

    # Away3D UV animation is sinusoidal in system time, with a texture scale.
    uv = None
    uvd = layer.nodes.get(T_UV)
    if uvd and p.uv_cycle > 0.0:
        uv = (uvd.get("axis", "x"), math.sin(TWO_PI * age / p.uv_cycle), p.uv_scale)
    return (x, y, scale_x * inst_scale[0], scale_y * inst_scale[1],
            tuple(color), angle, life, age, uv)


def _apply_uv_transform(image, axis, offset, uv_scale, repeat):
    """Sample scaled/offset UVs using the material's repeat or clamp mode."""
    if abs(offset) < 1e-8 and abs(uv_scale - 1.0) < 1e-8:
        return image
    source = np.asarray(image, np.float32)
    height, width = source.shape[:2]
    u = ((np.arange(width, dtype=np.float32) + 0.5) / width) * uv_scale
    v = ((np.arange(height, dtype=np.float32) + 0.5) / height) * uv_scale
    if axis == "x":
        u += offset
    elif axis == "y":
        v += offset
    if repeat:
        u = (u % 1.0) * width - 0.5
        v = (v % 1.0) * height - 0.5
    else:
        u = np.clip(u * width - 0.5, 0.0, width - 1.0)
        v = np.clip(v * height - 0.5, 0.0, height - 1.0)
    x0, y0 = np.floor(u).astype(int), np.floor(v).astype(int)
    fx, fy = (u - x0)[None, :, None], (v - y0)[:, None, None]
    if repeat:
        x0, x1 = x0 % width, (x0 + 1) % width
        y0, y1 = y0 % height, (y0 + 1) % height
    else:
        x0, x1 = x0.clip(0, width - 1), (x0 + 1).clip(0, width - 1)
        y0, y1 = y0.clip(0, height - 1), (y0 + 1).clip(0, height - 1)
    top = source[y0[:, None], x0[None, :]] * (1.0 - fx) + source[y0[:, None], x1[None, :]] * fx
    bottom = source[y1[:, None], x0[None, :]] * (1.0 - fx) + source[y1[:, None], x1[None, :]] * fx
    return Image.fromarray(np.clip(top * (1.0 - fy) + bottom * fy, 0, 255).astype(np.uint8), "RGBA")


class TextureCache:
    def __init__(self, fx_dir, textures_dir):
        self.dirs = [fx_dir, textures_dir]
        self.cache = {}
        self.missing = []

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
            missing = url or "<empty texture URL>"
            if missing not in self.missing:
                self.missing.append(missing)
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
                  frames: int = 30, resolution: int = 256, margin: float = 1.2,
                  warnings: list[str] | None = None, cancel_check=None):
    if not isinstance(frames, int) or not 1 <= frames <= 600:
        raise ValueError("frames must be between 1 and 600")
    if not isinstance(resolution, int) or not 16 <= resolution <= 2048:
        raise ValueError("resolution must be between 16 and 2048 pixels")
    if not math.isfinite(margin) or not 0.05 <= margin <= 10.0:
        raise ValueError("margin must be between 0.05 and 10")
    os.makedirs(out_dir, exist_ok=True)
    import glob
    for old in glob.glob(os.path.join(out_dir, f"{effect.name}_*.png")):
        os.remove(old)  # clear stale frames so the set matches this run
    tex = TextureCache(fx_dir, textures_dir)
    sim = []
    for i, layer in enumerate(effect.layers):
        if cancel_check:
            cancel_check()
        sim.append((layer, _build_particles(layer, i, cancel_check), _layer_transform(layer),
                    _sheet(layer)))

    times = [effect.duration * f / max(1, frames - 1) for f in range(frames)]

    # pre-pass: world extent (positions +- half quad) to fit the canvas
    ext = 1.0
    for layer, parts, inst, _sh in sim:
        for pi, p in enumerate(parts):
            if cancel_check and pi % 32 == 0:
                cancel_check()
            for t in times:
                st = _state(p, layer, inst, t)
                if not st:
                    continue
                x, y, sx, sy = st[0], st[1], st[2], st[3]
                ext = max(ext, abs(x) + layer.geom_w * abs(sx) / 2,
                          abs(y) + layer.geom_h * abs(sy) / 2)
    scale = (resolution / 2) / (ext * margin)
    half = resolution / 2

    written = []
    for fi, t in enumerate(times):
        if cancel_check:
            cancel_check()
        canvas = np.zeros((resolution, resolution, 4), np.float32)
        for layer, parts, inst, sheet in sim:
            if cancel_check:
                cancel_check()
            base = tex.get(layer.texture_url)
            additive = layer.blend_mode == "add"
            for pi, p in enumerate(parts):
                if cancel_check and pi % 32 == 0:
                    cancel_check()
                st = _state(p, layer, inst, t)
                if not st:
                    continue
                x, y, sx, sy, color, angle, life, age, uv = st
                w_px = max(1, int(layer.geom_w * abs(sx) * scale))
                h_px = max(1, int(layer.geom_h * abs(sy) * scale))
                if w_px > 4 * resolution or h_px > 4 * resolution:
                    continue
                src = _sheet_cell(base, sheet, life, age, p) or base
                spr = src.resize((w_px, h_px), Image.BILINEAR)
                if sx < 0:
                    spr = spr.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
                if sy < 0:
                    spr = spr.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
                if uv:
                    spr = _apply_uv_transform(spr, uv[0], uv[1], uv[2], layer.repeat)
                arr = np.asarray(spr, np.float32) / 255.0
                arr = (arr * np.array(color[:4], np.float32) +
                       np.array(color[4:], np.float32))       # multiplier + offset
                spr = Image.fromarray(np.clip(arr * 255, 0, 255).astype(np.uint8), "RGBA")
                if abs(angle) > 0.5:
                    spr = spr.rotate(angle, expand=True, resample=Image.BILINEAR)
                arr = np.asarray(spr, np.float32) / 255.0
                _composite(canvas, arr, half + x * scale, half - y * scale, additive)

        out = (np.clip(canvas, 0.0, 1.0) * 255).astype(np.uint8)
        path = os.path.join(out_dir, f"{effect.name}_{fi + 1}.png")
        Image.fromarray(out, "RGBA").save(path)
        written.append(path)
    if warnings is not None:
        warnings.extend(tex.missing)
    return written
