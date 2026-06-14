"""Pipeline orchestrator: .awd + .atf -> .glb / .gltf / .obj.

System-Python side: decode ATF textures to PNG, parse the AWD into a scene,
emit an intermediate JSON, then invoke Blender headless to build and export.

Usage:
    python -m src.pipeline cubikon              # one mesh
    python -m src.pipeline --all                # every mesh in meshes/
    python -m src.pipeline cubikon --gltf --obj # extra formats
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import sys

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import config
from src.atf import atf_to_png
from src.awd import parse_file


def _find_texture(textures_dir: str, mesh_name: str, channel: str) -> str | None:
    """Locate a channel ATF, preferring higher resolution (512 > 256 > 128 > none)."""
    for suffix in ("_512", "_256", "_128", ""):
        atf = os.path.join(textures_dir, f"{mesh_name}_{channel}{suffix}.atf")
        if os.path.exists(atf):
            return atf
    return None


def _resolve_atf(spec: str, dirs: list[str]) -> str | None:
    """Resolve a user-supplied ATF name (basename, with/without .atf) to a path."""
    base = spec[:-4] if spec.lower().endswith(".atf") else spec
    for d in dirs:
        p = os.path.join(d, base + ".atf")
        if os.path.exists(p):
            return p
    return None


def detect_textures(mesh_name: str, textures_dir: str) -> dict[str, str]:
    """Auto-detected {channel: atf_basename} for a mesh (for UI pre-fill)."""
    out = {}
    for channel in config.CHANNELS:
        atf = _find_texture(textures_dir, mesh_name, channel)
        if atf:
            out[channel] = os.path.splitext(os.path.basename(atf))[0]
    return out


def decode_textures(mesh_name: str, textures_dir: str, model_out: str,
                    overrides: dict | None = None) -> dict[str, str]:
    """Decode each channel ATF to PNG; return {channel: png_path}.

    `overrides` maps a channel -> an ATF basename chosen manually (UI); it takes
    precedence over the filename-convention auto-detection, per channel.
    """
    overrides = overrides or {}
    tex_out = os.path.join(model_out, "textures")
    os.makedirs(tex_out, exist_ok=True)
    search = [textures_dir, config.TEXTURES_DIR, config.FX_DIR]
    found: dict[str, str] = {}
    for channel in config.CHANNELS:
        atf = _resolve_atf(overrides[channel], search) if overrides.get(channel) \
            else _find_texture(textures_dir, mesh_name, channel)
        if atf:
            png = os.path.join(tex_out, f"{mesh_name}_{channel}.png")
            try:
                atf_to_png(atf, png)
                found[channel] = png
            except Exception:
                pass
    # fx meshes have no channel convention; fall back to a single <mesh>.atf
    if not found and not overrides:
        single = os.path.join(textures_dir, f"{mesh_name}.atf")
        if os.path.exists(single):
            png = os.path.join(tex_out, f"{mesh_name}_diffuse.png")
            try:
                atf_to_png(single, png)
                found["diffuse"] = png
            except Exception:
                pass
    return found


def build_scene_json(mesh_name: str, meshes_dir: str, textures_dir: str,
                     model_out: str, work: str, textures: dict | None = None,
                     clip: str | None = None) -> str:
    """Parse the AWD and write the intermediate scene JSON. Returns its path."""
    scene = parse_file(os.path.join(meshes_dir, f"{mesh_name}.awd"))
    textures = decode_textures(mesh_name, textures_dir, model_out, overrides=textures)

    objects = []
    for inst in scene.instances:
        geo = scene.geometry_for(inst)
        if not geo or not geo.subs:
            continue
        # merge sub-meshes into one vertex/index/uv set
        positions, indices, uvs = [], [], []
        for sub in geo.subs:
            base = len(positions) // 3
            positions += sub.positions
            indices += [base + i for i in sub.indices]
            uvs += sub.uvs if sub.uvs else [0.0] * (sub.vertex_count * 2)
        is_point = inst.is_point
        # vertex-animation pose frames whose target geometry is this instance's
        # (and whose vertex count matches the merged mesh) -> morph targets.
        # `clip` limits it to one named clip; otherwise all clips are concatenated.
        morphs = [fr for c in scene.clips
                  if c.geometry_id == inst.geometry_id and (not clip or c.name == clip)
                  for fr in c.frames if len(fr) == len(positions)]
        objects.append({
            "name": inst.name,
            "matrix": _matrix16(inst),
            "positions": positions,
            "indices": indices,
            "uvs": uvs,
            # points become empties and need no textures; body meshes share the set
            "textures": {} if is_point else textures,
            "morphs": morphs,
        })

    data = {"name": mesh_name, "objects": objects}
    os.makedirs(work, exist_ok=True)
    json_path = os.path.join(work, f"{mesh_name}.scene.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return json_path


def _matrix16(inst) -> list[float]:
    rows = inst.matrix_rows()
    return [v for row in rows for v in row]


def run_cmd(cmd: list[str], progress=None) -> None:
    """Run a subprocess; if `progress` is given, stream stdout lines to it."""
    if progress is None:
        subprocess.run(cmd, check=True)
        return
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, bufsize=1)
    for line in p.stdout:
        line = line.strip()
        if line:
            progress(line)
    if p.wait():
        raise subprocess.CalledProcessError(p.returncode, cmd)


def run_blender(scene_json: str, out_glb: str, gltf: bool, obj: bool,
                progress=None) -> None:
    cmd = [config.BLENDER_EXE, "--background", "--python",
           config.BUILD_SCENE_SCRIPT, "--", scene_json, out_glb]
    if gltf:
        cmd.append("--gltf")
    if obj:
        cmd.append("--obj")
    run_cmd(cmd, progress)


def convert(mesh_name: str, gltf: bool = False, obj: bool = False,
            run: bool = True, fx: bool = False, textures: dict | None = None,
            clip: str | None = None, progress=None) -> str:
    meshes_dir = config.FX_DIR if fx else config.MESHES_DIR
    textures_dir = config.FX_DIR if fx else config.TEXTURES_DIR
    out_base = config.FX_OUT if fx else config.OUT_DIR
    model = config.model_dir(mesh_name, out_base)
    work = config.work_dir(mesh_name, out_base)
    os.makedirs(model, exist_ok=True)
    scene_json = build_scene_json(mesh_name, meshes_dir, textures_dir, model, work,
                                  textures=textures, clip=clip)
    out_glb = os.path.join(model, f"{mesh_name}.glb")
    if run:
        run_blender(scene_json, out_glb, gltf, obj, progress=progress)
    return out_glb


def main():
    ap = argparse.ArgumentParser(description="DarkOrbit AWD/ATF -> glb pipeline")
    ap.add_argument("mesh", nargs="?", help="mesh name (without .awd)")
    ap.add_argument("--all", action="store_true", help="convert every mesh")
    ap.add_argument("--fx", action="store_true",
                    help="read fx_*.awd + textures from fx/ and output under out/fx/")
    ap.add_argument("--gltf", action="store_true", help="also export .gltf")
    ap.add_argument("--obj", action="store_true", help="also export .obj")
    ap.add_argument("--no-blender", action="store_true",
                    help="only emit scene JSON + textures, skip Blender")
    args = ap.parse_args()

    src_dir = config.FX_DIR if args.fx else config.MESHES_DIR
    if args.all:
        names = [os.path.splitext(os.path.basename(p))[0]
                 for p in sorted(glob.glob(os.path.join(src_dir, "*.awd")))]
    elif args.mesh:
        names = [args.mesh]
    else:
        ap.error("give a mesh name or --all")

    for name in names:
        print(f"=== {name} ===")
        out = convert(name, gltf=args.gltf, obj=args.obj,
                      run=not args.no_blender, fx=args.fx)
        print(f"  -> {out}")


if __name__ == "__main__":
    main()
