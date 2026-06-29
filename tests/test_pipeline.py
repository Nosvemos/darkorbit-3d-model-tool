"""Tests for texture resolution / detection (no decoding, no Blender)."""
from src import pipeline


def test_resolve_atf(tmp_path):
    (tmp_path / "foo.atf").write_bytes(b"x")
    d = [str(tmp_path)]
    assert pipeline._resolve_atf("foo", d) == str(tmp_path / "foo.atf")
    assert pipeline._resolve_atf("foo.atf", d) == str(tmp_path / "foo.atf")  # ext tolerated
    assert pipeline._resolve_atf("missing", d) is None


def test_find_texture_prefers_higher_resolution(tmp_path):
    (tmp_path / "ship_diffuse_256.atf").write_bytes(b"x")
    (tmp_path / "ship_diffuse_512.atf").write_bytes(b"x")
    assert pipeline._find_texture(str(tmp_path), "ship", "diffuse").endswith("_512.atf")


def test_detect_textures(tmp_path):
    (tmp_path / "ship_diffuse_512.atf").write_bytes(b"x")
    (tmp_path / "ship_normal_256.atf").write_bytes(b"x")
    assert pipeline.detect_textures("ship", str(tmp_path)) == {
        "diffuse": "ship_diffuse_512", "normal": "ship_normal_256"}


def test_build_scene_with_overlay(tmp_path):
    from tests import synth
    import json
    # Create main awd
    main_geom = synth.geometry_block(3, "main_geom", [1.0, 2.0, 3.0], [0, 0, 0], [])
    main_inst = synth.instance_block(4, "main_inst", [1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0], 3)
    main_awd = synth.awd_file(main_geom + main_inst)
    (tmp_path / "main.awd").write_bytes(main_awd)

    # Create overlay awd
    over_geom = synth.geometry_block(3, "over_geom", [4.0, 5.0, 6.0], [0, 0, 0], [])
    over_inst = synth.instance_block(4, "over_inst", [1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0], 3)
    over_awd = synth.awd_file(over_geom + over_inst)
    (tmp_path / "over.awd").write_bytes(over_awd)

    # Call build_scene_json
    json_path = pipeline.build_scene_json(
        "main", str(tmp_path), str(tmp_path), str(tmp_path), str(tmp_path),
        overlay="over"
    )

    with open(json_path) as f:
        data = json.load(f)

    # Verify both instances exist
    names = [obj["name"] for obj in data["objects"]]
    assert "main_inst" in names
    assert "over_inst" in names
