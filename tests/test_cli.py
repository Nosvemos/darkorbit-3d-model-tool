"""Tests for the unified CLI argument parser and override mapping."""
import pytest

from src import render as render_mod
from src.cli import build_parser


def test_subcommand_dispatch():
    ap = build_parser()
    a = ap.parse_args(["info", "sibelon"])
    assert a.command == "info" and a.mesh == "sibelon" and a.func.__name__ == "cmd_info"
    a = ap.parse_args(["convert", "x", "--fx", "--gltf", "--no-blender"])
    assert a.fx and a.gltf and a.no_blender
    a = ap.parse_args(["list"])
    assert a.what == "all"
    a = ap.parse_args(["fx", "explosion0", "--frames", "12"])
    assert a.name == "explosion0" and a.frames == 12
    a = ap.parse_args(["ui", "--port", "9001", "--no-browser"])
    assert a.command == "ui" and a.port == 9001 and a.no_browser


def test_command_required():
    with pytest.raises(SystemExit):
        build_parser().parse_args([])


def test_render_overrides_mapping():
    ap = build_parser()
    a = ap.parse_args(["render", "m", "--frames", "8", "--persp",
                       "--no-crop", "--mode", "item", "--hdri", "city.exr"])
    ov = render_mod.overrides_from_args(a)
    assert ov["frames"] == 8
    assert ov["cam_ortho"] is False
    assert ov["stable_crop"] is False
    assert ov["mode"] == "item"
    assert ov["world_hdri"] == "city.exr"


def test_render_overrides_only_set_flags():
    ap = build_parser()
    a = ap.parse_args(["render", "m"])
    ov = render_mod.overrides_from_args(a)
    assert ov == {}  # nothing overridden -> all defaults apply
