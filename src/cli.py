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

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import config, fx_render, pipeline
from src import render as render_mod
from src.awd import parse_file


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


# --- subcommands ------------------------------------------------------------

def cmd_convert(args):
    for name in _resolve_meshes(args):
        print(f"=== convert {name} ===")
        out = pipeline.convert(name, gltf=args.gltf, obj=args.obj,
                               run=not args.no_blender, fx=args.fx)
        print(f"  -> {out}")


def cmd_render(args):
    ov = render_mod.overrides_from_args(args)
    for name in _resolve_meshes(args):
        print(f"=== render {name} ===")
        print(f"  -> {render_mod.render(name, ov, fx=args.fx)}")


def cmd_fx(args):
    names = _stems(config.FX_DIR, "*.zip") if args.all else [args.name] if args.name \
        else None
    if not names:
        raise SystemExit("error: give an effect name or --all")
    for name in names:
        print(f"=== fx {name} ===")
        try:
            fx_render.render(name, args.frames, args.resolution, args.margin)
        except SystemExit as e:
            print(f"  skip: {e}")


def cmd_extract_awp(args):
    n, archives = fx_render.extract_all()
    print(f"extracted {n} .awp from {archives} archives -> {os.path.join(config.FX_DIR, 'awp')}")


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
    c.set_defaults(func=cmd_convert)

    r = sub.add_parser("render", help="turntable sprite render of a mesh")
    r.add_argument("mesh", nargs="?")
    r.add_argument("--all", action="store_true")
    r.add_argument("--fx", action="store_true", help="render fx_*.awd from fx/")
    render_mod.add_render_args(r)
    r.set_defaults(func=cmd_render)

    f = sub.add_parser("fx", help="render an .awp particle effect to sprites")
    f.add_argument("name", nargs="?")
    f.add_argument("--all", action="store_true")
    f.add_argument("--frames", type=int, default=30)
    f.add_argument("--resolution", type=int, default=256)
    f.add_argument("--margin", type=float, default=1.2)
    f.set_defaults(func=cmd_fx)

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
        args.func(args)
    except SystemExit as e:
        if isinstance(e.code, str):
            ap.exit(2, e.code + "\n")
        raise


if __name__ == "__main__":
    main()
