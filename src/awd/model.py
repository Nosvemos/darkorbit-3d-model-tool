"""Intermediate representation for a parsed AWD scene.

Blender-agnostic dataclasses so the parser can be tested standalone and a
pure-Python glTF writer can be added later without touching the parser.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Scene-node name prefixes that mark reference points (kept as Empties later).
POINT_PREFIXES = ("engine_", "laserpoint_", "light_position")


@dataclass
class SubMesh:
    """One sub-geometry: a flat triangle mesh."""
    positions: list[float]          # x,y,z interleaved (len = 3 * vertex_count)
    indices: list[int]              # triangle indices (len = 3 * triangle_count)
    uvs: list[float] = field(default_factory=list)      # u,v interleaved
    normals: list[float] = field(default_factory=list)  # x,y,z interleaved (may be empty)

    @property
    def vertex_count(self) -> int:
        return len(self.positions) // 3

    @property
    def triangle_count(self) -> int:
        return len(self.indices) // 3


@dataclass
class Geometry:
    """A named geometry made of one or more sub-meshes."""
    name: str
    subs: list[SubMesh] = field(default_factory=list)

    @property
    def vertex_count(self) -> int:
        return sum(s.vertex_count for s in self.subs)

    @property
    def triangle_count(self) -> int:
        return sum(s.triangle_count for s in self.subs)


@dataclass
class Material:
    """A material. DarkOrbit links textures by filename convention, not by id,
    so texture channels are resolved later from the mesh name."""
    name: str
    type: int = 0
    props: dict[int, bytes] = field(default_factory=dict)


@dataclass
class MeshInstance:
    """A scene-graph node: name + transform + geometry/material references.
    This is where node names like 'engine_0' / 'laserpoint_*' / 'main' live."""
    name: str
    matrix: list[float]                              # 12 floats, 3x4 column-major
    geometry_id: int
    material_ids: list[int] = field(default_factory=list)
    parent_id: int = 0

    @property
    def translation(self) -> tuple[float, float, float]:
        """World translation = 4th column of the 3x4 matrix."""
        m = self.matrix
        return (m[9], m[10], m[11]) if len(m) >= 12 else (0.0, 0.0, 0.0)

    def matrix_rows(self) -> list[list[float]]:
        """4x4 row-major matrix (for Blender mathutils.Matrix)."""
        m = self.matrix
        if len(m) < 12:
            return [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
        # stored column-major: col0=(m0,m1,m2) col1=(m3,m4,m5) col2=(m6,m7,m8) col3=(m9,m10,m11)
        return [
            [m[0], m[3], m[6], m[9]],
            [m[1], m[4], m[7], m[10]],
            [m[2], m[5], m[8], m[11]],
            [0.0, 0.0, 0.0, 1.0],
        ]

    @property
    def is_point(self) -> bool:
        return self.name.startswith(POINT_PREFIXES)


@dataclass
class AnimationClip:
    """A vertex/pose animation clip (AWD block type 112), e.g. 'open' / 'close'.

    `frames` holds one decoded pose per frame (flat x,y,z positions matching the
    target geometry's vertex order); `geometry_id` is the geometry it animates.
    """
    name: str
    raw: bytes = b""
    frames: list = field(default_factory=list)   # list[list[float]] (positions per frame)
    geometry_id: int = -1


@dataclass
class Scene:
    """Everything parsed from one .awd file."""
    source: str
    geometries: dict[int, Geometry] = field(default_factory=dict)
    materials: dict[int, Material] = field(default_factory=dict)
    instances: list[MeshInstance] = field(default_factory=list)
    clips: list[AnimationClip] = field(default_factory=list)

    def geometry_for(self, inst: MeshInstance) -> Geometry | None:
        return self.geometries.get(inst.geometry_id)

    def materials_for(self, inst: MeshInstance) -> list[Material]:
        return [self.materials[i] for i in inst.material_ids if i in self.materials]

    def summary(self) -> str:
        parts = []
        for inst in self.instances:
            geo = self.geometry_for(inst)
            v = geo.vertex_count if geo else 0
            t = geo.triangle_count if geo else 0
            tag = "*" if inst.is_point else ""
            parts.append(f"{inst.name}{tag}[{v}v/{t}t]")
        return (f"{self.source}: instances=[{', '.join(parts)}] "
                f"clips={[c.name for c in self.clips]}")
