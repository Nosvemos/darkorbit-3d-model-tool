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
from dataclasses import dataclass, field


# --- value samplers ---------------------------------------------------------

def sample1d(node, rng) -> float:
    if not node:
        return 0.0
    d = node.get("data", {})
    if "Random" in node.get("id", ""):           # note source typo: "Vaule"
        return rng.uniform(d.get("min", 0.0), d.get("max", 0.0))
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
        r = rng.uniform(d.get("innerRadius", 0.0), d.get("outerRadius", 0.0))
        sx, sy, sz = _unit_sphere(rng)
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


def _color_mult(node):
    """Return the (r, g, b, a) multiplier of a CompositeColor value."""
    d = (node or {}).get("data", {})
    return (d.get("mr", 1.0), d.get("mg", 1.0), d.get("mb", 1.0), d.get("ma", 1.0))


def segmented_color(node, life: float):
    """Evaluate a ParticleSegmentedColorNode multiplier at life fraction [0,1]."""
    if not node:
        return (1.0, 1.0, 1.0, 1.0)
    pts = [(0.0, _color_mult(node.get("startColor")))]
    for p in node.get("segmentPoints", []):
        pts.append((float(p.get("life", 0.0)), _color_mult(p.get("color"))))
    pts.append((1.0, _color_mult(node.get("endColor"))))
    pts.sort(key=lambda t: t[0])
    life = max(0.0, min(1.0, life))
    for i in range(len(pts) - 1):
        l0, c0 = pts[i]
        l1, c1 = pts[i + 1]
        if life <= l1 or i == len(pts) - 2:
            f = (life - l0) / (l1 - l0) if l1 > l0 else 0.0
            return tuple(c0[k] + (c1[k] - c0[k]) * f for k in range(4))
    return pts[-1][1]


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
            geom_w=w, geom_h=h, num=num, nodes=nodes, prop=prop))

    duration = 0.0
    for ev in d.get("particleEvents", []):
        if ev.get("name") == "end":
            duration = max(duration, float(ev.get("occurTime", 0.0)))
    if duration <= 0.0:
        duration = 1.0

    return Effect(name=os.path.splitext(os.path.basename(path))[0],
                  layers=layers, duration=duration)
