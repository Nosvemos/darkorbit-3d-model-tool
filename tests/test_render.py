"""Tests for the stable-crop / coordinate-adjustment logic in src.render.

Imports src.render (which pulls in pipeline + PIL but NOT bpy), so it runs in CI.
"""
from PIL import Image

from src.render import stable_crop


def _frame(path, size=32, box=(8, 8, 20, 16)):
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    for y in range(box[1], box[3]):
        for x in range(box[0], box[2]):
            im.putpixel((x, y), (200, 200, 200, 255))
    im.save(path)


def _raw(tmp):
    names = ["m_1.png", "m_2.png"]
    for n in names:
        _frame(tmp / n)
    return {"resolution": 32, "frames": names,
            "points": {"engine_0": [[10, 10], [10, 10]],
                       "laserpoint_x": [[10, 10], None]}}


def test_stable_crop_top_left(tmp_path):
    coords, meta = stable_crop(str(tmp_path), _raw(tmp_path), 0, "TOP_LEFT")
    assert meta["crop"] == [8, 8, 20, 16]
    assert meta["size"] == [12, 8]
    # point at (10,10) -> relative to crop origin (8,8) = (2,2)
    assert coords["engine_0"] == [[2, 2], [2, 2]]
    # off-screen frame becomes the "OFF" sentinel
    assert coords["laserpoint_x"] == [[2, 2], "OFF"]
    # frames physically cropped
    assert Image.open(tmp_path / "m_1.png").size == (12, 8)


def test_stable_crop_bottom_left_flips_y(tmp_path):
    coords, _ = stable_crop(str(tmp_path), _raw(tmp_path), 0, "BOTTOM_LEFT")
    # crop height 8 -> y' = (8-1) - 2 = 5
    assert coords["engine_0"] == [[2, 5], [2, 5]]


def test_stable_crop_padding(tmp_path):
    _, meta = stable_crop(str(tmp_path), _raw(tmp_path), 3, "TOP_LEFT")
    # padding expands the crop but stays clamped within the 32px frame
    assert meta["crop"] == [5, 5, 23, 19]


def test_render_args_overrides():
    import argparse
    from src.render import overrides_from_args, add_render_args
    parser = argparse.ArgumentParser()
    add_render_args(parser)
    args = parser.parse_args([
        "--no-rotation", "--anim-frame-start", "5", "--anim-frame-end", "15",
        "--sun-color", "#ffcc00", "--world-color", "#00ffcc",
        "--sun-energy", "2.5", "--world-strength", "1.2", "--quality", "high"
    ])
    ov = overrides_from_args(args)
    assert ov["rotation"] is False
    assert ov["anim_frame_start"] == 5
    assert ov["anim_frame_end"] == 15
    assert ov["sun_color"] == "#ffcc00"
    assert ov["world_color"] == "#00ffcc"
    assert ov["sun_energy"] == 2.5
    assert ov["world_strength"] == 1.2
    assert ov["quality"] == "high"


def test_render_preset_application(tmp_path, monkeypatch):
    import json
    import os
    from src import render as render_mod
    from src import config

    # Mock pipeline.convert and run_cmd to prevent actual Blender executions
    monkeypatch.setattr(render_mod, "convert", lambda *args, **kwargs: "/mocked.glb")
    monkeypatch.setattr(render_mod, "run_cmd", lambda *args, **kwargs: None)
    # Mock stable_crop to just return a dummy coordinate mapping
    monkeypatch.setattr(render_mod, "stable_crop", lambda *args, **kwargs: ({}, {}))

    # Point OUT_DIR to our isolated temp path
    monkeypatch.setattr(config, "OUT_DIR", str(tmp_path))

    # Create the sprites directory and place a dummy render_raw.json file there
    sprites = config.sprites_dir("dummy", str(tmp_path))
    os.makedirs(sprites, exist_ok=True)
    raw_path = os.path.join(sprites, "dummy_render_raw.json")
    with open(raw_path, "w") as f:
        json.dump({"resolution": 512, "frames": [], "points": {}}, f)

    # Call render with quality override
    render_mod.render("dummy", {"quality": "extra_low"})

    # Read generated render config file from work dir
    work_dir = config.work_dir("dummy", str(tmp_path))
    cfg_path = os.path.join(work_dir, "dummy_render_cfg.json")
    with open(cfg_path) as f:
        cfg = json.load(f)

    # Verify preset was correctly applied: extra_low has res=128, samples=16
    assert cfg["resolution"] == 128
    assert cfg["samples"] == 16
    assert cfg["quality"] == "extra_low"
