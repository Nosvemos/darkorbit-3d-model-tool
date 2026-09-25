"""Tiny local web UI for the toolkit — Python stdlib only (no web framework).

Serves a single static page (web/index.html) plus a small JSON API that drives
the existing pipeline / render / fx functions and exposes the output files so the
browser can preview sprite turntables and download the glb.

    python -m src ui            # then open http://127.0.0.1:8765
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import queue
import re
import shutil
import tempfile
import threading
import time
import webbrowser
from concurrent.futures import CancelledError
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from src import config, fx_render, pipeline
from src import render as render_mod
from src.awd import parse_file

if os.name == "nt":
    import msvcrt
else:
    import fcntl

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
    export_name = config.safe_output_name(body.get("output_name"), name)
    glb = pipeline.convert(name, gltf=bool(body.get("gltf")),
                           obj=bool(body.get("obj")), run=bool(body.get("run", True)), fx=fx,
                           textures=body.get("textures") or None,
                           clip=body.get("clip") or None,
                           overlay=body.get("overlay") or None,
                           output_name=export_name,
                           hide_objects=body.get("hide_objects") or None,
                           progress=progress,
                           cancel_event=control.cancel_event if control else None,
                           process_callback=control.set_process if control else None)
    scene = os.path.join(config.work_dir(export_name, _mesh_output_base(fx)),
                         f"{export_name}.scene.json")
    return {"ok": True,
            "glb": _rel_url(glb) if os.path.exists(glb) else None,
            "scene": _rel_url(scene) if os.path.exists(scene) else None}


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
_QUEUE_WAKE = threading.Event()
_QUEUE_PAUSED = [False]
_WORKER_STARTED = [False]
_RESERVED_OUTPUTS: dict[str, dict] = {}


def _try_output_lock(key: str):
    """Reserve an output basename across independent web and CLI workers."""
    lock_dir = os.path.join(tempfile.gettempdir(), "darkorbit-3d-tool-queue-locks")
    os.makedirs(lock_dir, exist_ok=True)
    lock_name = hashlib.sha256(key.encode("utf-8")).hexdigest() + ".lock"
    handle = open(os.path.join(lock_dir, lock_name), "a+b")
    try:
        if os.fstat(handle.fileno()).st_size == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                handle.close()
                return None
        else:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                handle.close()
                return None
        return handle
    except BaseException:
        if not handle.closed:
            handle.close()
        raise


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
    key = f"{reservation_prefix}|{export_name.casefold()}"
    reservation = _RESERVED_OUTPUTS.get(key)
    if reservation is None:
        reservation_handle = _try_output_lock(key)
        if reservation_handle is None:
            raise OSError(
                f"Export '{export_name}' is currently in use by another queue. "
                "Wait for that job to finish, then submit this export again.")
        reservation = {"jobs": set(), "handle": reservation_handle}
        _RESERVED_OUTPUTS[key] = reservation
    reservation["jobs"].add(jid)
    body["output_name"] = export_name
    if is_effect:
        cleanup = {"kind": "effect", "base": base, "directory": sprites_dir,
                   "export_name": export_name}
    else:
        output_path = config.mesh_dir(export_name, base)
        cleanup = {"kind": "tree", "base": base, "path": output_path}
        if endpoint == "/api/convert" and not body.get("run", True) and \
                os.path.lexists(output_path):
            cleanup["preserve_existing"] = True
    return export_name, key, cleanup


def _remove_output_path(path: str) -> None:
    """Remove one output path without following a symlink at its root."""
    if os.path.islink(path) or os.path.isfile(path):
        os.remove(path)
    elif os.path.isdir(path):
        shutil.rmtree(path)


def _output_path(base: str, path: str) -> str:
    """Resolve an output path and ensure it stays beneath its configured base."""
    real_base = os.path.realpath(base)
    raw_path = os.path.abspath(path)
    if os.path.islink(raw_path):
        raise OSError(f"Refusing to replace symlink output: {raw_path}")
    real_path = os.path.realpath(raw_path)
    if not real_base or real_path == real_base or \
            os.path.commonpath([real_base, real_path]) != real_base:
        raise OSError(f"Output path is outside its configured folder: {raw_path}")
    return real_path


def _effect_output_names(directory: str, export_name: str) -> list[str]:
    if not os.path.isdir(directory):
        return []
    frame_pattern = re.compile(rf"^{re.escape(export_name)}_\d+\.png$", re.IGNORECASE)
    archive_names = {f"{export_name}_frames.zip".casefold(),
                     f"{export_name}_frames.zip.tmp".casefold()}
    return [filename for filename in os.listdir(directory)
            if frame_pattern.fullmatch(filename) or filename.casefold() in archive_names]


def _begin_output_update(job: dict) -> None:
    """Move the previous export aside before writing the canonical basename."""
    spec = job.get("cleanup") or {}
    base = os.path.realpath(spec.get("base", ""))
    os.makedirs(base, exist_ok=True)
    if spec.get("kind") == "tree":
        target = _output_path(base, spec["path"])
        if spec.get("preserve_existing") and os.path.lexists(target):
            # --no-blender writes scene intermediates but does not replace the
            # existing GLB/export folder; leave that folder in place.
            job["_output_started"] = False
            return
        if os.path.lexists(target):
            backup_dir = tempfile.mkdtemp(prefix=".darkorbit-output-backup-", dir=base)
            backup_path = os.path.join(backup_dir, os.path.basename(target))
            try:
                os.replace(target, backup_path)
            except BaseException:
                _remove_output_path(backup_dir)
                raise
            job["_output_backup"] = {"kind": "tree", "directory": backup_dir,
                                     "path": backup_path}
        job["_output_started"] = True
        return

    if spec.get("kind") == "effect":
        directory = _output_path(base, spec["directory"])
        filenames = _effect_output_names(directory, spec["export_name"])
        if not filenames:
            job["_output_started"] = True
            return
        backup_dir = tempfile.mkdtemp(prefix=".darkorbit-output-backup-", dir=base)
        moved = []
        try:
            for filename in filenames:
                source = os.path.join(directory, filename)
                if os.path.islink(source) or not os.path.isfile(source):
                    raise OSError(f"Refusing to replace non-file effect output: {source}")
                os.replace(source, os.path.join(backup_dir, filename))
                moved.append(filename)
        except BaseException:
            os.makedirs(directory, exist_ok=True)
            for filename in moved:
                os.replace(os.path.join(backup_dir, filename),
                           os.path.join(directory, filename))
            _remove_output_path(backup_dir)
            raise
        job["_output_backup"] = {"kind": "effect", "directory": backup_dir,
                                 "target_directory": directory, "files": moved}
        job["_output_started"] = True
        return

    raise ValueError("unknown output reservation type")


def _restore_output_update(job: dict) -> tuple[int, bool]:
    """Discard failed partial output and restore the last successful export."""
    if not job.pop("_output_started", False):
        return 0, True
    removed = _cleanup_job_outputs(job)
    if removed < 0:
        return removed, False
    backup = job.get("_output_backup")
    if not backup:
        return removed, True
    try:
        if backup["kind"] == "tree":
            target = _output_path(job["cleanup"]["base"], job["cleanup"]["path"])
            os.replace(backup["path"], target)
        else:
            target_directory = _output_path(job["cleanup"]["base"],
                                            backup["target_directory"])
            os.makedirs(target_directory, exist_ok=True)
            for filename in backup["files"]:
                os.replace(os.path.join(backup["directory"], filename),
                           os.path.join(target_directory, filename))
        _remove_output_path(backup["directory"])
        job.pop("_output_backup", None)
        return removed, True
    except (OSError, ValueError, KeyError):
        return removed, False


def _discard_output_backup(job: dict) -> bool:
    backup = job.get("_output_backup")
    if not backup:
        job.pop("_output_started", None)
        return True
    try:
        _remove_output_path(backup["directory"])
        job.pop("_output_backup", None)
        job.pop("_output_started", None)
        return True
    except OSError:
        return False


def _cleanup_job_outputs(job: dict) -> int:
    """Remove partial output at the canonical path reserved by this job."""
    spec = job.get("cleanup") or {}
    try:
        base = os.path.realpath(spec.get("base", ""))
        if spec.get("kind") == "tree":
            path = _output_path(base, spec.get("path", ""))
            if not os.path.lexists(path):
                return 0
            _remove_output_path(path)
            return 1
        if spec.get("kind") == "effect":
            directory = _output_path(base, spec.get("directory", ""))
            removed = 0
            for filename in _effect_output_names(directory, spec["export_name"]):
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
    reservation = _RESERVED_OUTPUTS.get(key) if key else None
    if reservation:
        reservation["jobs"].discard(job.get("id"))
        if not reservation["jobs"]:
            _RESERVED_OUTPUTS.pop(key, None)
            handle = reservation.get("handle")
            if handle is not None:
                try:
                    handle.close()
                except OSError:
                    pass


def _job_worker():
    while True:
        item = None
        with _LOCK:
            if not _QUEUE_PAUSED[0]:
                try:
                    item = _QUEUE.get_nowait()
                except queue.Empty:
                    pass
            if item:
                jid, fn = item
                job = _JOBS.get(jid)
                if job and job["status"] == "queued":
                    job["status"] = "running"
                    job["started_at"] = time.time()
                    job["log"].append("started")
                else:
                    job = None
            else:
                job = None
        if item is None:
            _QUEUE_WAKE.wait(0.5)
            _QUEUE_WAKE.clear()
            continue
        if not job:
            _QUEUE.task_done()
            continue
        control = JobControl(jid, job)
        try:
            control.check_cancelled()
            _begin_output_update(job)
            result = fn(control)
            control.check_cancelled()
            with _LOCK:
                if job["cancel_event"].is_set():
                    raise CancelledError("job cancelled")
                job["result"] = result
                job["status"] = "done"
            if not _discard_output_backup(job):
                with _LOCK:
                    job["log"].append("previous export backup could not be removed")
        except BaseException as e:   # incl. SystemExit, so failures never hang the job
            removed, restored = _restore_output_update(job)
            if job["cancel_event"].is_set() or isinstance(e, CancelledError):
                with _LOCK:
                    job["result"] = None
                    job["status"] = "cancelled"
                    if not restored:
                        job["log"].append("cancelled · output rollback needs attention")
                    else:
                        job["log"].append(
                            f"cancelled · cleaned {removed} output item(s)" if removed
                            else "cancelled · partial outputs cleaned")
            else:
                with _LOCK:
                    job["error"] = str(e) or e.__class__.__name__
                    job["status"] = "error"
                    if not restored:
                        job["log"].append("failed · output rollback needs attention")
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
               "process": None,
               "created_at": time.time(), "started_at": None,
               "finished_at": None, "cleanup": None, "reservation_key": None,
               "job_type": endpoint or "job", "asset": "", "output_name": ""}
        if endpoint and body is not None:
            job["asset"] = str(body.get("name") or "asset")
            job["fx"] = bool(body.get("fx"))
            job["requested_output_name"] = config.safe_output_name(
                body.get("output_name"), job["asset"])
            output_name, reservation_key, cleanup = \
                _reserve_output_locked(jid, endpoint, body)
            job["output_name"] = output_name
            job["reservation_key"] = reservation_key
            job["cleanup"] = cleanup
        _JOBS[jid] = job
        _QUEUE.put((jid, fn))
        _QUEUE_WAKE.set()
        _ensure_worker_locked()
    return jid


def api_queue_control(action: str):
    if action not in {"pause", "resume"}:
        return {"ok": False, "error": "action must be pause or resume"}
    with _LOCK:
        _QUEUE_PAUSED[0] = action == "pause"
        _QUEUE_WAKE.set()
        running = sum(job["status"] in {"running", "cancelling"}
                      for job in _JOBS.values())
        queued = sum(job["status"] == "queued" for job in _JOBS.values())
        return {"ok": True, "paused": _QUEUE_PAUSED[0],
                "running": running, "queued": queued}


def api_job(q):
    jid = q.get("id", [""])[0]
    with _LOCK:
        job = _JOBS.get(jid)
        if not job:
            return {"status": "unknown"}
        result = {key: value for key, value in job.items()
                  if key not in {"cancel_event", "process", "cleanup", "reservation_key",
                                 "_output_backup", "_output_started"}}
        result["log"] = job["log"][-8:]
        result["cancelable"] = job["status"] in {"queued", "running"}
    result["queue_position"] = _queue_position(jid)
    return result


def api_jobs(_q=None):
    with _LOCK:
        paused = _QUEUE_PAUSED[0]
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
    return {"jobs": active + queued + history, "paused": paused,
            "counts": {"running": len(active), "queued": len(queued),
                       "finished": len(history)}}


def api_clear_history():
    """Remove finished job records while preserving active work and outputs."""
    finished_statuses = {"done", "error", "cancelled"}
    with _LOCK:
        finished_ids = [jid for jid, job in _JOBS.items()
                        if job["status"] in finished_statuses]
        for jid in finished_ids:
            del _JOBS[jid]
    return {"ok": True, "cleared": len(finished_ids)}


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
        if u.path == "/api/queue/control":
            result = api_queue_control(str(body.get("action") or ""))
            return self._send(200 if result["ok"] else 400, result)
        if u.path == "/api/job/cancel":
            result = api_cancel_job(str(body.get("id") or ""))
            return self._send(200 if result["ok"] else 404, result)
        if u.path == "/api/jobs/clear":
            return self._send(200, api_clear_history())
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


class QueueHandler(Handler):
    """Queue-only HTTP surface for the standalone CLI worker process."""

    def do_GET(self):
        path = urlparse(self.path).path
        if path not in {"/api/job", "/api/jobs"} and not path.startswith("/out/"):
            return self._send(404, {"error": "not found"})
        return super().do_GET()

    def do_POST(self):
        if urlparse(self.path).path not in {
                "/api/queue/control", "/api/job/cancel", "/api/jobs/clear",
                "/api/convert",
                "/api/render", "/api/fx"}:
            return self._send(404, {"error": "not found"})
        return super().do_POST()


def serve_queue(host="127.0.0.1", port=8766):
    """Run a headless queue instance for CLI jobs, separate from the web UI."""
    httpd = ThreadingHTTPServer((host, port), QueueHandler)
    url = f"http://{host}:{port}"
    print(f"DarkOrbit 3D CLI queue -> {url}  (Ctrl+C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nCLI queue stopped")
    finally:
        httpd.server_close()


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
