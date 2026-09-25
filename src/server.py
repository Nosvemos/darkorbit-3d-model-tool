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
import queue
import re
import shutil
import threading
import time
import webbrowser
from concurrent.futures import CancelledError
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from src import config, fx_render, pipeline
from src import render as render_mod
from src.awd import parse_file

WEB_DIR = os.path.join(config.ROOT, "web")
_NUM = re.compile(r"(\d+)")
_PROFILE_OVERRIDE_KEYS = {
    key for profile in config.RENDER_PROFILES.values() for key in profile
}


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
            "textures": pipeline.detect_textures(name, tex_dir,
                                                  single_atf_fallback=fx),
            "channels": list(config.CHANNELS)}


def api_textures(q):
    """All available ATF basenames (textures/ + fx/), for the manual picker."""
    names = set()
    for d in (config.TEXTURES_DIR, config.FX_DIR):
        names.update(_stems(d, "*.atf"))
    return {"items": sorted(names)}


def api_convert(body, progress=None, control=None):
    name = body["name"]
    fx = bool(body.get("fx"))
    glb = pipeline.convert(name, gltf=bool(body.get("gltf")),
                           obj=bool(body.get("obj")), fx=fx,
                           textures=body.get("textures") or None,
                           clip=body.get("clip") or None,
                           overlay=body.get("overlay") or None,
                           output_name=body.get("output_name") or None,
                           hide_objects=body.get("hide_objects") or None,
                           progress=progress,
                           cancel_event=control.cancel_event if control else None,
                           process_callback=control.set_process if control else None)
    return {"ok": True, "glb": _rel_url(glb)}


def api_render(body, progress=None, control=None):
    name = body["name"]
    fx = bool(body.get("fx"))
    export_name = config.safe_output_name(body.get("output_name"), name)
    ov = {k: v for k, v in body.items()
          if k in config.RENDER_DEFAULTS and v not in (None, "")}
    # Profile-controlled browser fields are defaults, not user overrides.
    # Only fields the user edited after selecting a preset are sent in this
    # explicit map; this also keeps older open UI tabs from masking the preset.
    for key in _PROFILE_OVERRIDE_KEYS:
        ov.pop(key, None)
    profile_overrides = body.get("profile_overrides")
    if isinstance(profile_overrides, dict):
        for key, value in profile_overrides.items():
            if key in _PROFILE_OVERRIDE_KEYS and value is not None:
                ov[key] = value
    sprites = render_mod.render(name, ov, fx=fx, textures=body.get("textures") or None,
                                clip=body.get("clip") or None,
                                overlay=body.get("overlay") or None,
                                output_name=export_name, progress=progress,
                                cancel_event=control.cancel_event if control else None,
                                process_callback=control.set_process if control else None,
                                cancel_check=control.check_cancelled if control else None)
    base = config.FX_OUT if fx else config.OUT_DIR
    coords = os.path.join(sprites, f"{export_name}_Coords.json")
    glb = os.path.join(config.model_dir(export_name, base), f"{export_name}.glb")
    return {"ok": True, "frames": _frame_urls(sprites, export_name),
            "coords": _rel_url(coords) if os.path.exists(coords) else None,
            "glb": _rel_url(glb) if os.path.exists(glb) else None}


def api_fx(body, progress=None, control=None):
    name = body["name"]
    if progress:
        progress("simulating particles…")
    warnings = []
    sprites = fx_render.render(name, int(body.get("frames", 30)),
                               int(body.get("resolution", 256)),
                               float(body.get("margin", 1.2)),
                               output_name=body.get("output_name") or None,
                               warnings=warnings,
                               cancel_check=control.check_cancelled if control else None)
    export_name = config.safe_output_name(body.get("output_name"), name)
    archive = fx_render.frames_archive_path(sprites, export_name)
    return {"ok": True, "frames": _frame_urls(sprites, export_name),
            "archive": _rel_url(archive), "warnings": warnings}


# --- background jobs (so long Blender runs stream progress, don't block) -----

_JOBS: dict = {}
_LOCK = threading.Lock()
_SEQ = [0]
_QUEUE = queue.Queue()
_WORKER_STARTED = [False]
_RESERVED_OUTPUTS: dict[str, str] = {}


class JobControl:
    """Progress and cancellation hooks shared by one queued operation."""

    def __init__(self, jid: str, job: dict):
        self.jid = jid
        self.job = job
        self.cancel_event = job["cancel_event"]

    def __call__(self, line: str):
        with _LOCK:
            if self.job["status"] in {"done", "error", "cancelled"}:
                return
            self.job["log"].append(str(line))
            del self.job["log"][:-200]

    def check_cancelled(self):
        if self.cancel_event.is_set():
            raise CancelledError("job cancelled")

    def set_process(self, process):
        with _LOCK:
            self.job["process"] = process
            cancel = self.cancel_event.is_set()
        if process is not None and cancel:
            pipeline.stop_process(process)


def _remove_queued_job_locked(jid: str) -> bool:
    """Remove a queued item and keep Queue's unfinished-task accounting valid."""
    with _QUEUE.mutex:
        for item in list(_QUEUE.queue):
            if item[0] != jid:
                continue
            _QUEUE.queue.remove(item)
            _QUEUE.unfinished_tasks -= 1
            if _QUEUE.unfinished_tasks == 0:
                _QUEUE.all_tasks_done.notify_all()
            _QUEUE.not_full.notify()
            return True
    return False


def _mesh_output_base(fx: bool) -> str:
    return config.FX_OUT if fx else config.OUT_DIR


def _effect_output_conflict(sprites_dir: str, export_name: str) -> bool:
    if not os.path.isdir(sprites_dir):
        return False
    prefix = f"{export_name}_"
    archive = f"{export_name}_frames.zip"
    return any(name.startswith(prefix) for name in os.listdir(sprites_dir)) or \
        os.path.exists(os.path.join(sprites_dir, archive))


def _reserve_output_locked(jid: str, endpoint: str, body: dict) -> tuple[str, str, dict]:
    asset = str(body.get("name") or "asset")
    requested = config.safe_output_name(body.get("output_name"), asset)
    is_effect = endpoint == "/api/fx"
    fx = bool(body.get("fx"))
    if is_effect:
        fx_render._archive_name(asset)
        sprites_dir = config.effect_sprites_dir(asset)
        base = config.FX_EFFECTS_OUT
        reservation_prefix = os.path.realpath(sprites_dir).casefold()
    else:
        base = _mesh_output_base(fx)
        sprites_dir = ""
        reservation_prefix = os.path.realpath(base).casefold()

    export_name = requested
    suffix = 0
    while True:
        key = f"{reservation_prefix}|{export_name.casefold()}"
        if is_effect:
            conflict = _effect_output_conflict(sprites_dir, export_name)
        else:
            conflict = os.path.exists(config.mesh_dir(export_name, base))
        if key not in _RESERVED_OUTPUTS and not conflict:
            break
        suffix += 1
        tail = f"__job{jid}" if suffix == 1 else f"__job{jid}_{suffix}"
        export_name = config.safe_output_name(f"{requested}{tail}", asset)

    _RESERVED_OUTPUTS[key] = jid
    body["output_name"] = export_name
    cleanup = ({"kind": "effect", "base": base, "directory": sprites_dir,
                "export_name": export_name} if is_effect else
               {"kind": "tree", "base": base,
                "path": config.mesh_dir(export_name, base)})
    return export_name, key, cleanup


def _cleanup_job_outputs(job: dict) -> int:
    """Remove only output paths reserved as new and owned by this job."""
    spec = job.get("cleanup") or {}
    try:
        base = os.path.realpath(spec.get("base", ""))
        if spec.get("kind") == "tree":
            raw_path = os.path.abspath(spec.get("path", ""))
            if os.path.islink(raw_path):
                return -1
            path = os.path.realpath(raw_path)
            if not base or path == base or os.path.commonpath([base, path]) != base:
                return -1
            if not os.path.isdir(path):
                return 0
            shutil.rmtree(path)
            return 1
        if spec.get("kind") == "effect":
            raw_directory = os.path.abspath(spec.get("directory", ""))
            if os.path.islink(raw_directory):
                return -1
            directory = os.path.realpath(raw_directory)
            if not base or directory == base or os.path.commonpath([base, directory]) != base:
                return -1
            export_name = spec["export_name"]
            frame_pattern = re.compile(rf"^{re.escape(export_name)}_\d+\.png$")
            archive_names = {f"{export_name}_frames.zip",
                             f"{export_name}_frames.zip.tmp"}
            removed = 0
            for filename in os.listdir(directory) if os.path.isdir(directory) else ():
                if frame_pattern.fullmatch(filename) or filename in archive_names:
                    path = os.path.join(directory, filename)
                    if os.path.isfile(path) and not os.path.islink(path):
                        os.remove(path)
                        removed += 1
            return removed
    except (OSError, ValueError, KeyError):
        return -1
    return 0


def _release_reservation_locked(job: dict):
    key = job.get("reservation_key")
    if key and _RESERVED_OUTPUTS.get(key) == job.get("id"):
        _RESERVED_OUTPUTS.pop(key, None)


def _job_worker():
    while True:
        jid, fn = _QUEUE.get()
        with _LOCK:
            job = _JOBS.get(jid)
            if job and job["status"] == "queued":
                job["status"] = "running"
                job["started_at"] = time.time()
                job["log"].append("started")
            else:
                job = None
        if not job:
            _QUEUE.task_done()
            continue
        control = JobControl(jid, job)
        try:
            control.check_cancelled()
            result = fn(control)
            control.check_cancelled()
            with _LOCK:
                if job["cancel_event"].is_set():
                    raise CancelledError("job cancelled")
                job["result"] = result
                job["status"] = "done"
        except BaseException as e:   # incl. SystemExit, so failures never hang the job
            if job["cancel_event"].is_set() or isinstance(e, CancelledError):
                removed = _cleanup_job_outputs(job)
                with _LOCK:
                    job["result"] = None
                    job["status"] = "cancelled"
                    if removed < 0:
                        job["log"].append("cancelled · automatic output cleanup failed")
                    else:
                        job["log"].append(
                            f"cancelled · cleaned {removed} output item(s)" if removed
                            else "cancelled · partial outputs cleaned")
            else:
                with _LOCK:
                    job["error"] = str(e) or e.__class__.__name__
                    job["status"] = "error"
        finally:
            with _LOCK:
                job["process"] = None
                job["finished_at"] = time.time()
                _release_reservation_locked(job)
            _QUEUE.task_done()


def _ensure_worker_locked():
    if _WORKER_STARTED[0]:
        return
    threading.Thread(target=_job_worker, daemon=True).start()
    _WORKER_STARTED[0] = True


def _queue_position(jid: str) -> int:
    with _QUEUE.mutex:
        ids = [item[0] for item in list(_QUEUE.queue)]
    return ids.index(jid) + 1 if jid in ids else 0


def _start_job(fn, endpoint=None, body=None):
    with _LOCK:
        _SEQ[0] += 1
        jid = str(_SEQ[0])
        job = {"id": jid, "status": "queued", "log": ["queued"],
               "result": None, "error": None, "cancel_event": threading.Event(),
               "process": None, "created_at": time.time(), "started_at": None,
               "finished_at": None, "cleanup": None, "reservation_key": None,
               "job_type": endpoint or "job", "asset": "", "output_name": ""}
        if endpoint and body is not None:
            job["asset"] = str(body.get("name") or "asset")
            job["fx"] = bool(body.get("fx"))
            job["requested_output_name"] = config.safe_output_name(
                body.get("output_name"), job["asset"])
            output_name, reservation_key, cleanup = _reserve_output_locked(jid, endpoint, body)
            job["output_name"] = output_name
            job["reservation_key"] = reservation_key
            job["cleanup"] = cleanup
        _JOBS[jid] = job
        _QUEUE.put((jid, fn))
        _ensure_worker_locked()
    return jid


def api_job(q):
    jid = q.get("id", [""])[0]
    with _LOCK:
        job = _JOBS.get(jid)
        if not job:
            return {"status": "unknown"}
        result = {key: value for key, value in job.items()
                  if key not in {"cancel_event", "process", "cleanup", "reservation_key"}}
        result["log"] = job["log"][-8:]
        result["cancelable"] = job["status"] in {"queued", "running"}
    result["queue_position"] = _queue_position(jid)
    return result


def api_jobs(_q=None):
    with _LOCK:
        jobs = list(_JOBS.values())
        views = []
        for job in jobs:
            result = job.get("result") or {}
            summary = {key: value for key, value in result.items() if key != "frames"}
            if result.get("frames") is not None:
                summary["frame_count"] = len(result["frames"])
                if result["frames"]:
                    summary["first_frame"] = result["frames"][0]
            views.append({
                "id": job["id"], "status": job["status"], "log": job["log"][-3:],
                "result": summary or None, "error": job["error"],
                "job_type": job["job_type"], "asset": job["asset"],
                "fx": job.get("fx", False), "output_name": job["output_name"],
                "requested_output_name": job.get("requested_output_name", ""),
                "created_at": job["created_at"], "started_at": job["started_at"],
                "finished_at": job["finished_at"],
                "cancelable": job["status"] in {"queued", "running"},
            })
    for view in views:
        view["queue_position"] = _queue_position(view["id"])
    active = [j for j in views if j["status"] in {"running", "cancelling"}]
    queued = sorted((j for j in views if j["status"] == "queued"),
                    key=lambda j: j["queue_position"])
    history = sorted((j for j in views if j["status"] in {"done", "error", "cancelled"}),
                     key=lambda j: int(j["id"]), reverse=True)[:12]
    return {"jobs": active + queued + history,
            "counts": {"running": len(active), "queued": len(queued),
                       "finished": len(history)}}


def api_cancel_job(jid: str):
    process = None
    queued_cancel = False
    with _LOCK:
        job = _JOBS.get(str(jid))
        if not job:
            return {"ok": False, "status": "unknown", "error": "job not found"}
        status = job["status"]
        if status == "queued":
            job["cancel_event"].set()
            _remove_queued_job_locked(str(jid))
            job["status"] = "cancelled"
            job["finished_at"] = time.time()
            job["log"].append("cancelled before start")
            queued_cancel = True
        elif status == "running":
            job["cancel_event"].set()
            job["status"] = "cancelling"
            job["log"].append("cancellation requested")
            process = job.get("process")
        elif status == "cancelling":
            return {"ok": True, "status": "cancelling"}
        else:
            return {"ok": False, "status": status,
                    "error": f"job is already {status}"}

    if process is not None:
        pipeline.stop_process(process)
    if queued_cancel:
        with _LOCK:
            job["log"].append("cancelled · no output was created")
            _release_reservation_locked(job)
    return {"ok": True, "status": "cancelling" if not queued_cancel else "cancelled"}


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
            if path == "/api/jobs":
                return self._send(200, api_jobs(q))
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
        if u.path == "/api/job/cancel":
            result = api_cancel_job(str(body.get("id") or ""))
            return self._send(200 if result["ok"] else 404, result)
        routes = {"/api/convert": api_convert, "/api/render": api_render,
                  "/api/fx": api_fx}
        fn = routes.get(u.path)
        if not fn:
            return self._send(404, {"error": "not found"})
        # run as a background job and return its id; the UI polls /api/job
        try:
            jid = _start_job(lambda control: fn(body, control, control=control),
                             endpoint=u.path, body=body)
        except (OSError, ValueError) as e:
            return self._send(400, {"error": str(e)})
        self._send(200, {"job": jid, "output_name": _JOBS[jid]["output_name"]})

    def _send_file(self, abs_path):
        if not os.path.isfile(abs_path):
            return self._send(404, {"error": "not found"})
        ctype = {"html": "text/html", "png": "image/png", "json": "application/json",
                 "zip": "application/zip", "glb": "model/gltf-binary"}.get(abs_path.rsplit(".", 1)[-1],
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
