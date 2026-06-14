"""AWD2 parser tests on synthetic byte streams (no game assets needed)."""
import struct

import pytest

from src.awd import parse
from src.awd.parser import _Reader, decompress
from tests import synth

# a unit cube-ish geometry: 3 verts, 1 triangle, with UVs
POS = [0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0]
IDX = [0, 1, 2]
UV = [0.0, 0.0, 1.0, 0.0, 0.0, 1.0]
IDENT12 = [1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0]


def _single_mesh_awd(magic=b"AWDc", geom_prop_len=0):
    blocks = (
        synth.geometry_block(1, "ship_geom", POS, IDX, UV, geom_prop_len)
        + synth.material_block(2, "ship_mat")
        + synth.instance_block(3, "ship", IDENT12, geom_id=1, material_ids=[2])
    )
    return synth.awd_file(blocks, magic)


def test_reader_basic():
    r = _Reader(struct.pack("<IHB", 7, 5, 9) + synth._str16("hi"))
    assert r.u32() == 7
    assert r.u16() == 5
    assert r.u8() == 9
    assert r.str16() == "hi"


def test_decompress_rejects_bad_magic():
    with pytest.raises(ValueError):
        decompress(b"XYZ" + b"\x00" * 20)


def test_parse_single_mesh():
    scene = parse(_single_mesh_awd())
    assert len(scene.instances) == 1
    inst = scene.instances[0]
    assert inst.name == "ship"
    geo = scene.geometry_for(inst)
    assert geo is not None
    assert geo.vertex_count == 3
    assert geo.triangle_count == 1
    sub = geo.subs[0]
    assert sub.positions == POS
    assert sub.indices == IDX
    assert sub.uvs == UV
    assert [m.name for m in scene.materials_for(inst)] == ["ship_mat"]


@pytest.mark.parametrize("magic", [b"AWDc", b"AWD\x02"])
def test_both_header_variants(magic):
    scene = parse(_single_mesh_awd(magic))
    assert scene.geometries[1].vertex_count == 3


def test_geometry_property_skip_regression():
    """Non-zero geometry property block must be skipped correctly.

    Guards the `r.pos += r.u32()` augmented-assignment bug, where the left side
    is read before u32() advances it, silently dropping the 4-byte length read.
    """
    scene = parse(_single_mesh_awd(geom_prop_len=12))
    assert scene.geometries[1].vertex_count == 3
    assert scene.geometries[1].subs[0].positions == POS


def test_vertex_clip_frames_parsed():
    pose_a = [0.0] * 9                         # 3 verts, flat
    pose_b = [1.0, 2.0, 3.0] + [0.0] * 6
    blocks = (
        synth.geometry_block(1, "ship_geom", POS, IDX, UV)
        + synth.instance_block(2, "ship", IDENT12, geom_id=1)
        + synth.vertex_clip_block(3, "idle", [pose_a, pose_b])
    )
    scene = parse(synth.awd_file(blocks))
    assert len(scene.clips) == 1
    clip = scene.clips[0]
    assert clip.name == "idle"
    assert clip.geometry_id == 1
    assert clip.frames == [pose_a, pose_b]


def test_point_classification_and_orphan_naming():
    # one body, one engine point (instanced), one orphan geometry with a null~ material
    blocks = (
        synth.geometry_block(1, "ship_geom", POS, IDX, UV)
        + synth.instance_block(2, "ship", IDENT12, geom_id=1)
        + synth.geometry_block(3, "engine_0_geom", POS, IDX, UV)
        + synth.instance_block(4, "engine_0", IDENT12, geom_id=3)
        + synth.geometry_block(5, "geometry", POS, IDX, UV)   # orphan, generic name
        + synth.material_block(6, "null~laserpoint_front")    # unused -> names the orphan
    )
    scene = parse(synth.awd_file(blocks))
    by_name = {i.name: i for i in scene.instances}
    assert by_name["engine_0"].is_point
    assert not by_name["ship"].is_point
    # orphan geometry recovered its name from the null~ material
    assert "laserpoint_front" in by_name
    assert by_name["laserpoint_front"].is_point
