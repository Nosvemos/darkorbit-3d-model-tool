"""Tests for the web UI server's pure helpers (no sockets, no assets)."""
import os

from src import config, server


def test_natural_sort_orders_frames_numerically():
    names = ["m_10.png", "m_2.png", "m_1.png"]
    assert sorted(names, key=lambda n: server._natural(n)) == \
        ["m_1.png", "m_2.png", "m_10.png"]


def test_rel_url_maps_under_out():
    p = os.path.join(config.OUT_DIR, "sibelon", "sprites", "sibelon_1.png")
    assert server._rel_url(p) == "/out/sibelon/sprites/sibelon_1.png"


def test_api_list_unknown_kind_defaults_to_meshes(tmp_path, monkeypatch):
    # point the meshes dir at an empty tmp dir so this needs no real assets
    monkeypatch.setattr(config, "MESHES_DIR", str(tmp_path))
    out = server.api_list({"kind": ["meshes"]})
    assert out == {"kind": "meshes", "items": []}
