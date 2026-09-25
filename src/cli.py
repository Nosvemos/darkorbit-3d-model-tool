"""Unified command-line interface for the DarkOrbit 3D model tool.

    do3d convert <mesh> [--all] [--fx] [--gltf] [--obj] [--no-blender]
    do3d render  <mesh> [--all] [--fx] [--mode ...] [render options]
    do3d fx      <name>  [--all] [--frames N] [--resolution PX] [--margin F]
    do3d extract-awp
    do3d list    [meshes|fx|effects|textures|all]
    do3d info    <mesh> [--fx]

Also available as `python -m src <command>`.
"""
from __future__ import annotations

import argparse
import glob
import os
import sys
import time
from urllib.parse import urljoin

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import config, fx_render, pipeline
from src import render as render_mod
from src.awd import parse_file
from src.queue_client import DEFAULT_SERVER_URL, QueueClient, QueueClientError


def _stems(directory: str, pattern: str) -> list[str]:
    return [os.path.splitext(os.path.basename(p))[0]
            for p in sorted(glob.glob(os.path.join(directory, pattern)))]


def _resolve_meshes(args) -> list[str]:
    src = config.FX_DIR if getattr(args, "fx", False) else config.MESHES_DIR
    if args.all:
        return _stems(src, "*.awd")
    if args.mesh:
        return [args.mesh]
    raise SystemExit("error: give a mesh name or --all")


def _reject_bulk_custom_name(args) -> None:
    if getattr(args, "all", False) and getattr(args, "output_name", None):
        raise SystemExit("error: --output-name is only valid for a single asset")


def _texture_overrides(args) -> dict[str, str] | None:
    textures = {}
    for value in getattr(args, "textures", None) or ():
        channel, separator, name = value.partition("=")
        channel = channel.strip().lower()
        name = name.strip()
        if not separator or channel not in config.CHANNELS or not name:
            raise SystemExit(
                "error: --texture must be CHANNEL=NAME, where CHANNEL is "
                + ", ".join(config.CHANNELS)
            )
        textures[channel] = name
    return textures or None


def _server_url(args) -> str:
    return getattr(args, "queue_server", DEFAULT_SERVER_URL)


def _server_link(server: str, path: str | None) -> str | None:
    return urljoin(server.rstrip("/") + "/", path.lstrip("/")) if path else None


def _job_kind(job: dict) -> str:
    if job.get("job_type") == "/api/fx":
        return "particle effect"
    if job.get("job_type") == "/api/convert":
        return "FX conversion" if job.get("fx") else "conversion"
    if job.get("job_type") == "/api/render":
        return "FX mesh render" if job.get("fx") else "sprite render"
    return "job"


def _print_job_result(server: str, result: dict | None) -> None:
    if not result:
        return
    frames = result.get("frames") or []
    for key, label in (("glb", "GLB"), ("scene", "Scene JSON"), ("coords", "Coords"),
                       ("archive", "Frames ZIP")):
        link = _server_link(server, result.get(key))
        if link:
            print(f"  {label}: {link}")
    first_frame = result.get("first_frame") or (frames[0] if frames else None)
    if first_frame:
        print(f"  First frame: {_server_link(server, first_frame)}")
    frame_count = result.get("frame_count") or len(frames)
    if frame_count:
        print(f"  Frames: {frame_count}")
    if result.get("warnings"):
        print("  Warnings: " + ", ".join(result["warnings"]))


def _watch_job(client: QueueClient, job_id: str, interval: float = 0.7) -> int:
    seen_logs = []
    last_status = None
    last_position = None
    try:
        while True:
            job = client.job(job_id)
            status = job.get("status", "unknown")
            if status == "unknown":
                raise QueueClientError(f"job {job_id} was not found")
            position = job.get("queue_position") if status == "queued" else None
            if status != last_status or position != last_position:
                label = f"queue position {position}" if status == "queued" else status
                print(f"[{job_id}] {job.get('asset') or 'Job'} · {label}")
                last_status = status
                last_position = position
            logs = job.get("log") or []
            if logs[:len(seen_logs)] == seen_logs:
                new_logs = logs[len(seen_logs):]
            else:
                new_logs = [line for line in logs if line not in seen_logs]
            for line in new_logs:
                if line not in {"queued", "started"}:
                    print(f"  {line}")
            seen_logs = logs[:]

            if status == "done":
                _print_job_result(client.server, job.get("result"))
                return 0
            if status in {"error", "cancelled"}:
                if job.get("error"):
                    print(f"  Error: {job['error']}", file=sys.stderr)
                return 1
            time.sleep(max(0.1, interval))
    except KeyboardInterrupt:
        print(f"\nStopped watching; job {job_id} continues. Cancel it with `do3d queue cancel {job_id}`.")
        return 130


def _submit_job(args, endpoint: str, body: dict, asset: str) -> str:
    client = QueueClient(_server_url(args))
    response = client.submit(endpoint, body)
    job_id = str(response["job"])
    output_name = response.get("output_name")
    suffix = f" · output {output_name}" if output_name else ""
    print(f"Queued {asset} as job {job_id}{suffix}")
    return job_id


def _finish_submissions(args, job_ids: list[str]) -> None:
    if args.follow:
        client = QueueClient(_server_url(args))
        for job_id in job_ids:
            result = _watch_job(client, job_id)
            if result:
                raise SystemExit(result)
    elif job_ids:
        print("Manage jobs with `do3d queue list`, `do3d queue watch ID`, "
              "and `do3d queue cancel ID`.")


def _validate_queue_flags(args) -> None:
    if args.follow and not args.queue:
        raise SystemExit("error: --follow requires --queue")


def _add_queue_submission_options(parser) -> None:
    parser.add_argument("--queue", action="store_true",
                        help="submit this operation to the standalone CLI queue")
    parser.add_argument("--queue-server", default=DEFAULT_SERVER_URL,
                        help=f"CLI queue URL (default: {DEFAULT_SERVER_URL}; "
                             "or set DO3D_QUEUE_URL)")
    parser.add_argument("--follow", action="store_true",
                        help="watch the submitted job until it finishes; requires --queue")


# --- subcommands ------------------------------------------------------------

def cmd_convert(args):
    _validate_queue_flags(args)
    _reject_bulk_custom_name(args)
    hide = [h.strip() for h in args.hide_objects.split(",") if h.strip()] if getattr(args, "hide_objects", None) else None
    textures = _texture_overrides(args)
    submitted = []
    for name in _resolve_meshes(args):
        print(f"=== convert {name} ===")
        if args.queue:
            body = {"name": name, "fx": args.fx, "gltf": args.gltf,
                    "obj": args.obj, "run": not args.no_blender,
                    "textures": textures, "clip": args.clip or None,
                    "overlay": args.overlay or None,
                    "output_name": args.output_name or None,
                    "hide_objects": hide}
            submitted.append(_submit_job(args, "/api/convert", body, name))
            continue
        out = pipeline.convert(name, gltf=args.gltf, obj=args.obj,
                               run=not args.no_blender, fx=args.fx,
                               textures=textures, clip=args.clip or None,
                               overlay=args.overlay or None,
                               output_name=args.output_name or None,
                               hide_objects=hide)
        print(f"  -> {out}")
    _finish_submissions(args, submitted)


def cmd_render(args):
    _validate_queue_flags(args)
    _reject_bulk_custom_name(args)
    ov = render_mod.overrides_from_args(args)
    textures = _texture_overrides(args)
    submitted = []
    for name in _resolve_meshes(args):
        print(f"=== render {name} ===")
        if args.queue:
            profile_keys = {key for profile in config.RENDER_PROFILES.values()
                            for key in profile}
            body = {**ov, "name": name, "fx": args.fx,
                    "textures": textures, "clip": args.clip or None,
                    "overlay": args.overlay or None,
                    "output_name": args.output_name or None,
                    "profile_overrides": {key: value for key, value in ov.items()
                                          if key in profile_keys}}
            submitted.append(_submit_job(args, "/api/render", body, name))
            continue
        out = render_mod.render(name, ov, fx=args.fx, clip=args.clip or None,
                                textures=textures,
                                overlay=args.overlay or None,
                                output_name=args.output_name or None)
        print(f"  -> {out}")
    _finish_submissions(args, submitted)


def cmd_fx(args):
    _validate_queue_flags(args)
    _reject_bulk_custom_name(args)
    try:
        fx_render.validate_options(args.frames, args.resolution, args.margin)
    except ValueError as e:
        raise SystemExit(f"error: {e}") from e
    names = _stems(config.FX_DIR, "*.zip") if args.all else [args.name] if args.name \
        else None
    if not names:
        raise SystemExit("error: give an effect name or --all")
    submitted = []
    for name in names:
        print(f"=== fx {name} ===")
        if args.queue:
            body = {"name": name, "frames": args.frames,
                    "resolution": args.resolution, "margin": args.margin,
                    "output_name": args.output_name or None}
            submitted.append(_submit_job(args, "/api/fx", body, name))
            continue
        warnings = []
        try:
            fx_render.render(name, args.frames, args.resolution, args.margin,
                             output_name=args.output_name or None,
                             warnings=warnings)
        except SystemExit as e:
            print(f"  skip: {e}")
            continue
        except ValueError as e:
            print(f"  skip: {e}")
            continue
        if warnings:
            print(f"  missing textures (white fallback): {', '.join(warnings)}")
    _finish_submissions(args, submitted)


def cmd_queue_list(args):
    client = QueueClient(args.queue_server)
    data = client.jobs()
    counts = data.get("counts") or {}
    running, queued = counts.get("running", 0), counts.get("queued", 0)
    state = "paused" if data.get("paused") else "running" if running or queued else "idle"
    print(f"Render queue · {state} · {running} running · {queued} waiting")
    jobs = data.get("jobs") or []
    if not jobs:
        print("  No active or recent jobs.")
        return
    for job in jobs:
        status = job.get("status", "unknown")
        position = f" · position {job['queue_position']}" \
            if status == "queued" and job.get("queue_position") else ""
        output_name = job.get("output_name")
        output = f" · output {output_name}" if output_name else ""
        print(f"  [{job.get('id')}] {job.get('asset') or 'Job'} · "
              f"{_job_kind(job)} · {status}{position}{output}")
        logs = job.get("log") or []
        if logs and logs[-1] not in {"queued", "started"}:
            print(f"      {logs[-1]}")
        if status == "done":
            _print_job_result(client.server, job.get("result"))


def cmd_queue_pause(args):
    data = QueueClient(args.queue_server).control("pause")
    running, queued = data.get("running", 0), data.get("queued", 0)
    if running:
        print(f"Queue will pause after the active job · {queued} waiting")
    else:
        print(f"Queue paused · {queued} waiting")


def cmd_queue_resume(args):
    data = QueueClient(args.queue_server).control("resume")
    print(f"Queue resumed · {data.get('queued', 0)} waiting")


def cmd_queue_cancel(args):
    data = QueueClient(args.queue_server).cancel(args.job_id)
    status = data.get("status", "cancelling")
    if status == "cancelled":
        print(f"Job {args.job_id} cancelled; partial output was cleaned.")
    elif status == "cancelling":
        print(f"Cancellation requested for job {args.job_id}; process stop and output cleanup are in progress.")
    else:
        print(f"Job {args.job_id}: {status}")


def cmd_queue_watch(args):
    return _watch_job(QueueClient(args.queue_server), args.job_id, args.interval)


def cmd_queue_serve(args):
    from src import server
    server.serve_queue(host=args.host, port=args.port)


def cmd_extract_awp(args):
    n, archives = fx_render.extract_all()
    print(f"extracted {n} .awp from {archives} archives -> "
          f"{os.path.join(config.FX_DIR, 'awp', 'by_archive')}")


def cmd_list(args):
    what = args.what
    groups = {
        "meshes": (config.MESHES_DIR, "*.awd"),
        "fx": (config.FX_DIR, "*.awd"),
        "effects": (config.FX_DIR, "*.zip"),
        "textures": (config.TEXTURES_DIR, "*.atf"),
    }
    targets = groups.keys() if what == "all" else [what]
    for key in targets:
        directory, pattern = groups[key]
        names = _stems(directory, pattern)
        print(f"{key} ({len(names)}):")
        for n in names:
            print(f"  {n}")


def cmd_ui(args):
    from src import server
    server.serve(host=args.host, port=args.port, open_browser=not args.no_browser)


def cmd_info(args):
    src = config.FX_DIR if args.fx else config.MESHES_DIR
    path = os.path.join(src, f"{args.mesh}.awd")
    if not os.path.exists(path):
        raise SystemExit(f"error: not found: {path}")
    scene = parse_file(path)
    print(f"{args.mesh}  ({len(scene.instances)} objects)")
    for inst in scene.instances:
        geo = scene.geometry_for(inst)
        v = geo.vertex_count if geo else 0
        t = geo.triangle_count if geo else 0
        tag = " [point]" if inst.is_point else ""
        print(f"  {inst.name:32s} {v:6d}v {t:6d}t{tag}")
    if scene.clips:
        print(f"  clips: {', '.join(c.name for c in scene.clips)}")
    tex_dir = config.FX_DIR if args.fx else config.TEXTURES_DIR
    found = [c for c in config.CHANNELS
             if pipeline._find_texture(tex_dir, args.mesh, c)]
    single = os.path.exists(os.path.join(tex_dir, f"{args.mesh}.atf"))
    print(f"  textures: {', '.join(found) if found else ('<single>' if single else 'none')}")


# --- parser -----------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="do3d", description="DarkOrbit AWD/ATF -> glb / sprites toolkit")
    sub = ap.add_subparsers(dest="command", required=True)

    c = sub.add_parser("convert", help="AWD (+ATF) -> glb/gltf/obj")
    c.add_argument("mesh", nargs="?")
    c.add_argument("--all", action="store_true")
    c.add_argument("--fx", action="store_true", help="source from fx/, out to out/fx/")
    c.add_argument("--gltf", action="store_true")
    c.add_argument("--obj", action="store_true")
    c.add_argument("--no-blender", action="store_true")
    c.add_argument("--overlay", help="mesh name to overlay on top")
    c.add_argument("--clip", help="select a single animation clip")
    c.add_argument("--texture", dest="textures", action="append", metavar="CHANNEL=NAME",
                   help="override an ATF texture channel; may be repeated")
    c.add_argument("--output-name", "--export-name", dest="output_name",
                   help="basename for exported files (default: mesh name)")
    c.add_argument("--hide", "--hide-objects", dest="hide_objects",
                   help="comma-separated list of object names to hide/exclude")
    _add_queue_submission_options(c)
    c.set_defaults(func=cmd_convert)

    r = sub.add_parser("render", help="turntable sprite render of a mesh")
    r.add_argument("mesh", nargs="?")
    r.add_argument("--all", action="store_true")
    r.add_argument("--fx", action="store_true", help="render fx_*.awd from fx/")
    r.add_argument("--overlay", help="mesh name to overlay on top")
    r.add_argument("--output-name", "--export-name", dest="output_name",
                   help="basename for exported glb/sprite files (default: mesh name)")
    r.add_argument("--texture", dest="textures", action="append", metavar="CHANNEL=NAME",
                   help="override an ATF texture channel; may be repeated")
    render_mod.add_render_args(r)
    _add_queue_submission_options(r)
    r.set_defaults(func=cmd_render)

    f = sub.add_parser("fx", help="render an .awp particle effect to sprites")
    f.add_argument("name", nargs="?")
    f.add_argument("--all", action="store_true")
    f.add_argument("--frames", type=int, default=30)
    f.add_argument("--resolution", type=int, default=256)
    f.add_argument("--margin", type=float, default=1.2)
    f.add_argument("--output-name", "--export-name", dest="output_name",
                   help="basename for exported sprite files (default: effect name)")
    _add_queue_submission_options(f)
    f.set_defaults(func=cmd_fx)

    q = sub.add_parser("queue", help="run or manage the standalone CLI render queue")
    q.add_argument("--queue-server", default=DEFAULT_SERVER_URL,
                   help=f"CLI queue URL (default: {DEFAULT_SERVER_URL}; "
                        "or set DO3D_QUEUE_URL)")
    queue_actions = q.add_subparsers(dest="queue_action", required=True)
    ql = queue_actions.add_parser("list", aliases=["status"],
                                  help="show active, waiting, and recent jobs")
    ql.add_argument("--queue-server", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    ql.set_defaults(func=cmd_queue_list)
    qp = queue_actions.add_parser("pause", help="finish the active job, then hold the queue")
    qp.add_argument("--queue-server", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    qp.set_defaults(func=cmd_queue_pause)
    qr = queue_actions.add_parser("resume", help="resume starting queued jobs")
    qr.add_argument("--queue-server", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    qr.set_defaults(func=cmd_queue_resume)
    qc = queue_actions.add_parser("cancel", help="cancel a queued or running job")
    qc.add_argument("job_id")
    qc.add_argument("--queue-server", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    qc.set_defaults(func=cmd_queue_cancel)
    qw = queue_actions.add_parser("watch", help="follow one job's status and progress")
    qw.add_argument("job_id")
    qw.add_argument("--queue-server", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    qw.add_argument("--interval", type=float, default=0.7,
                    help="polling interval in seconds (default: 0.7)")
    qw.set_defaults(func=cmd_queue_watch)
    qs = queue_actions.add_parser("serve", help="start the independent CLI queue service")
    qs.add_argument("--host", default="127.0.0.1")
    qs.add_argument("--port", type=int, default=8766)
    qs.set_defaults(func=cmd_queue_serve)

    e = sub.add_parser("extract-awp", help="unzip fx/*.zip -> fx/awp/")
    e.set_defaults(func=cmd_extract_awp)

    ls = sub.add_parser("list", help="list available assets")
    ls.add_argument("what", nargs="?", default="all",
                    choices=["meshes", "fx", "effects", "textures", "all"])
    ls.set_defaults(func=cmd_list)

    i = sub.add_parser("info", help="inspect a mesh (objects, points, textures)")
    i.add_argument("mesh")
    i.add_argument("--fx", action="store_true")
    i.set_defaults(func=cmd_info)

    u = sub.add_parser("ui", help="launch the local web UI")
    u.add_argument("--host", default="127.0.0.1")
    u.add_argument("--port", type=int, default=8765)
    u.add_argument("--no-browser", action="store_true")
    u.set_defaults(func=cmd_ui)
    return ap


def main(argv=None):
    ap = build_parser()
    args = ap.parse_args(argv)
    try:
        result = args.func(args)
        if isinstance(result, int) and result != 0:
            raise SystemExit(result)
    except QueueClientError as e:
        ap.exit(2, f"error: {e}\n")
    except SystemExit as e:
        if isinstance(e.code, str):
            ap.exit(2, e.code + "\n")
        raise


if __name__ == "__main__":
    main()
