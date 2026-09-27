"""Shared mesh appearance presets and scale-to-bounds behavior."""
import json

from src import config, pipeline, server


def test_mesh_effect_presets_are_available_without_a_design():
    for name in ("frost", "inferno", "legend"):
        preset = config.resolve_effect_preset(name)
        appearance = config.appearance_ui_defaults(preset)
        recipes = config.design_particles(
            preset, config.appearance_settings(preset, {}), mesh_radius=50)

        assert preset["label"]
        assert appearance["design_color"].startswith("#")
        assert recipes
        assert all("scale_to_mesh" not in recipe for recipe in recipes)
        assert all(recipe["center_on_mesh"] for recipe in recipes)


def test_generic_effect_recipe_scale_tracks_mesh_radius():
    preset = config.resolve_effect_preset("frost")
    appearance = config.appearance_settings(preset, {})
    small = config.design_particles(preset, appearance, mesh_radius=50)
    large = config.design_particles(preset, appearance, mesh_radius=200)

    assert small[0]["scale"] == [.35, .35, .35]
    assert large[0]["scale"] == [1.4, 1.4, 1.4]
    assert config.effect_scale_for_radius(0) == 1
    assert config.effect_scale_for_radius(10000) == 3


def test_manual_appearance_works_without_design_or_particle_preset():
    preset, appearance = config.resolve_appearance_settings(
        "none", None, {"design_color": "#E02030", "rim_strength": 3.})

    assert preset is None
    assert appearance["rim_color"] == "#E02030"
    assert appearance["rim_strength"] == 3
    assert appearance["body_tint"] == 0


def test_auto_preset_keeps_supported_design_recipe():
    assert config.resolve_effect_preset("auto", "spectrum-frozen") is \
        config.DESIGNS["spectrum-frozen"]
    assert config.resolve_effect_preset("auto", None) is None


def test_scene_bounds_radius_ignores_points_and_hidden_parts():
    identity = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
    objects = [
        {"name": "body", "positions": [-1, -1, -1, 1, 1, 1],
         "matrix": identity},
        {"name": "engine_0", "positions": [-100, 0, 0, 100, 0, 0],
         "matrix": identity},
        {"name": "hidden", "positions": [-100, -100, -100, 100, 100, 100],
         "matrix": identity, "hide": True},
    ]

    assert abs(pipeline._scene_bounds_radius(objects) - 3 ** .5) < 1e-9


def test_api_info_exposes_generic_appearance_presets_for_unlisted_mesh(monkeypatch, tmp_path):
    class EmptyScene:
        instances = []
        clips = []

        @staticmethod
        def geometry_for(_instance):
            return None

    monkeypatch.setattr(server, "parse_file", lambda _path: EmptyScene())
    monkeypatch.setattr(server.pipeline, "detect_textures", lambda *args, **kwargs: {})
    monkeypatch.setattr(config, "MESHES_DIR", str(tmp_path))

    info = server.api_info({"name": ["custom-mesh"], "fx": ["0"]})

    assert info["designs"] == {}
    assert set(info["effect_presets"]) == {"frost", "inferno", "legend"}
    assert info["default_appearance"]["rim_strength"] == 0


def test_api_render_forwards_mesh_wide_preset_and_manual_values(monkeypatch, tmp_path):
    captured = {}

    def fake_render(name, overrides, **kwargs):
        captured.update(name=name, overrides=overrides, **kwargs)
        return str(tmp_path / "sprites")

    monkeypatch.setattr(server.render_mod, "render", fake_render)
    monkeypatch.setattr(config, "OUT_DIR", str(tmp_path))

    server.api_render({"name": "plain-mesh", "effect_preset": "legend",
                       "design_color": "#E5C020", "rim_strength": 5.5,
                       "particle_scale": 1.25})

    assert captured["effect_preset"] == "legend"
    assert captured["appearance_overrides"] == {
        "design_color": "#E5C020", "rim_strength": 5.5,
        "particle_scale": 1.25}
    assert captured["design"] is None


def test_convert_serializes_generic_appearance_and_bounds(tmp_path, monkeypatch):
    from tests import synth

    positions = [-10, -10, -10, 10, -10, -10, 0, 10, -10,
                 0, 0, 10]
    awd = synth.awd_file(
        synth.geometry_block(1, "body", positions, [0, 1, 2], [])
        + synth.instance_block(2, "body", [1, 0, 0, 0, 1, 0, 0, 0, 1,
                                             0, 0, 0], 1)
    )
    (tmp_path / "custom-mesh.awd").write_bytes(awd)
    out = tmp_path / "out"
    monkeypatch.setattr(config, "MESHES_DIR", str(tmp_path))
    monkeypatch.setattr(config, "TEXTURES_DIR", str(tmp_path))
    monkeypatch.setattr(config, "OUT_DIR", str(out))

    pipeline.convert("custom-mesh", run=False, effect_preset="inferno",
                     appearance_overrides={"rim_strength": 3.})

    scene_path = out / "custom-mesh" / "work" / "custom-mesh.scene.json"
    scene = json.loads(scene_path.read_text(encoding="utf-8"))
    assert scene["appearance"]["rim_strength"] == 3
    assert 10 <= scene["bounds_radius"] <= 18
