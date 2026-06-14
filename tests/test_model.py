"""Tests for the AWD intermediate model dataclasses."""
from src.awd.model import Geometry, MeshInstance, Scene, SubMesh


def test_submesh_counts():
    sub = SubMesh(positions=[0] * 9, indices=[0, 1, 2], uvs=[0] * 6)
    assert sub.vertex_count == 3
    assert sub.triangle_count == 1


def test_instance_translation_and_matrix_rows():
    # column-major 3x4: translation is the 4th column (m9, m10, m11)
    mtx = [1, 0, 0, 0, 1, 0, 0, 0, 1, 5, 6, 7]
    inst = MeshInstance(name="x", matrix=mtx, geometry_id=1)
    assert inst.translation == (5, 6, 7)
    rows = inst.matrix_rows()
    assert rows[0] == [1, 0, 0, 5]
    assert rows[1] == [0, 1, 0, 6]
    assert rows[2] == [0, 0, 1, 7]
    assert rows[3] == [0, 0, 0, 1]


def test_is_point_prefixes():
    assert MeshInstance("engine_0", [], 1).is_point
    assert MeshInstance("laserpoint_left", [], 1).is_point
    assert MeshInstance("light_position", [], 1).is_point
    assert not MeshInstance("sibelon", [], 1).is_point


def test_scene_lookup_and_summary():
    scene = Scene(source="x")
    scene.geometries[1] = Geometry("g", [SubMesh([0] * 9, [0, 1, 2])])
    inst = MeshInstance("ship", [1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0], 1)
    scene.instances.append(inst)
    assert scene.geometry_for(inst).name == "g"
    assert "ship" in scene.summary()
