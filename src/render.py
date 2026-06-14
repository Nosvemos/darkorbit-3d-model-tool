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
from src.pipeline import convert


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
    crop_h = gy2 - gy1
    for path in paths:
        Image.open(path).convert("RGBA").crop((gx1, gy1, gx2, gy2)).save(path)

    adjusted: dict[str, list] = {}
    for name, vals in points.items():
        out = []
        for v in vals:
            if not v:
                out.append(None)
                continue
            x, y = v[0] - gx1, v[1] - gy1
            if origin == "BOTTOM_LEFT":
                y = (crop_h - 1) - y
            out.append([int(round(x)), int(round(y))])
        adjusted[name] = out
    return {"crop": [gx1, gy1, gx2, gy2],
            "size": [gx2 - gx1, gy2 - gy1], "points": adjusted}


def render(mesh_name: str, overrides: dict) -> str:
    out_dir = os.path.join(config.OUT_DIR, mesh_name)
    glb = os.path.join(out_dir, f"{mesh_name}.glb")
    if not os.path.exists(glb):
        convert(mesh_name)  # build the glb first

    cfg = dict(config.RENDER_DEFAULTS)
    cfg.update(overrides)
    cfg_path = os.path.join(out_dir, f"{mesh_name}_render_cfg.json")
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f)

    frames_dir = os.path.join(out_dir, "frames")
    subprocess.run([config.BLENDER_EXE, "--background", "--python",
                    config.RENDER_SCRIPT, "--", glb, frames_dir, cfg_path],
                   check=True)

    with open(os.path.join(frames_dir, f"{mesh_name}_render_raw.json"),
              encoding="utf-8") as f:
        raw = json.load(f)

    coords_path = os.path.join(out_dir, f"{mesh_name}_Coords.json")
    if cfg["stable_crop"]:
        result = stable_crop(frames_dir, raw, cfg["crop_padding"], cfg["coord_origin"])
    else:
        result = {"size": [raw["resolution"]] * 2, "points": raw["points"]}
    with open(coords_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    return frames_dir


def main():
    ap = argparse.ArgumentParser(description="Turntable sprite renderer")
    ap.add_argument("mesh", nargs="?")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--frames", type=int)
    ap.add_argument("--resolution", type=int)
    ap.add_argument("--samples", type=int)
    ap.add_argument("--hdri", help="bundled world HDRI, e.g. studio.exr / city.exr")
    ap.add_argument("--elevation", type=float)
    ap.add_argument("--azimuth", type=float)
    ap.add_argument("--persp", action="store_true", help="perspective (default ortho)")
    ap.add_argument("--margin", type=float, help="frame padding factor (>1 zooms out)")
    ap.add_argument("--origin", choices=["TOP_LEFT", "BOTTOM_LEFT"])
    args = ap.parse_args()

    ov: dict = {}
    if args.frames is not None: ov["frames"] = args.frames
    if args.resolution is not None: ov["resolution"] = args.resolution
    if args.samples is not None: ov["samples"] = args.samples
    if args.hdri: ov["world_hdri"] = args.hdri
    if args.elevation is not None: ov["cam_elevation"] = args.elevation
    if args.azimuth is not None: ov["cam_azimuth"] = args.azimuth
    if args.persp: ov["cam_ortho"] = False
    if args.margin is not None: ov["cam_margin"] = args.margin
    if args.origin: ov["coord_origin"] = args.origin

    if args.all:
        names = [os.path.splitext(os.path.basename(p))[0]
                 for p in sorted(glob.glob(os.path.join(config.MESHES_DIR, "*.awd")))]
    elif args.mesh:
        names = [args.mesh]
    else:
        ap.error("give a mesh name or --all")

    for name in names:
        print(f"=== render {name} ===")
        print(f"  -> {render(name, ov)}")


if __name__ == "__main__":
    main()
