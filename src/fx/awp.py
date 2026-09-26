"""Parser + value samplers for Away3D '.awp' particle effects (plain JSON).

An .awp describes one or more particle *layers* (animationDatas). Each layer has:
  - a textured material (TextureMaterial: url + blendMode)
  - a geometry assembler (plane shape W x H, particle count `num`)
  - animation nodes (time / velocity / acceleration / scale / colour / rotation)
  - per-instance property curves (position / scale / rotation / timeOffset / playSpeed)

Node/value parameters use "value sub-parsers" (const / random / 3D distributions /
composite colour). This module turns those into Python sample functions so the
renderer can instantiate concrete particles.
"""
from __future__ import annotations

import json
import math
import os
import random
from dataclasses import dataclass, field


# --- value samplers ---------------------------------------------------------

def sample1d(node, rng) -> float:
    if not node:
        return 0.0
    d = node.get("data", {})
    if "Random" in node.get("id", ""):           # note source typo: "Vaule"
        return rng.uniform(d.get("min", 0.0), d.get("max", 0.0))
    if "Curve" in node.get("id", ""):
        # Curves act as one-dimensional distributions for particle properties.
        # Sample their normalized input with the same seeded stream as Random.
        anchors = sorted(d.get("anchorDatas", []), key=lambda item: float(item.get("x", 0.0)))
        if not anchors:
            return 0.0
        t = rng.random()
        if t <= float(anchors[0].get("x", 0.0)):
            return float(anchors[0].get("y", 0.0))
        for left, right in zip(anchors, anchors[1:]):
            x0, x1 = float(left.get("x", 0.0)), float(right.get("x", 0.0))
            if t <= x1:
                y0, y1 = float(left.get("y", 0.0)), float(right.get("y", 0.0))
                factor = (t - x0) / (x1 - x0) if x1 > x0 else 0.0
                return y0 + (y1 - y0) * factor
        return float(anchors[-1].get("y", 0.0))
    return float(d.get("value", 0.0))


def _unit_sphere(rng):
    u = rng.uniform(-1.0, 1.0)
    th = rng.uniform(0.0, 2.0 * math.pi)
    s = math.sqrt(max(0.0, 1.0 - u * u))
    return s * math.cos(th), s * math.sin(th), u


def sample3d(node, rng):
    """Return an (x, y, z) sample from a 1D/3D value sub-parser."""
    if not node:
        return (0.0, 0.0, 0.0)
    d = node.get("data", {})
    i = node.get("id", "")
    if "Sphere" in i:
        # ThreeDSphereSetter.generateOneValue samples volume, then normalizes
        # a random cube vector (the shipped implementation, not uniform angle).
        rng.random()  # unused angle sampled by the AS3 setter
        inner, outer = d.get("innerRadius", 0.0), d.get("outerRadius", 0.0)
        r = (rng.random() * (outer ** 3 - inner ** 3) + inner ** 3) ** (1 / 3)
        direction = tuple(rng.random() - .5 for _ in range(3))
        length = math.sqrt(sum(x * x for x in direction))
        sx, sy, sz = tuple(x / length for x in direction) if length else (1, 0, 0)
        return (d.get("centerX", 0) + r * sx,
                d.get("centerY", 0) + r * sy,
                d.get("centerZ", 0) + r * sz)
    if "Cylinder" in i:
        r = rng.uniform(d.get("innerRadius", 0.0), d.get("outerRadius", 0.0))
        th = rng.uniform(0.0, 2.0 * math.pi)
        h = d.get("height", 0.0)
        return (d.get("centerX", 0) + r * math.cos(th),
                d.get("centerY", 0) + rng.uniform(-h / 2, h / 2),
                d.get("centerZ", 0) + r * math.sin(th))
    if "Composite" in i:                          # ThreeDComposite {x,y,z: 1D}
        return (sample1d(d.get("x"), rng),
                sample1d(d.get("y"), rng),
                sample1d(d.get("z"), rng))
    return (float(d.get("x", 0.0)), float(d.get("y", 0.0)), float(d.get("z", 0.0)))


def color_transform(node, rng=None) -> tuple[float, ...]:
    """Sample a CompositeColor value as normalized multipliers and offsets."""
    d = (node or {}).get("data", {})
    rng = rng or random
    channels = (
        ("redMultiplierValue", "mr", 1.0),
        ("greenMultiplierValue", "mg", 1.0),
        ("blueMultiplierValue", "mb", 1.0),
        ("alphaMultiplierValue", "ma", 1.0),
    )
    offsets = (
        ("redOffsetValue", "or"),
        ("greenOffsetValue", "og"),
        ("blueOffsetValue", "ob"),
        ("alphaOffsetValue", "oa"),
    )

    def component(primary, fallback, default):
        value = d.get(primary)
        if isinstance(value, dict):
            return sample1d(value, rng)
        return float(d.get(fallback, default))

    multipliers = tuple(component(nested, direct, default)
                        for nested, direct, default in channels)
    offset_values = []
    for nested, direct in offsets:
        value = d.get(nested)
        raw = sample1d(value, rng) if isinstance(value, dict) else float(d.get(direct, 0.0))
        offset_values.append(raw / 255.0)
    return multipliers + tuple(offset_values)


def _color_mult(node, rng=None):
    """Return the (r, g, b, a) multiplier of a CompositeColor value."""
    return color_transform(node, rng)[:4]


def segmented_color_transform(node, life: float, rng=None) -> tuple[float, ...]:
    """Interpolate multiplier and offset values along a segmented colour curve."""
    if not node:
        return (1.0, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0)
    use_multiplier = node.get("usesMultiplier", True)
    use_offset = node.get("usesOffset", True)

    def value(color):
        result = color_transform(color, rng)
        multipliers = result[:4] if use_multiplier else (1.0, 1.0, 1.0, 1.0)
        offsets = result[4:] if use_offset else (0.0, 0.0, 0.0, 0.0)
        return multipliers + offsets

    points = [(0.0, value(node.get("startColor")))]
    for point in node.get("segmentPoints", []):
        points.append((float(point.get("life", 0.0)), value(point.get("color"))))
    points.append((1.0, value(node.get("endColor"))))
    points.sort(key=lambda item: item[0])
    life = max(0.0, min(1.0, life))
    for index in range(len(points) - 1):
        l0, c0 = points[index]
        l1, c1 = points[index + 1]
        if life <= l1 or index == len(points) - 2:
            factor = (life - l0) / (l1 - l0) if l1 > l0 else 0.0
            return tuple(c0[k] + (c1[k] - c0[k]) * factor for k in range(8))
    return points[-1][1]


def segmented_color(node, life: float):
    """Evaluate a ParticleSegmentedColorNode multiplier at life fraction [0,1]."""
    return segmented_color_transform(node, life)[:4]


# --- model ------------------------------------------------------------------

@dataclass
class Layer:
    name: str
    texture_url: str
    blend_mode: str
    geom_w: float
    geom_h: float
    num: int
    nodes: dict = field(default_factory=dict)      # id -> data
    prop: dict = field(default_factory=dict)       # per-instance property curves
    repeat: bool = False


@dataclass
class Effect:
    name: str
    layers: list = field(default_factory=list)
    duration: float = 1.0


def _assembler_shape(data: dict):
    asm = data.get("geometry", {}).get("data", {}).get("assembler", {}).get("data", {})
    shape = asm.get("shape", {}).get("data", {})
    return shape.get("width", 10.0), shape.get("height", 10.0), int(asm.get("num", 1) or 1)


def load(path: str) -> Effect:
    with open(path, encoding="utf-8") as f:
        d = json.load(f)

    layers = []
    for ad in d.get("animationDatas", []):
        data = ad.get("data", {})
        mat = data.get("material", {}).get("data", {})
        w, h, num = _assembler_shape(data)
        nodes = {n.get("id"): n.get("data", {}) for n in data.get("nodes", [])}
        prop = ad.get("property", {}).get("data", {})
        layers.append(Layer(
            name=data.get("name", "layer"),
            texture_url=mat.get("url", ""),
            blend_mode=mat.get("blendMode", "normal"),
            geom_w=w, geom_h=h, num=num, repeat=bool(mat.get("repeat", False)),
            nodes=nodes, prop=prop))

    duration = 0.0
    for ev in d.get("particleEvents", []):
        if ev.get("name") == "end":
            duration = max(duration, float(ev.get("occurTime", 0.0)))
    if duration <= 0.0:
        duration = 1.0

    return Effect(name=os.path.splitext(os.path.basename(path))[0],
                  layers=layers, duration=duration)
