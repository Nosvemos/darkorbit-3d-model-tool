"""Render an Away3D '.awp' particle effect to a sprite-frame sequence.

Usage:
    python -m src.fx_render explosion0
    python -m src.fx_render explosion0 --frames 24 --resolution 256
    python -m src.fx_render explosion0 --queue
    python -m src.fx_render --all

Outputs are isolated under out/fx/effects/<name>/sprites/.
"""
from __future__ import annotations

import argparse
import glob
import math
import os
import sys
import zipfile

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import config
from src.fx import awp as awp_mod
from src.fx import render as fx_render


def _archive_name(name: str) -> str:
    if not name or name in {".", ".."} or os.path.basename(name) != name:
        raise ValueError("effect name must be a file basename")
    return name


def _awp_member(zf: zipfile.ZipFile, name: str) -> str | None:
    members = [m for m in zf.namelist() if m.lower().endswith(".awp")]
    if not members:
        return None
    requested = f"{name}.awp".casefold()
    exact = [m for m in members
             if m.replace("\\", "/").rsplit("/", 1)[-1].casefold() == requested]
    if exact:
        return exact[0]
    if len(members) == 1:
        return members[0]
    raise ValueError(f"{name}.zip contains multiple .awp files and none is named {name}.awp")


def _write_awp(zf: zipfile.ZipFile, member: str, name: str) -> str:
    """Cache an archive's AWP under its archive identity, not a shared inner name."""
    inner_name = member.replace("\\", "/").rsplit("/", 1)[-1]
    dest_dir = os.path.join(config.FX_DIR, "awp", "by_archive", name)
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, inner_name)
    temp = dest + ".tmp"
    try:
        with open(temp, "wb") as f:
            f.write(zf.read(member))
        os.replace(temp, dest)
    finally:
        if os.path.exists(temp):
            os.remove(temp)
    return dest


def ensure_awp(name: str) -> str:
    """Extract the requested archive into a cache isolated by ZIP basename.

    Existing flattened ``fx/awp/<inner-name>.awp`` files are deliberately not
    trusted: different ZIPs in the supplied assets reuse inner AWP basenames.
    """
    name = _archive_name(name)
    zp = os.path.join(config.FX_DIR, f"{name}.zip")
    if os.path.exists(zp):
        try:
            with zipfile.ZipFile(zp) as zf:
                member = _awp_member(zf, name)
                if member:
                    return _write_awp(zf, member, name)
                raise ValueError(f"{name}.zip contains no .awp file")
        except zipfile.BadZipFile as e:
            raise ValueError(f"invalid effect archive: {name}.zip") from e

    # Preserve support for users who provide a standalone AWP without a ZIP.
    standalone = os.path.join(config.FX_DIR, "awp", f"{name}.awp")
    if os.path.exists(standalone):
        return standalone
    archive_cache = os.path.join(config.FX_DIR, "awp", "by_archive", name)
    cached = sorted(glob.glob(os.path.join(archive_cache, "*.awp")))
    if len(cached) == 1:
        return cached[0]
    raise ValueError(f"awp not found for '{name}' (looked in fx/{name}.zip and fx/awp/)")


def extract_all() -> tuple[int, int]:
    """Unpack every fx/*.zip into an archive-isolated cache."""
    zips = sorted(glob.glob(os.path.join(config.FX_DIR, "*.zip")))
    n = 0
    for zp in zips:
        name = os.path.splitext(os.path.basename(zp))[0]
        try:
            with zipfile.ZipFile(zp) as zf:
                member = _awp_member(zf, name)
                if member:
                    _write_awp(zf, member, name)
                    n += 1
        except (zipfile.BadZipFile, ValueError):
            pass
    return n, len(zips)


def validate_options(frames: int, resolution: int, margin: float) -> None:
    if not 1 <= frames <= 600:
        raise ValueError("frames must be between 1 and 600")
    if not 16 <= resolution <= 2048:
        raise ValueError("resolution must be between 16 and 2048 pixels")
    if not math.isfinite(margin) or not 0.05 <= margin <= 10.0:
        raise ValueError("margin must be between 0.05 and 10")


def frames_archive_path(sprites_dir: str, export_name: str) -> str:
    return os.path.join(sprites_dir, f"{export_name}_frames.zip")


def _write_frames_archive(paths: list[str], sprites_dir: str,
                          export_name: str) -> str:
    archive = frames_archive_path(sprites_dir, export_name)
    temp = archive + ".tmp"
    try:
        with zipfile.ZipFile(temp, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for path in paths:
                zf.write(path, arcname=os.path.basename(path))
        os.replace(temp, archive)
    finally:
        if os.path.exists(temp):
            os.remove(temp)
    return archive


def render(name: str, frames: int, resolution: int, margin: float,
           output_name: str | None = None,
           warnings: list[str] | None = None, cancel_check=None) -> str:
    name = _archive_name(name)
    validate_options(frames, resolution, margin)
    if cancel_check:
        cancel_check()
    effect = awp_mod.load(ensure_awp(name))
    export_name = config.safe_output_name(output_name, name)
    effect.name = export_name   # name frames after the requested export, not the .awp
    out_dir = config.effect_sprites_dir(name)
    paths = fx_render.render_effect(effect, out_dir, config.FX_DIR,
                                    config.TEXTURES_DIR, frames=frames,
                                    resolution=resolution, margin=margin,
                                    warnings=warnings,
                                    cancel_check=cancel_check)
    if cancel_check:
        cancel_check()
    archive = _write_frames_archive(paths, out_dir, export_name)
    label = name if export_name == name else f"{name} as {export_name}"
    print(f"  {label}: {len(effect.layers)} layers, {len(paths)} frames -> {out_dir}")
    print(f"  frame archive -> {archive}")
    return out_dir


def main():
    from src.cli import main as cli_main
    cli_main(["fx", *sys.argv[1:]])


if __name__ == "__main__":
    main()
