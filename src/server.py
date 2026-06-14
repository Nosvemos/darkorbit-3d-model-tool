"""Tiny local web UI for the toolkit — Python stdlib only (no web framework).

Serves a single static page (web/index.html) plus a small JSON API that drives
the existing pipeline / render / fx functions and exposes the output files so the
browser can preview sprite turntables and download the glb.

    python -m src ui            # then open http://127.0.0.1:8765
"""
from __future__ import annotations

import glob
import json
import os
import re
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from src import config, fx_render, pipeline
from src import render as render_mod
from src.awd import parse_file

WEB_DIR = os.path.join(config.ROOT, "web")
_NUM = re.compile(r"(\d+)")


def _stems(directory, pattern):
    return [os.path.splitext(os.path.basename(p))[0]
            for p in sorted(glob.glob(os.path.join(directory, pattern)))]


def _natural(name):
    return [int(t) if t.isdigit() else t for t in _NUM.split(name)]


def _rel_url(abs_path):
    """Map an absolute path under OUT_DIR to a /out/... URL."""
    rel = os.path.relpath(abs_path, config.OUT_DIR).replace(os.sep, "/")
    return "/out/" + rel


def _frame_urls(sprites_dir, name):
    files = sorted(glob.glob(os.path.join(sprites_dir, f"{name}_*.png")),
                   key=lambda p: _natural(os.path.basename(p)))
    return [_rel_url(p) for p in files]


# --- API handlers (return python objects, serialised as JSON) ---------------

def api_list(q):
    kind = q.get("kind", ["meshes"])[0]
    groups = {
        "meshes": (config.MESHES_DIR, "*.awd"),
        "fx": (config.FX_DIR, "*.awd"),
        "effects": (config.FX_DIR, "*.zip"),
    }
    directory, pattern = groups.get(kind, groups["meshes"])
    return {"kind": kind, "items": _stems(directory, pattern)}


def api_info(q):
    name = q["name"][0]
    fx = q.get("fx", ["0"])[0] == "1"
    src = config.FX_DIR if fx else config.MESHES_DIR
    scene = parse_file(os.path.join(src, f"{name}.awd"))
    tex_dir = config.FX_DIR if fx else config.TEXTURES_DIR
    objects = []
    for inst in scene.instances:
        geo = scene.geometry_for(inst)
        objects.append({"name": inst.name, "point": inst.is_point,
                        "verts": geo.vertex_count if geo else 0,
                        "tris": geo.triangle_count if geo else 0})
    return {"name": name, "objects": objects,
            "clips": [c.name for c in scene.clips],
            "textures": pipeline.detect_textures(name, tex_dir),
            "channels": list(config.CHANNELS)}


def api_textures(q):
    """All available ATF basenames (textures/ + fx/), for the manual picker."""
    names = set()
    for d in (config.TEXTURES_DIR, config.FX_DIR):
        names.update(_stems(d, "*.atf"))
    return {"items": sorted(names)}


def api_convert(body, progress=None):
    name = body["name"]
    fx = bool(body.get("fx"))
    glb = pipeline.convert(name, gltf=bool(body.get("gltf")),
                           obj=bool(body.get("obj")), fx=fx,
                           textures=body.get("textures") or None,
                           clip=body.get("clip") or None, progress=progress)
    return {"ok": True, "glb": _rel_url(glb)}


def api_render(body, progress=None):
    name = body["name"]
    fx = bool(body.get("fx"))
    ov = {k: v for k, v in body.items()
          if k in config.RENDER_DEFAULTS and v not in (None, "")}
    sprites = render_mod.render(name, ov, fx=fx, textures=body.get("textures") or None,
                                clip=body.get("clip") or None, progress=progress)
    base = config.FX_OUT if fx else config.OUT_DIR
    coords = os.path.join(sprites, f"{name}_Coords.json")
    glb = os.path.join(config.model_dir(name, base), f"{name}.glb")
    return {"ok": True, "frames": _frame_urls(sprites, name),
            "coords": _rel_url(coords) if os.path.exists(coords) else None,
            "glb": _rel_url(glb) if os.path.exists(glb) else None}


def api_fx(body, progress=None):
    name = body["name"]
    if progress:
        progress("simulating particles…")
    sprites = fx_render.render(name, int(body.get("frames", 30)),
                               int(body.get("resolution", 256)),
                               float(body.get("margin", 1.2)))
    return {"ok": True, "frames": _frame_urls(sprites, name)}


# --- background jobs (so long Blender runs stream progress, don't block) -----

_JOBS: dict = {}
_LOCK = threading.Lock()
_SEQ = [0]


def _start_job(fn):
    with _LOCK:
        _SEQ[0] += 1
        jid = str(_SEQ[0])
    job = {"status": "running", "log": [], "result": None, "error": None}
    _JOBS[jid] = job

    def run():
        def prog(line):
            job["log"].append(line)
            del job["log"][:-200]               # keep the tail bounded
        try:
            job["result"] = fn(prog)
            job["status"] = "done"
        except BaseException as e:   # incl. SystemExit, so failures never hang the job
            job["error"] = str(e) or e.__class__.__name__
            job["status"] = "error"

    threading.Thread(target=run, daemon=True).start()
    return jid


def api_job(q):
    job = _JOBS.get(q.get("id", [""])[0])
    if not job:
        return {"status": "unknown"}
    return {"status": job["status"], "log": job["log"][-8:],
            "result": job["result"], "error": job["error"]}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass  # quiet

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urlparse(self.path)
        path, q = u.path, parse_qs(u.query)
        try:
            if path == "/" or path == "/index.html":
                return self._send_file(os.path.join(WEB_DIR, "index.html"))
            if path == "/api/list":
                return self._send(200, api_list(q))
            if path == "/api/info":
                return self._send(200, api_info(q))
            if path == "/api/textures":
                return self._send(200, api_textures(q))
            if path == "/api/job":
                return self._send(200, api_job(q))
            if path.startswith("/out/"):
                return self._send_file(os.path.join(
                    config.OUT_DIR, path[len("/out/"):].replace("/", os.sep)))
            self._send(404, {"error": "not found"})
        except Exception as e:
            self._send(500, {"error": str(e)})

    def do_POST(self):
        u = urlparse(self.path)
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        routes = {"/api/convert": api_convert, "/api/render": api_render,
                  "/api/fx": api_fx}
        fn = routes.get(u.path)
        if not fn:
            return self._send(404, {"error": "not found"})
        # run as a background job and return its id; the UI polls /api/job
        jid = _start_job(lambda prog: fn(body, prog))
        self._send(200, {"job": jid})

    def _send_file(self, abs_path):
        if not os.path.isfile(abs_path):
            return self._send(404, {"error": "not found"})
        ctype = {"html": "text/html", "png": "image/png", "json": "application/json",
                 "glb": "model/gltf-binary"}.get(abs_path.rsplit(".", 1)[-1],
                                                 "application/octet-stream")
        with open(abs_path, "rb") as f:
            self._send(200, f.read(), ctype)


def serve(host="127.0.0.1", port=8765, open_browser=True):
    httpd = ThreadingHTTPServer((host, port), Handler)
    url = f"http://{host}:{port}"
    print(f"DarkOrbit 3D tool UI -> {url}  (Ctrl+C to stop)")
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
