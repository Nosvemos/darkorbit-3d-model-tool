"""Render an Away3D '.awp' particle effect to a sprite-frame sequence.

Usage:
    python -m src.fx_render explosion0
    python -m src.fx_render explosion0 --frames 24 --resolution 256
    python -m src.fx_render --all
"""
from __future__ import annotations

import argparse
import glob
import os
import sys
import zipfile

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import config
from src.fx import awp as awp_mod
from src.fx import render as fx_render


def ensure_awp(name: str) -> str:
    """Return the path to fx/awp/<name>.awp, extracting fx/<name>.zip if needed."""
    awp_dir = os.path.join(config.FX_DIR, "awp")
    path = os.path.join(awp_dir, f"{name}.awp")
    if os.path.exists(path):
        return path
    zp = os.path.join(config.FX_DIR, f"{name}.zip")
    if os.path.exists(zp):
        os.makedirs(awp_dir, exist_ok=True)
        with zipfile.ZipFile(zp) as zf:
            for m in zf.namelist():
                if m.lower().endswith(".awp"):
                    with open(os.path.join(awp_dir, os.path.basename(m)), "wb") as f:
                        f.write(zf.read(m))
        if os.path.exists(path):
            return path
    raise SystemExit(f"awp not found for '{name}' (looked in fx/awp/ and fx/{name}.zip)")


def extract_all() -> tuple[int, int]:
    """Unpack every fx/*.zip into fx/awp/. Returns (extracted, archives)."""
    awp_dir = os.path.join(config.FX_DIR, "awp")
    os.makedirs(awp_dir, exist_ok=True)
    zips = sorted(glob.glob(os.path.join(config.FX_DIR, "*.zip")))
    n = 0
    for zp in zips:
        try:
            with zipfile.ZipFile(zp) as zf:
                for m in zf.namelist():
                    if m.lower().endswith(".awp"):
                        with open(os.path.join(awp_dir, os.path.basename(m)), "wb") as f:
                            f.write(zf.read(m))
                        n += 1
        except zipfile.BadZipFile:
            pass
    return n, len(zips)


def render(name: str, frames: int, resolution: int, margin: float) -> str:
    effect = awp_mod.load(ensure_awp(name))
    out_dir = os.path.join(config.OUT_DIR, "fx", name, "sprites")
    paths = fx_render.render_effect(effect, out_dir, config.FX_DIR,
                                    config.TEXTURES_DIR, frames=frames,
                                    resolution=resolution, margin=margin)
    print(f"  {name}: {len(effect.layers)} layers, {len(paths)} frames -> {out_dir}")
    return out_dir


def main():
    ap = argparse.ArgumentParser(description="Render .awp particle effect to sprites")
    ap.add_argument("name", nargs="?", help="effect name (without .zip/.awp)")
    ap.add_argument("--all", action="store_true", help="render every fx/*.zip")
    ap.add_argument("--frames", type=int, default=30)
    ap.add_argument("--resolution", type=int, default=256)
    ap.add_argument("--margin", type=float, default=1.2, help="canvas padding factor")
    args = ap.parse_args()

    if args.all:
        names = [os.path.splitext(os.path.basename(p))[0]
                 for p in sorted(glob.glob(os.path.join(config.FX_DIR, "*.zip")))]
    elif args.name:
        names = [args.name]
    else:
        ap.error("give an effect name or --all")

    for name in names:
        print(f"=== fx {name} ===")
        try:
            render(name, args.frames, args.resolution, args.margin)
        except SystemExit as e:
            print(f"  skip: {e}")


if __name__ == "__main__":
    main()
