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
