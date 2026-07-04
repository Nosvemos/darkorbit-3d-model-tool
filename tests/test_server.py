"""Tests for the web UI server's pure helpers (no sockets, no assets)."""
import os
import threading
import time

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


def test_jobs_are_queued_serially():
    gate = threading.Event()
    seen = []

    def first(_progress):
        seen.append("first")
        gate.wait(2)
        return {"ok": 1}

    def second(_progress):
        seen.append("second")
        return {"ok": 2}

    jid1 = server._start_job(first)
    jid2 = server._start_job(second)

    for _ in range(100):
        if server.api_job({"id": [jid1]})["status"] == "running":
            break
        time.sleep(0.01)

    queued = server.api_job({"id": [jid2]})
    assert queued["status"] == "queued"
    assert queued["queue_position"] >= 1
    assert seen == ["first"]

    gate.set()
    for _ in range(100):
        if server.api_job({"id": [jid2]})["status"] == "done":
            break
        time.sleep(0.01)

    assert server.api_job({"id": [jid1]})["status"] == "done"
    assert server.api_job({"id": [jid2]})["result"] == {"ok": 2}
    assert seen == ["first", "second"]
