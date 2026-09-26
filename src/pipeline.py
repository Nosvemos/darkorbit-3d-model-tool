"""Pipeline orchestrator: .awd + .atf -> .glb / .gltf / .obj.

System-Python side: decode ATF textures to PNG, parse the AWD into a scene,
emit an intermediate JSON, then invoke Blender headless to build and export.

Usage:
    python -m src.pipeline cubikon              # one mesh
    python -m src.pipeline --all                # every mesh in meshes/
    python -m src.pipeline cubikon --gltf --obj # extra formats
    python -m src.pipeline cubikon --queue      # enqueue on the web UI worker
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
from src.atf import atf_to_png
from src.awd import parse_file


def _find_texture(textures_dir: str, mesh_name: str, channel: str) -> str | None:
    """Locate a channel ATF, preferring higher resolution (512 > 256 > 128 > none)."""
    # ships.xml abstract_petbasic / abstract_wildpet: all ordinary levels use
    # texture="pet" independently of their pet-1 ... pet-15 geometry.
    level = mesh_name.lower().removeprefix('pet-')
    if mesh_name.lower().startswith('pet-') and level.isdigit() and 1 <= int(level) <= 15:
        mesh_name = 'pet'
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


def resolve_design(mesh_name: str, design: str | None) -> str | None:
    """Validate and normalize a supported DarkOrbit design preset."""
    if design in (None, ""):
        return None
    key = str(design).strip().lower()
    if key not in config.DESIGNS:
        choices = ", ".join(sorted(config.DESIGNS))
        raise ValueError(f"unknown design '{design}' (choose {choices})")
    if mesh_name.lower() not in config.DESIGNS[key]['meshes']:
        raise ValueError(f"design '{key}' does not support mesh '{mesh_name}'")
    return key


def _design_geometry(mesh_name: str, design: str | None) -> str:
    key = resolve_design(mesh_name, design)
    if key:
        return config.DESIGNS[key]["geometry"]
    return mesh_name


def _design_texture_overrides(mesh_name: str, design: str | None,
                              textures: dict | None) -> dict | None:
    key = resolve_design(mesh_name, design)
    defaults = dict(config.DESIGNS[key]["textures"]) if key else {}
    defaults.update(textures or {})
    return defaults or None


def _input_file_state(path: str | None) -> dict | None:
    if not path:
        return None
    try:
        stat = os.stat(path)
    except OSError:
        return None
    return {"path": os.path.normcase(os.path.abspath(path)),
            "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def _texture_input_states(mesh_name: str, textures_dir: str,
                          overrides: dict | None = None) -> dict:
    overrides = overrides or {}
    search = [textures_dir, config.TEXTURES_DIR, config.FX_DIR]
    found = {}
    for channel in config.CHANNELS:
        if overrides.get(channel) == "none":
            continue
        atf = _resolve_atf(overrides[channel], search) if overrides.get(channel) \
            else _find_texture(textures_dir, mesh_name, channel)
        if overrides.get(channel) and not atf:
            raise ValueError(f"Missing {channel} ATF: {overrides[channel]}")
        if atf:
            found[channel] = _input_file_state(atf)
    if not found and not overrides:
        single = os.path.join(textures_dir, f"{mesh_name}.atf")
        if os.path.exists(single):
            found["diffuse"] = _input_file_state(single)
    return found


def _pack_away3d_specular(specular_png: str) -> str:
    """Pack Away3D R strength and G gloss into glTF-compatible channels.

    glTF stores roughness in the metallic-roughness texture's G channel and
    KHR_materials_specular strength in the specular texture's alpha channel.
    The source specular map instead stores strength in R and gloss in G.
    """
    with Image.open(specular_png) as source:
        rgba = source.convert("RGBA")
        red, green, _blue, _alpha = rgba.split()
        roughness = green.point(
            lambda gloss: round(255.0 * (2.0 / (50.0 * gloss / 255.0 + 2.0)) ** 0.5)
        )
        zero = Image.new("L", rgba.size, 0)
        packed = Image.merge("RGBA", (zero, roughness, zero, red))
        output = os.path.splitext(specular_png)[0] + "_gltf.png"
        packed.save(output)
    return output


def detect_textures(mesh_name: str, textures_dir: str,
                    single_atf_fallback: bool = False) -> dict[str, str]:
    """Auto-detected {channel: atf_basename} for a mesh (for UI pre-fill)."""
    out = {}
    for channel in config.CHANNELS:
        atf = _find_texture(textures_dir, mesh_name, channel)
        if atf:
            out[channel] = os.path.splitext(os.path.basename(atf))[0]
    if not out and single_atf_fallback:
        single = os.path.join(textures_dir, f"{mesh_name}.atf")
        if os.path.exists(single):
            out["diffuse"] = mesh_name
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
        if overrides.get(channel) == "none":
            continue
        atf = _resolve_atf(overrides[channel], search) if overrides.get(channel) \
            else _find_texture(textures_dir, mesh_name, channel)
        if atf:
            png = os.path.join(tex_out, f"{mesh_name}_{channel}.png")
            try:
                atf_to_png(atf, png)
                found[channel] = png
            except Exception as exc:
                raise RuntimeError(f"Cannot decode {channel} texture {atf}") from exc
    if found.get("specular"):
        found["specular_pbr"] = _pack_away3d_specular(found["specular"])
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
                     clip: str | None = None, overlay: str | None = None,
                     output_name: str | None = None, hide_objects: list[str] | None = None,
                     design: str | None = None) -> str:
    """Parse the AWD and write the intermediate scene JSON. Returns its path."""
    design = resolve_design(mesh_name, design)
    textures = _design_texture_overrides(mesh_name, design, textures)
    geometry_mesh = _design_geometry(mesh_name, design)
    export_name = config.safe_output_name(output_name, mesh_name)
    scene = parse_file(os.path.join(meshes_dir, f"{geometry_mesh}.awd"))
    main_textures = decode_textures(geometry_mesh, textures_dir, model_out,
                                   overrides=textures)

    objects = []

    def _should_hide(name: str) -> bool:
        if not hide_objects:
            return False
        return any(h in name for h in hide_objects if h)

    used_names = set()

    def add_scene_objects(sc, texs, is_overlay=False):
        for inst in sc.instances:
            geo = sc.geometry_for(inst)
            if not geo or not geo.subs:
                continue
            # merge sub-meshes into one vertex/index/uv set
            positions, indices, uvs, normals = [], [], [], []
            has_complete_normals = bool(geo.subs)
            for sub in geo.subs:
                base = len(positions) // 3
                positions += sub.positions
                indices += [base + i for i in sub.indices]
                uvs += sub.uvs if sub.uvs else [0.0] * (sub.vertex_count * 2)
                if len(sub.normals) == sub.vertex_count * 3:
                    normals += sub.normals
                else:
                    has_complete_normals = False
            is_point = inst.is_point
            # vertex-animation clips targeting this instance's geometry -> each becomes
            # its own named glTF animation (morph targets). `clip` limits to one clip;
            # otherwise every matching clip is exported separately.
            clips_out = []
            for c in sc.clips:
                if c.geometry_id != inst.geometry_id or (clip and c.name != clip):
                    continue
                frames = [fr for fr in c.frames if len(fr) == len(positions)]
                if frames:
                    clips_out.append({"name": c.name, "frames": frames})
            object_name = inst.name
            suffix = 1
            while object_name in used_names:
                object_name = f'{inst.name}.{suffix:03d}'
                suffix += 1
            used_names.add(object_name)
            objects.append({
                "name": object_name,
                "overlay": is_overlay,
                "matrix": _matrix16(inst, config.DESIGNS[design].get("mesh_scale", 1) if design and not is_overlay else 1),
                "positions": positions,
                "indices": indices,
                "uvs": uvs,
                # Away3D may omit this stream; preserve it exactly when every
                # merged sub-mesh supplies one, otherwise let Blender derive it.
                "normals": normals if has_complete_normals else [],
                # points become empties and need no textures; body meshes share the set
                "textures": {} if is_point else texs,
                "clips": clips_out,
                "hide": _should_hide(inst.name),
            })

    add_scene_objects(scene, main_textures)

    if overlay:
        overlay_scene = parse_file(os.path.join(meshes_dir, f"{overlay}.awd"))
        overlay_textures = decode_textures(overlay, textures_dir, model_out)
        add_scene_objects(overlay_scene, overlay_textures, is_overlay=True)

    appearance = None
    if design:
        preset = config.DESIGNS[design]
        appearance = {key: preset[key] for key in (
            "rim_color", "rim_strength", "rim_power", "outline_size")}
        appearance["visual_size"] = preset["visual_size"]
    data = {"name": export_name, "source": mesh_name,
            "geometry_source": geometry_mesh, "design": design,
            "appearance": appearance, "objects": objects}
    os.makedirs(work, exist_ok=True)
    json_path = os.path.join(work, f"{export_name}.scene.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return json_path


def _matrix16(inst, scale=1) -> list[float]:
    rows = inst.matrix_rows()
    rows = [[v * scale if i < 3 else v for v in row] for i, row in enumerate(rows)]
    return [v for row in rows for v in row]


def build_inputs(mesh_name: str, fx: bool = False, textures: dict | None = None,
                 clip: str | None = None, overlay: str | None = None,
                 hide_objects: list[str] | None = None,
                 output_name: str | None = None,
                 design: str | None = None) -> dict:
    """Return the normalized inputs that determine a generated GLB."""
    design = resolve_design(mesh_name, design)
    if design and fx:
        raise ValueError("PET design presets cannot be applied to FX meshes")
    effective_textures = _design_texture_overrides(mesh_name, design, textures)
    geometry_mesh = _design_geometry(mesh_name, design)
    export_name = config.safe_output_name(output_name, mesh_name)
    meshes_dir = config.FX_DIR if fx else config.MESHES_DIR
    textures_dir = config.FX_DIR if fx else config.TEXTURES_DIR
    overlay_files = None
    if overlay:
        overlay_files = {
            "awd": _input_file_state(os.path.join(meshes_dir, f"{overlay}.awd")),
            "textures": _texture_input_states(overlay, textures_dir),
        }
    return {
        "source": mesh_name,
        "export_name": export_name,
        "fx": bool(fx),
        "textures": dict(textures or {}),
        "design": design,
        "design_recipe": config.DESIGNS.get(design),
        "clip": clip or None,
        "overlay": overlay or None,
        "hide_objects": list(hide_objects or []),
        "input_files": {
            "awd": _input_file_state(os.path.join(meshes_dir, f"{geometry_mesh}.awd")),
            "textures": _texture_input_states(geometry_mesh, textures_dir,
                                               effective_textures),
            "overlay": overlay_files,
        },
    }


def stop_process(process: subprocess.Popen, timeout: float = 2.0) -> None:
    """Stop and reap a child process, escalating if it ignores termination."""
    if process.poll() is not None:
        return
    try:
        process.terminate()
    except OSError:
        pass
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
        except OSError:
            pass
        try:
            process.wait()
        except OSError:
            pass
    except OSError:
        pass


def run_cmd(cmd: list[str], progress=None, cancel_event=None,
            process_callback=None) -> None:
    """Run a subprocess, stream progress, and optionally support cancellation."""
    if cancel_event is not None and cancel_event.is_set():
        raise CancelledError("job cancelled")
    if progress is None and cancel_event is None:
        subprocess.run(cmd, check=True)
        return
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, bufsize=1)
    try:
        if process_callback:
            process_callback(p)
        for line in p.stdout:
            if cancel_event is not None and cancel_event.is_set():
                stop_process(p)
                raise CancelledError("job cancelled")
            line = line.strip()
            if line and progress:
                progress(line)
        return_code = p.wait()
        if cancel_event is not None and cancel_event.is_set():
            raise CancelledError("job cancelled")
        if return_code:
            raise subprocess.CalledProcessError(return_code, cmd)
    finally:
        if p.poll() is None:
            stop_process(p)
        if p.stdout:
            p.stdout.close()
        if process_callback:
            process_callback(None)


def run_blender(scene_json: str, out_glb: str, gltf: bool, obj: bool,
                progress=None, cancel_event=None, process_callback=None) -> None:
    cmd = [config.BLENDER_EXE, "--background", "--python-exit-code", "1", "--python",
           config.BUILD_SCENE_SCRIPT, "--", scene_json, out_glb]
    if gltf:
        cmd.append("--gltf")
    if obj:
        cmd.append("--obj")
    run_cmd(cmd, progress, cancel_event=cancel_event,
            process_callback=process_callback)


def convert(mesh_name: str, gltf: bool = False, obj: bool = False,
            run: bool = True, fx: bool = False, textures: dict | None = None,
            clip: str | None = None, overlay: str | None = None,
            output_name: str | None = None, hide_objects: list[str] | None = None,
            progress=None, cancel_event=None, process_callback=None,
            design: str | None = None, save_blend: bool = True,
            effect_style: str = "softened", appearance_overrides: dict | None = None) -> str:
    if cancel_event is not None and cancel_event.is_set():
        raise CancelledError("job cancelled")
    export_name = config.safe_output_name(output_name, mesh_name)
    design = resolve_design(mesh_name, design)
    if design and fx:
        raise ValueError("PET design presets cannot be applied to FX meshes")
    effective_textures = _design_texture_overrides(mesh_name, design, textures)
    meshes_dir = config.FX_DIR if fx else config.MESHES_DIR
    textures_dir = config.FX_DIR if fx else config.TEXTURES_DIR
    out_base = config.FX_OUT if fx else config.OUT_DIR
    model = config.model_dir(export_name, out_base)
    work = config.work_dir(export_name, out_base)
    os.makedirs(model, exist_ok=True)
    scene_json = build_scene_json(mesh_name, meshes_dir, textures_dir, model, work,
                                  textures=effective_textures, clip=clip, overlay=overlay,
                                  output_name=export_name, hide_objects=hide_objects,
                                  design=design)
    out_glb = os.path.join(model, f"{export_name}.glb")
    if run:
        run_blender(scene_json, out_glb, gltf, obj, progress=progress,
                    cancel_event=cancel_event, process_callback=process_callback)
        if not os.path.isfile(out_glb) or os.path.getsize(out_glb) == 0:
            raise RuntimeError(
                f"Blender finished without creating the expected GLB: {out_glb}")
        if save_blend:
            cfg = {**config.RENDER_DEFAULTS, **config.RENDER_PROFILES['darkorbit'],
                   'frames': 1, 'source_scene': scene_json, 'effect_style': effect_style,
                   'blend_path': os.path.join(model, f'{export_name}.blend')}
            def check_cancelled():
                if cancel_event is not None and cancel_event.is_set():
                    raise CancelledError('job cancelled')
            if design:
                from src.fx.scene import prepare
                preset = config.DESIGNS[design]
                cfg['appearance'] = config.appearance_settings(preset, appearance_overrides or {})
                cfg['particle_scene'] = prepare(config.design_particles(preset, cfg['appearance']),
                                                work, cfg, check_cancelled)
            cfg_path = os.path.join(work, f'{export_name}_scene_cfg.json')
            with open(cfg_path, 'w', encoding='utf-8') as f:
                json.dump(cfg, f)
            run_cmd([config.BLENDER_EXE, '--background', '--python-exit-code', '1',
                     '--python', config.RENDER_SCRIPT, '--', out_glb, work,
                     cfg_path, '--scene-only'], progress, cancel_event=cancel_event,
                    process_callback=process_callback)
        with open(os.path.join(work, f"{export_name}_build.json"), "w",
                  encoding="utf-8") as f:
            json.dump({"version": config.MODEL_BUILD_VERSION,
                       **build_inputs(mesh_name, fx=fx, textures=textures,
                                      clip=clip, overlay=overlay,
                                      hide_objects=hide_objects,
                                      output_name=export_name,
                                      design=design)}, f)
    return out_glb


def main():
    from src.cli import main as cli_main
    cli_main(["convert", *sys.argv[1:]])


if __name__ == "__main__":
    main()
