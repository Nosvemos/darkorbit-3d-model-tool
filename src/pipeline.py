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


def decode_textures(mesh_name: str) -> dict[str, str]:
    """Decode each available channel ATF to PNG; return {channel: png_path}."""
    tex_out = os.path.join(config.model_dir(mesh_name), "textures")
    os.makedirs(tex_out, exist_ok=True)
    found: dict[str, str] = {}
    for channel in config.CHANNELS:
        atf = os.path.join(config.TEXTURES_DIR,
                           f"{mesh_name}_{channel}{config.TEXTURE_SUFFIX}.atf")
        if os.path.exists(atf):
            png = os.path.join(tex_out, f"{mesh_name}_{channel}.png")
            atf_to_png(atf, png)
            found[channel] = png
    return found


def build_scene_json(mesh_name: str) -> str:
    """Parse the AWD and write the intermediate scene JSON. Returns its path."""
    scene = parse_file(os.path.join(config.MESHES_DIR, f"{mesh_name}.awd"))
    textures = decode_textures(mesh_name)

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
        objects.append({
            "name": inst.name,
            "matrix": _matrix16(inst),
            "positions": positions,
            "indices": indices,
            "uvs": uvs,
            # points become empties and need no textures; body meshes share the set
            "textures": {} if is_point else textures,
        })

    data = {"name": mesh_name, "objects": objects}
    work = config.work_dir(mesh_name)
    os.makedirs(work, exist_ok=True)
    json_path = os.path.join(work, f"{mesh_name}.scene.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return json_path


def _matrix16(inst) -> list[float]:
    rows = inst.matrix_rows()
    return [v for row in rows for v in row]


def run_blender(scene_json: str, out_glb: str, gltf: bool, obj: bool) -> None:
    cmd = [config.BLENDER_EXE, "--background", "--python",
           config.BUILD_SCENE_SCRIPT, "--", scene_json, out_glb]
    if gltf:
        cmd.append("--gltf")
    if obj:
        cmd.append("--obj")
    subprocess.run(cmd, check=True)


def convert(mesh_name: str, gltf: bool = False, obj: bool = False,
            run: bool = True) -> str:
    model = config.model_dir(mesh_name)
    os.makedirs(model, exist_ok=True)
    scene_json = build_scene_json(mesh_name)
    out_glb = os.path.join(model, f"{mesh_name}.glb")
    if run:
        run_blender(scene_json, out_glb, gltf, obj)
    return out_glb


def main():
    ap = argparse.ArgumentParser(description="DarkOrbit AWD/ATF -> glb pipeline")
    ap.add_argument("mesh", nargs="?", help="mesh name (without .awd)")
    ap.add_argument("--all", action="store_true", help="convert every mesh")
    ap.add_argument("--gltf", action="store_true", help="also export .gltf")
    ap.add_argument("--obj", action="store_true", help="also export .obj")
    ap.add_argument("--no-blender", action="store_true",
                    help="only emit scene JSON + textures, skip Blender")
    args = ap.parse_args()

    if args.all:
        names = [os.path.splitext(os.path.basename(p))[0]
                 for p in sorted(glob.glob(os.path.join(config.MESHES_DIR, "*.awd")))]
    elif args.mesh:
        names = [args.mesh]
    else:
        ap.error("give a mesh name or --all")

    for name in names:
        print(f"=== {name} ===")
        out = convert(name, gltf=args.gltf, obj=args.obj, run=not args.no_blender)
        print(f"  -> {out}")


if __name__ == "__main__":
    main()
