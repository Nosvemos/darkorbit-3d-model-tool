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
