"""AWD2 (Away3D) parser for DarkOrbit '.awd' assets.

File layout (verified empirically on the DarkOrbit asset set):
    bytes 0-2 : magic 'AWD'
    byte 3    : 'c' (DarkOrbit 'AWDc' variant) or version-major (standard 'AWD\\x02')
    byte 7    : compression (1 = zlib)
    byte 8    : uncompressed length (u32 LE)
    byte 12   : zlib deflate stream -> AWD2 block list

Block header (little-endian, 11 bytes):
    u32 id, u8 namespace, u8 type, u8 flags, u32 length, then `length` data bytes.

Block types: 1=TriangleGeometry, 23=MeshInstance (scene node), 81=Material,
112=vertex-anim clip, 113=AnimationSet, 122=Animator, 254=Namespace, 255=Metadata.

TriangleGeometry stream types: 1=positions, 2=indices, 3=UVs, 4=normals.
Stream value types (ftype): 5=uint16, 6=uint32, 7=float32, 8=float64.

MeshInstance layout: u32 parent_id, 12x f32 transform (3x4 column-major),
str16 name, u32 geometry_id, u16 material_count, u32 material_id[count], (trailing).
"""
from __future__ import annotations

import struct
import zlib

from .model import AnimationClip, Geometry, Material, MeshInstance, Scene, SubMesh

MAGIC = b"AWD"

# AWD2 block type ids
T_GEOMETRY = 1
T_MESH_INSTANCE = 23
T_MATERIAL = 81
T_ANIM_CLIP = 112

# TriangleGeometry stream ids
S_POSITIONS = 1
S_INDICES = 2
S_UVS = 3
S_NORMALS = 4

# stream value type -> (struct code, byte size)
_FTYPE = {5: ("H", 2), 6: ("I", 4), 7: ("f", 4), 8: ("d", 8)}


class _Reader:
    """Little-endian cursor over a bytes buffer."""

    def __init__(self, buf: bytes, pos: int = 0):
        self.buf = buf
        self.pos = pos

    def u8(self) -> int:
        v = self.buf[self.pos]
        self.pos += 1
        return v

    def u16(self) -> int:
        v = struct.unpack_from("<H", self.buf, self.pos)[0]
        self.pos += 2
        return v

    def u32(self) -> int:
        v = struct.unpack_from("<I", self.buf, self.pos)[0]
        self.pos += 4
        return v

    def f32(self, n: int) -> list[float]:
        v = list(struct.unpack_from(f"<{n}f", self.buf, self.pos))
        self.pos += 4 * n
        return v

    def str16(self) -> str:
        n = self.u16()
        s = self.buf[self.pos:self.pos + n].decode("utf-8", "replace")
        self.pos += n
        return s.rstrip("\x00")

    def raw(self, n: int) -> bytes:
        b = self.buf[self.pos:self.pos + n]
        self.pos += n
        return b


def decompress(raw: bytes) -> bytes:
    """Strip the 12-byte header and inflate the zlib body."""
    if raw[:3] != MAGIC:
        raise ValueError(f"not an AWD file (magic={raw[:4]!r})")
    compression = raw[7]
    if compression != 1:
        raise ValueError(f"unsupported compression {compression} (expected 1=zlib)")
    return zlib.decompress(raw[12:])


def _iter_blocks(body: bytes):
    """Yield (block_id, type, data_bytes) for each AWD2 block."""
    off = 0
    n = len(body)
    while off + 11 <= n:
        block_id = struct.unpack_from("<I", body, off)[0]
        btype = body[off + 5]
        length = struct.unpack_from("<I", body, off + 7)[0]
        data_off = off + 11
        if data_off + length > n:
            raise ValueError(f"block at {off} length {length} overruns body")
        yield block_id, btype, body[data_off:data_off + length]
        off = data_off + length


def _parse_geometry(data: bytes) -> Geometry:
    r = _Reader(data)
    name = r.str16()
    num_subs = r.u16()
    # NOTE: never write `r.pos += r.u32()` — Python reads r.pos before u32()
    # advances it, silently discarding the 4-byte read. Use an explicit temp.
    geom_prop_len = r.u32()
    r.pos += geom_prop_len  # geometry-level properties: skipped

    geo = Geometry(name=name)
    for _ in range(num_subs):
        sub_len = r.u32()
        sub_end = r.pos + sub_len
        sub_prop_len = r.u32()
        r.pos += sub_prop_len  # sub-geometry properties: skipped

        positions: list[float] = []
        indices: list[int] = []
        uvs: list[float] = []
        normals: list[float] = []

        while r.pos < sub_end:
            stream_type = r.u8()
            ftype = r.u8()
            slen = r.u32()
            if ftype not in _FTYPE:
                r.pos += slen
                continue
            fmt, size = _FTYPE[ftype]
            count = slen // size
            values = list(struct.unpack_from(f"<{count}{fmt}", r.buf, r.pos))
            r.pos += slen
            if stream_type == S_POSITIONS:
                positions = values
            elif stream_type == S_INDICES:
                indices = values
            elif stream_type == S_UVS:
                uvs = values
            elif stream_type == S_NORMALS:
                normals = values

        geo.subs.append(SubMesh(positions=positions, indices=indices,
                                uvs=uvs, normals=normals))
        r.pos = sub_end  # user attributes after streams: skipped
    return geo


def _parse_material(data: bytes) -> Material:
    r = _Reader(data)
    name = r.str16()
    mat_type = r.u16()
    props: dict[int, bytes] = {}
    prop_len = r.u32()
    end = r.pos + prop_len
    while r.pos < end:
        key = r.u16()
        props[key] = r.raw(r.u32())
    return Material(name=name, type=mat_type, props=props)


def _parse_instance(data: bytes) -> MeshInstance:
    r = _Reader(data)
    parent_id = r.u32()
    matrix = r.f32(12)
    name = r.str16()
    geometry_id = r.u32()
    mat_count = r.u16()
    material_ids = [r.u32() for _ in range(mat_count)]
    return MeshInstance(name=name, matrix=matrix, geometry_id=geometry_id,
                        material_ids=material_ids, parent_id=parent_id)


def _parse_clip(data: bytes) -> AnimationClip:
    return AnimationClip(name=_Reader(data).str16(), raw=data)


_IDENTITY12 = [1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0]


def _clean_name(geom_name: str) -> str:
    """Turn a geometry name like 'kristallin_geom' into a node name 'kristallin'."""
    return geom_name[:-5] if geom_name.endswith("_geom") else geom_name


def parse(raw: bytes, source: str = "<bytes>") -> Scene:
    """Parse raw .awd file bytes into a Scene."""
    body = decompress(raw)
    scene = Scene(source=source)
    for block_id, btype, data in _iter_blocks(body):
        if btype == T_GEOMETRY:
            scene.geometries[block_id] = _parse_geometry(data)
        elif btype == T_MATERIAL:
            scene.materials[block_id] = _parse_material(data)
        elif btype == T_MESH_INSTANCE:
            scene.instances.append(_parse_instance(data))
        elif btype == T_ANIM_CLIP:
            scene.clips.append(_parse_clip(data))
        # metadata / namespace / animation-set / animator: ignored

    # Some exporter variants store the instance transform as a 16x float64 matrix
    # with no usable name/geometry reference -> those instances don't resolve.
    # Drop unresolved instances and synthesize one per orphan geometry so every
    # geometry is still emitted with a sensible name.
    scene.instances = [i for i in scene.instances if i.geometry_id in scene.geometries]
    referenced_geo = {i.geometry_id for i in scene.instances}
    referenced_mat = {m for i in scene.instances for m in i.material_ids}

    # Orphan geometries sometimes carry their node name only on a sibling, unused
    # 'null~<name>' material block (no instance was exported). Pair them by nearest
    # block id so e.g. protegit's engine_0 keeps its name instead of 'geometry'.
    spare = sorted(mid for mid, m in scene.materials.items()
                   if mid not in referenced_mat and m.name.startswith("null~"))
    for gid in sorted(g for g in scene.geometries if g not in referenced_geo):
        name = _clean_name(scene.geometries[gid].name)
        material_ids: list[int] = []
        if name in ("", "geometry") and spare:
            mid = min(spare, key=lambda m: abs(m - gid))
            spare.remove(mid)
            name = scene.materials[mid].name[len("null~"):]
            material_ids = [mid]
        scene.instances.append(MeshInstance(
            name=name, matrix=list(_IDENTITY12), geometry_id=gid,
            material_ids=material_ids))
    return scene


def parse_file(path: str) -> Scene:
    with open(path, "rb") as f:
        return parse(f.read(), source=path)
