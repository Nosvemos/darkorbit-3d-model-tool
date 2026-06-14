"""Turntable sprite render orchestrator.

Builds the render config (defaults + CLI overrides), invokes Blender headless
to render frames + raw point coordinates, then does the stable crop and
coordinate adjustment in system Python (Pillow).

Usage:
    python -m src.render sibelon
    python -m src.render sibelon --frames 36 --resolution 512 --persp
    python -m src.render sibelon --hdri city.exr --elevation 60 --azimuth 30
    python -m src.render --all
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import sys

from PIL import Image

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import config
from src.pipeline import convert, run_cmd


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def stable_crop(out_dir: str, raw: dict, padding: int, origin: str) -> dict:
    """Crop every frame to one global alpha+point bbox; return adjusted coords."""
    res = raw["resolution"]
    paths = [os.path.join(out_dir, fn) for fn in raw["frames"]]
    points = raw["points"]

    gx1 = gy1 = res
    gx2 = gy2 = 0
    for i, path in enumerate(paths):
        alpha = Image.open(path).convert("RGBA").split()[-1]
        bbox = alpha.point(lambda p: 255 if p > 10 else 0).getbbox()
        if not bbox:
            continue
        x1, y1, x2, y2 = bbox
        for vals in points.values():
            v = vals[i]
            if v:
                x1, y1 = min(x1, int(v[0])), min(y1, int(v[1]))
                x2, y2 = max(x2, int(v[0])), max(y2, int(v[1]))
        gx1, gy1 = min(gx1, x1 - padding), min(gy1, y1 - padding)
        gx2, gy2 = max(gx2, x2 + padding), max(gy2, y2 + padding)

    gx1, gy1 = _clamp(gx1, 0, res), _clamp(gy1, 0, res)
    gx2, gy2 = _clamp(gx2, 0, res), _clamp(gy2, 0, res)
    # nothing visible in any frame (e.g. empty render) -> keep the full frame
    if gx2 <= gx1 or gy2 <= gy1:
        gx1, gy1, gx2, gy2 = 0, 0, res, res
    crop_h = gy2 - gy1
    for path in paths:
        Image.open(path).convert("RGBA").crop((gx1, gy1, gx2, gy2)).save(path)

    adjusted: dict[str, list] = {}
    for name, vals in points.items():
        out = []
        for v in vals:
            if not v:
                out.append("OFF")
                continue
            x, y = v[0] - gx1, v[1] - gy1
            if origin == "BOTTOM_LEFT":
                y = (crop_h - 1) - y
            out.append([int(round(x)), int(round(y))])
        adjusted[name] = out
    return adjusted, {"crop": [gx1, gy1, gx2, gy2], "size": [gx2 - gx1, gy2 - gy1]}


def render(mesh_name: str, overrides: dict, fx: bool = False,
           textures: dict | None = None, clip: str | None = None,
           progress=None) -> str:
    base = config.FX_OUT if fx else config.OUT_DIR
    glb = os.path.join(config.model_dir(mesh_name, base), f"{mesh_name}.glb")
    # rebuild the glb if it's missing or the user picked textures / a clip manually
    if textures or clip or not os.path.exists(glb):
        if progress:
            progress("building glb…")
        convert(mesh_name, fx=fx, textures=textures, clip=clip, progress=progress)

    work = config.work_dir(mesh_name, base)
    sprites = config.sprites_dir(mesh_name, base)
    os.makedirs(work, exist_ok=True)
    os.makedirs(sprites, exist_ok=True)
    # clear previous frames so the sprite set always matches this run's frame count
    for old in glob.glob(os.path.join(sprites, f"{mesh_name}_*.png")):
        os.remove(old)

    cfg = dict(config.RENDER_DEFAULTS)
    cfg.update(overrides)
    cfg_path = os.path.join(work, f"{mesh_name}_render_cfg.json")
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f)

    if progress:
        progress("rendering frames…")
    run_cmd([config.BLENDER_EXE, "--background", "--python",
             config.RENDER_SCRIPT, "--", glb, sprites, cfg_path], progress)

    raw_path = os.path.join(sprites, f"{mesh_name}_render_raw.json")
    with open(raw_path, encoding="utf-8") as f:
        raw = json.load(f)
    os.remove(raw_path)  # keep sprites/ tidy

    if cfg["stable_crop"]:
        coords, meta = stable_crop(sprites, raw, cfg["crop_padding"],
                                   cfg["coord_origin"])
    else:
        coords = {k: [[int(round(v[0])), int(round(v[1]))] if v else "OFF"
                      for v in vals] for k, vals in raw["points"].items()}
        meta = {"size": [raw["resolution"]] * 2}
    # Coords.json only when there are tracked points (ship mode); item / point-less
    # renders skip it. Flat {point_name: [[x, y] | "OFF", ...]} matches the app format.
    coords_path = os.path.join(sprites, f"{mesh_name}_Coords.json")
    if coords:
        with open(coords_path, "w", encoding="utf-8") as f:
            json.dump(coords, f, indent=4)
    elif os.path.exists(coords_path):
        os.remove(coords_path)  # stale coords from a previous ship-mode run
    with open(os.path.join(work, f"{mesh_name}_meta.json"), "w",
              encoding="utf-8") as f:
        json.dump(meta, f, indent=4)
    return sprites


# CLI flag name -> RENDER_DEFAULTS key (only flags the user set are applied)
_FLAG_TO_KEY = {
    "mode": "mode",
    "frames": "frames", "total_degrees": "total_degrees",
    "deg_per_frame": "deg_per_frame", "start_angle": "start_angle",
    "frame_start": "frame_start", "resolution": "resolution",
    "samples": "samples", "engine": "engine", "view_transform": "view_transform",
    "origin": "coord_origin", "hdri": "world_hdri",
    "world_strength": "world_strength", "sun_energy": "sun_energy",
    "emission": "emission_strength", "elevation": "cam_elevation",
    "azimuth": "cam_azimuth", "margin": "cam_margin",
}


def add_render_args(ap):
    """Attach the render flags to a parser (shared by `render` and the CLI)."""
    ap.add_argument("--mode", choices=["auto", "ship", "item"],
                    help="ship: track points + Coords.json; item: plain render, "
                         "no points; auto: ship if points exist (default)")
    g = ap.add_argument_group("turntable")
    g.add_argument("--frames", type=int, help="frame count (e.g. 32, 72)")
    g.add_argument("--total-degrees", type=float, dest="total_degrees",
                   help="total sweep, default 360")
    g.add_argument("--deg-per-frame", type=float, dest="deg_per_frame",
                   help="explicit per-frame step (overrides total/frames)")
    g.add_argument("--start-angle", type=float, dest="start_angle")
    g.add_argument("--frame-start", type=int, dest="frame_start",
                   help="first frame number in filenames (default 1)")

    g = ap.add_argument_group("output / quality")
    g.add_argument("--resolution", type=int)
    g.add_argument("--samples", type=int)
    g.add_argument("--engine")
    g.add_argument("--view-transform", dest="view_transform",
                   help="Standard / AgX / Filmic")
    g.add_argument("--no-crop", action="store_true", help="disable stable crop")
    g.add_argument("--no-transparent", action="store_true",
                   help="render on opaque background")
    g.add_argument("--origin", choices=["TOP_LEFT", "BOTTOM_LEFT"])

    g = ap.add_argument_group("camera / lighting")
    g.add_argument("--hdri", help="bundled world HDRI, e.g. studio.exr / city.exr")
    g.add_argument("--world-strength", type=float, dest="world_strength")
    g.add_argument("--sun-energy", type=float, dest="sun_energy")
    g.add_argument("--emission", type=float, help="glow emission strength")
    g.add_argument("--elevation", type=float)
    g.add_argument("--azimuth", type=float)
    g.add_argument("--persp", action="store_true", help="perspective (default ortho)")
    g.add_argument("--margin", type=float, help="frame padding factor (>1 zooms out)")


def overrides_from_args(args) -> dict:
    """Build a RENDER_DEFAULTS override dict from parsed args."""
    ov: dict = {}
    for flag, key in _FLAG_TO_KEY.items():
        val = getattr(args, flag, None)
        if val is not None:
            ov[key] = val
    if getattr(args, "persp", False):
        ov["cam_ortho"] = False
    if getattr(args, "no_crop", False):
        ov["stable_crop"] = False
    if getattr(args, "no_transparent", False):
        ov["film_transparent"] = False
    return ov


def main():
    ap = argparse.ArgumentParser(description="Turntable sprite renderer")
    ap.add_argument("mesh", nargs="?")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--fx", action="store_true",
                    help="render fx_*.awd meshes from fx/ (output under out/fx/)")
    add_render_args(ap)
    args = ap.parse_args()

    ov = overrides_from_args(args)
    src_dir = config.FX_DIR if args.fx else config.MESHES_DIR
    if args.all:
        names = [os.path.splitext(os.path.basename(p))[0]
                 for p in sorted(glob.glob(os.path.join(src_dir, "*.awd")))]
    elif args.mesh:
        names = [args.mesh]
    else:
        ap.error("give a mesh name or --all")

    for name in names:
        print(f"=== render {name} ===")
        print(f"  -> {render(name, ov, fx=args.fx)}")


if __name__ == "__main__":
    main()
