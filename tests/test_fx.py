"""Tests for the .awp particle parser and value samplers (pure logic)."""
import json
import random

from src.fx import awp


def test_sample1d_const_and_random():
    assert awp.sample1d({"id": "OneDConstValueSubParser", "data": {"value": 3.5}},
                        random.Random(0)) == 3.5
    r = awp.sample1d({"id": "OneDRandomVauleSubParser", "data": {"min": 2, "max": 4}},
                     random.Random(1))
    assert 2.0 <= r <= 4.0


def test_sample3d_const_and_sphere():
    assert awp.sample3d({"id": "ThreeDConstValueSubParser",
                         "data": {"x": 1, "y": 2, "z": 3}}, random.Random(0)) == (1, 2, 3)
    x, y, z = awp.sample3d({"id": "ThreeDSphereValueSubParser",
                            "data": {"innerRadius": 1, "outerRadius": 1}}, random.Random(2))
    assert abs((x * x + y * y + z * z) ** 0.5 - 1.0) < 1e-6  # on the unit sphere


def test_segmented_color_endpoints_and_mid():
    node = {
        "startColor": {"data": {"mr": 1, "mg": 0, "mb": 0, "ma": 1}},
        "segmentPoints": [{"life": 0.5,
                           "color": {"data": {"mr": 0, "mg": 1, "mb": 0, "ma": 1}}}],
        "endColor": {"data": {"mr": 0, "mg": 0, "mb": 1, "ma": 0}},
    }
    assert awp.segmented_color(node, 0.0) == (1, 0, 0, 1)
    assert awp.segmented_color(node, 0.5) == (0, 1, 0, 1)
    assert awp.segmented_color(node, 1.0) == (0, 0, 1, 0)
    mid = awp.segmented_color(node, 0.75)               # between green and blue
    assert mid[2] == 0.5 and mid[1] == 0.5


def test_load_minimal_effect(tmp_path):
    doc = {
        "particleEvents": [{"name": "end", "occurTime": "1.6"}],
        "customParameters": {},
        "animationDatas": [{
            "data": {
                "name": "fireball",
                "material": {"data": {"url": "flame.png", "blendMode": "add"},
                             "id": "TextureMaterialSubParser"},
                "geometry": {"data": {"assembler": {"data": {
                    "shape": {"data": {"width": 50, "height": 40},
                              "id": "PlaneShapeSubParser"},
                    "num": 3}, "id": "SingleGeometrySubParser"}}},
                "nodes": [{"id": "ParticleTimeNodeSubParser",
                           "data": {"duration": {"id": "OneDConstValueSubParser",
                                                 "data": {"value": 0.8}}}}],
            },
            "property": {"data": {"playSpeed": {"id": "OneDConstValueSubParser",
                                                "data": {"value": 1}}},
                         "id": "InstancePropertySubParser"},
        }],
    }
    p = tmp_path / "fireball.awp"
    p.write_text(json.dumps(doc), encoding="utf-8")
    eff = awp.load(str(p))
    assert eff.name == "fireball"
    assert eff.duration == 1.6
    assert len(eff.layers) == 1
    layer = eff.layers[0]
    assert layer.texture_url == "flame.png"
    assert layer.blend_mode == "add"
    assert (layer.geom_w, layer.geom_h, layer.num) == (50, 40, 3)
    assert "ParticleTimeNodeSubParser" in layer.nodes
