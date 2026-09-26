"""Turntable sprite render orchestrator.

Builds the render config (defaults + CLI overrides), invokes Blender headless
to render frames + raw point coordinates, then does the stable crop and
coordinate adjustment in system Python (Pillow).

Usage:
    python -m src.render sibelon
    python -m src.render sibelon --frames 36 --resolution 512
    python -m src.render sibelon --camera-model orbit --light-model blender --hdri city.exr
    python -m src.render sibelon --queue --follow
    python -m src.render --all
"""
from __future__ import annotations

import argparse
from concurrent.futures import CancelledError
import glob
import json
import os
import subprocess
import sys

from PIL import Image

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import config
from src.pipeline import build_inputs, convert, resolve_design, run_cmd


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def stable_crop(out_dir: str, raw: dict, padding: int, origin: str,
                align_box: list[int] | None = None, cancel_check=None) -> dict:
    """Crop every frame to one global alpha+point bbox; return adjusted coords."""
    res = raw["resolution"]
    paths = [os.path.join(out_dir, fn) for fn in raw["frames"]]
    points = raw["points"]

    if align_box:
        gx1, gy1, gx2, gy2 = align_box
    else:
        gx1 = gy1 = res
        gx2 = gy2 = 0
        for i, path in enumerate(paths):
            if cancel_check:
                cancel_check()
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
        if cancel_check:
            cancel_check()
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
           overlay: str | None = None, output_name: str | None = None,
           progress=None, cancel_event=None, process_callback=None,
           cancel_check=None, design: str | None = None) -> str:
    def check_cancelled():
        if cancel_check:
            cancel_check()
        elif cancel_event is not None and cancel_event.is_set():
            raise CancelledError("job cancelled")

    check_cancelled()
    design = resolve_design(mesh_name, design)
    export_name = config.safe_output_name(output_name, mesh_name)
    base = config.FX_OUT if fx else config.OUT_DIR
    glb = os.path.join(config.model_dir(export_name, base), f"{export_name}.glb")
    build_stamp = os.path.join(config.work_dir(export_name, base),
                               f"{export_name}_build.json")
    try:
        with open(build_stamp, encoding="utf-8") as f:
            built = json.load(f)
    except (OSError, ValueError, TypeError):
        built = {}
    if not isinstance(built, dict):
        built = {}
    hide_objs = overrides.get("hide_objects")
    expected_build = build_inputs(
        mesh_name, fx=fx, textures=textures, clip=clip, overlay=overlay,
        hide_objects=hide_objs, output_name=export_name, design=design)
    build_matches = (built.get("version") == config.MODEL_BUILD_VERSION and
                     all(built.get(key) == value
                         for key, value in expected_build.items()))
    # Rebuild missing/stale GLBs as well as explicit per-run source overrides.
    # Compare provenance too: one export name can be reused for different
    # source meshes or build options, and must not keep the previous model.
    if (textures or clip or overlay or hide_objs or not os.path.exists(glb) or
            not build_matches):
        if progress:
            progress("building glb…")
        convert(mesh_name, fx=fx, textures=textures, clip=clip, overlay=overlay,
                output_name=export_name, hide_objects=hide_objs, design=design,
                save_blend=False,
                progress=progress,
                cancel_event=cancel_event, process_callback=process_callback)

    check_cancelled()
    work = config.work_dir(export_name, base)
    sprites = config.sprites_dir(export_name, base)
    os.makedirs(work, exist_ok=True)
    os.makedirs(sprites, exist_ok=True)
    # clear previous frames so the sprite set always matches this run's frame count
    for old in glob.glob(os.path.join(sprites, f"{export_name}_*.png")):
        os.remove(old)

    cfg = dict(config.RENDER_DEFAULTS)
    profile = overrides.get("profile") or cfg.get("profile")
    if profile in config.RENDER_PROFILES:
        cfg.update(config.RENDER_PROFILES[profile])
    quality = overrides.get("quality") or cfg.get("quality")
    if quality in config.QUALITY_PRESETS:
        cfg.update(config.QUALITY_PRESETS[quality])
    cfg.update(overrides)
    if design:
        preset = config.PET_DESIGNS[design]
        cfg["appearance"] = {key: preset[key] for key in (
            "rim_color", "rim_strength", "rim_power", "outline_size")}
    cfg["source_scene"] = os.path.join(work, f"{export_name}.scene.json")
    cfg["blend_path"] = os.path.join(config.model_dir(export_name, base), f"{export_name}.blend")
    if design and cfg.get("design_particles", True):
        from src.fx.scene import prepare
        cfg["particle_scene"] = prepare(config.PET_DESIGNS[design]["particles"], work,
                                        cfg, check_cancelled)
    cfg_path = os.path.join(work, f"{export_name}_render_cfg.json")
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f)

    if progress:
        progress("rendering frames…")
    run_cmd([config.BLENDER_EXE, "--background", "--python-exit-code", "1", "--python",
             config.RENDER_SCRIPT, "--", glb, sprites, cfg_path], progress,
            cancel_event=cancel_event, process_callback=process_callback)
    check_cancelled()

    raw_path = os.path.join(sprites, f"{export_name}_render_raw.json")
    if not os.path.isfile(raw_path):
        raise RuntimeError(
            "Blender finished without writing render metadata at "
            f"{raw_path}; check the preceding Blender output in the queue log")
    with open(raw_path, encoding="utf-8") as f:
        raw = json.load(f)
    os.remove(raw_path)  # keep sprites/ tidy

    align_box = None
    crop_align = cfg.get("crop_align")
    if crop_align:
        if os.path.exists(str(crop_align)):
            meta_path = str(crop_align)
            master_cfg_path = meta_path.replace("_meta.json", "_render_cfg.json")
        else:
            meta_path = os.path.join(config.OUT_DIR, str(crop_align), "work", f"{crop_align}_meta.json")
            master_cfg_path = os.path.join(config.OUT_DIR, str(crop_align), "work", f"{crop_align}_render_cfg.json")
        if os.path.exists(meta_path):
            try:
                with open(meta_path, encoding="utf-8") as f:
                    meta_data = json.load(f)
                if "crop" in meta_data:
                    align_box = meta_data["crop"]
                # Scale align_box if the resolutions of master and current renders differ
                if os.path.exists(master_cfg_path):
                    with open(master_cfg_path, encoding="utf-8") as f:
                        master_cfg = json.load(f)
                    master_res = master_cfg.get("resolution")
                    current_res = cfg.get("resolution") or config.RENDER_DEFAULTS["resolution"]
                    if master_res and current_res and master_res != current_res:
                        scale = current_res / master_res
                        align_box = [
                            int(round(align_box[0] * scale)),
                            int(round(align_box[1] * scale)),
                            int(round(align_box[2] * scale)),
                            int(round(align_box[3] * scale))
                        ]
            except Exception:
                pass

    if cfg["stable_crop"] or align_box:
        coords, meta = stable_crop(sprites, raw, cfg["crop_padding"],
                                   cfg["coord_origin"], align_box=align_box,
                                   cancel_check=check_cancelled)
    else:
        coords = {k: [[int(round(v[0])), int(round(v[1]))] if v else "OFF"
                      for v in vals] for k, vals in raw["points"].items()}
        meta = {"size": [raw["resolution"]] * 2}
    # Coords.json only when there are tracked points (ship mode); item / point-less
    # renders skip it. Flat {point_name: [[x, y] | "OFF", ...]} matches the app format.
    coords_path = os.path.join(sprites, f"{export_name}_Coords.json")
    if coords:
        with open(coords_path, "w", encoding="utf-8") as f:
            json.dump(coords, f, indent=4)
    elif os.path.exists(coords_path):
        os.remove(coords_path)  # stale coords from a previous ship-mode run
    with open(os.path.join(work, f"{export_name}_meta.json"), "w",
              encoding="utf-8") as f:
        json.dump(meta, f, indent=4)
    return sprites


# CLI flag name -> RENDER_DEFAULTS key (only flags the user set are applied)
_FLAG_TO_KEY = {
    "profile": "profile", "mode": "mode",
    "frames": "frames", "total_degrees": "total_degrees",
    "deg_per_frame": "deg_per_frame", "start_angle": "start_angle",
    "frame_start": "frame_start", "resolution": "resolution",
    "samples": "samples", "engine": "engine", "view_transform": "view_transform",
    "origin": "coord_origin", "hdri": "world_hdri",
    "world_strength": "world_strength", "sun_energy": "sun_energy",
    "ambient_strength": "ambient_strength",
    "specular_strength": "specular_strength",
    "emission": "emission_strength", "elevation": "cam_elevation",
    "azimuth": "cam_azimuth", "cam_tilt": "cam_tilt", "cam_pan": "cam_pan",
    "cam_fov": "cam_fov", "cam_distance": "cam_distance",
    "camera_model": "camera_model",
    "sun_tilt": "sun_tilt", "sun_pan": "sun_pan", "light_model": "light_model",
    "light_quality": "light_quality", "margin": "cam_margin",
    "anim_frame_start": "anim_frame_start", "anim_frame_end": "anim_frame_end",
    "sun_color": "sun_color", "world_color": "world_color",
    "ambient_color": "ambient_color",
    "quality": "quality",
    "hide_objects": "hide_objects",
    "crop_align": "crop_align",
    "effect_time": "effect_time", "effect_fps": "effect_fps",
    "cam_zoom": "cam_zoom", "camera_framing": "camera_framing",
}


def add_render_args(ap):
    """Attach the render flags to a parser (shared by `render` and the CLI)."""
    ap.add_argument("--profile", choices=sorted(config.RENDER_PROFILES),
                    help="visual profile (default: darkorbit)")
    ap.add_argument('--effect-time', type=float, help='PET effect start time in seconds (default 2)')
    ap.add_argument('--effect-fps', type=float, help='PET effect sampling rate (default 30)')
    ap.add_argument('--cam-zoom', type=float, help='Observer3D zoom, 1 through 3')
    ap.add_argument('--camera-framing', choices=['sprite', 'native'],
                    help='sprite: enlarge a crop at game distance; native: full game FOV')
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
    g.add_argument("--clip", help="play/export a single animation clip (default: all)")
    g.add_argument("--no-rotation", action="store_true", help="disable turntable Z rotation")
    g.add_argument("--anim-frame-start", type=int, dest="anim_frame_start",
                   help="start frame of the animation clip (default 1)")
    g.add_argument("--anim-frame-end", type=int, dest="anim_frame_end",
                   help="end frame of the animation clip")

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
    g.add_argument("--quality", choices=["extra_low", "low", "medium", "high", "extra_high", "custom"])
    g.add_argument("--hide", "--hide-objects", dest="hide_objects",
                   help="comma-separated list of object names to hide/exclude")
    g.add_argument("--crop-align", dest="crop_align",
                   help="align stable crop coordinates with a reference metadata name or file path")

    g = ap.add_argument_group("camera / lighting")
    g.add_argument("--hdri", help="bundled world HDRI, e.g. studio.exr / city.exr")
    g.add_argument("--use-hdri", action="store_true",
                   help="enable Blender world HDRI lighting")
    g.add_argument("--no-hdri", action="store_true",
                   help="disable Blender world HDRI lighting")
    g.add_argument("--world-strength", type=float, dest="world_strength")
    g.add_argument("--ambient-strength", type=float, dest="ambient_strength",
                   help="material ambient-fill strength (separate from world background)")
    g.add_argument("--sun-energy", type=float, dest="sun_energy")
    g.add_argument("--specular-strength", type=float, dest="specular_strength",
                   help="DarkOrbit LightSettings specular multiplier")
    g.add_argument("--emission", type=float, help="glow emission strength")
    g.add_argument("--camera-model", choices=["darkorbit", "orbit"],
                   dest="camera_model")
    g.add_argument("--elevation", type=float)
    g.add_argument("--azimuth", type=float)
    g.add_argument("--cam-tilt", type=float, dest="cam_tilt",
                   help="DarkOrbit Observer3D tilt")
    g.add_argument("--cam-pan", type=float, dest="cam_pan",
                   help="DarkOrbit Observer3D pan")
    g.add_argument("--fov", "--cam-fov", type=float, dest="cam_fov",
                   help="perspective camera field of view")
    g.add_argument("--cam-distance", type=float, dest="cam_distance",
                   help="fixed camera distance; omitted means fit object")
    g.add_argument("--persp", action="store_true", help="force perspective camera")
    g.add_argument("--ortho", action="store_true", help="force orthographic camera")
    g.add_argument("--margin", type=float, help="frame padding factor (>1 zooms out)")
    g.add_argument("--light-model", choices=["darkorbit", "blender"],
                   dest="light_model")
    g.add_argument("--sun-tilt", type=float, dest="sun_tilt",
                   help="DarkOrbit sun directionTilt")
    g.add_argument("--sun-pan", type=float, dest="sun_pan",
                   help="DarkOrbit sun directionPan")
    g.add_argument("--light-quality", choices=["low", "medium", "high"],
                   dest="light_quality")
    g.add_argument("--hero-light", action="store_true",
                   help="enable DarkOrbit hero-position point light")
    g.add_argument("--no-hero-light", action="store_true",
                   help="disable DarkOrbit hero-position point light")
    g.add_argument("--sun-color", dest="sun_color", help="sun light color (hex)")
    g.add_argument("--world-color", dest="world_color", help="world background light color (hex)")
    g.add_argument("--ambient-color", dest="ambient_color",
                   help="material ambient-fill color (hex)")


def overrides_from_args(args) -> dict:
    """Build a RENDER_DEFAULTS override dict from parsed args."""
    ov: dict = {}
    for flag, key in _FLAG_TO_KEY.items():
        val = getattr(args, flag, None)
        if val is not None:
            ov[key] = val
    if getattr(args, "hdri", None):
        ov["use_hdri"] = True
    if getattr(args, "use_hdri", False):
        ov["use_hdri"] = True
    if getattr(args, "no_hdri", False):
        ov["use_hdri"] = False
    if getattr(args, "persp", False):
        ov["cam_ortho"] = False
    if getattr(args, "ortho", False):
        ov["cam_ortho"] = True
    if getattr(args, "hero_light", False):
        ov["hero_light"] = True
    if getattr(args, "no_hero_light", False):
        ov["hero_light"] = False
    if getattr(args, "no_crop", False):
        ov["stable_crop"] = False
    if getattr(args, "no_transparent", False):
        ov["film_transparent"] = False
    if getattr(args, "no_rotation", False):
        ov["rotation"] = False
    if getattr(args, "hide_objects", None) and isinstance(ov.get("hide_objects"), str):
        ov["hide_objects"] = [h.strip() for h in ov["hide_objects"].split(",") if h.strip()]
    return ov


def main():
    from src.cli import main as cli_main
    cli_main(["render", *sys.argv[1:]])


if __name__ == "__main__":
    main()
