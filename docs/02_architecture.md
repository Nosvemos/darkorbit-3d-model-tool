# Architecture & Technical Decisions

## Overall Structure
Hybrid pipeline: pure-Python preprocessing (parse + decode) + Blender headless (scene + export).

```
src/
  atf/
    decoder.py        # ATF → RGBA → PNG
    dxt.py            # BC1/BC3 (DXT1/5) decode
  awd/
    parser.py         # AWDc decompress + AWD2 block parse → intermediate model (dataclass)
    model.py          # Scene / Mesh / Node / Material dataclasses
  blender/
    build_scene.py    # (blender --background --python) import + material wire + empties + export
  pipeline.py         # CLI orchestrator: meshes/ loop
  config.py           # paths, blender exe, output format selection
  render.py             # turntable sprite render orchestrator (Phase 5)
out/
  <mesh>/
    model/   <mesh>.glb (+textures/, gltf/, obj/)
    sprites/ <mesh>_1.png ... + <mesh>_Coords.json   # engine_/laserpoint_ coordinates
    work/    intermediate files (scene/cfg/meta json)
```

## Decision 1 — ATF decode: our own decoder
**Choice**: Write a pure-Python ATF decoder (DXT + LZMA).
**Why**: Full automation is the goal; depending on the ATF2PNG GUI tool breaks automation.
PIL cannot decode DXT → our own BC1/BC3 decoder (`atf/dxt.py`). For LZMA we use the Python
stdlib `lzma`. The existing `cubikon_diffuse_512.png` serves as the validation reference.
**Alternative**: If ATF2PNG.exe supports a CLI, call it via subprocess (fallback).

## Decision 2 — AWD parse: pure-Python AWD2 parser
**Choice**: `awd/parser.py` — zlib decompress + AWD2 block reader.
**Why**: The Prefab3D GUI cannot be scripted. The AWD2 format is documented. Decompress has been validated.
The parser preserves the node tree (`main` + `engine_*` + `laserpoint_*`) and the transforms →
helper points are not lost.

## Decision 3 — Export path: Blender headless (primary)
**Choice**: `blender --background --python build_scene.py`.
**Why**:
- The user's quality expectation matches the existing manual Blender workflow (material nodes).
- The existing render/animation scripts already assume a Blender scene.
- glTF/glb/obj export is mature in Blender; full control over material node wiring.
- For the `engine_/laserpoint_` → Empty conversion, the existing `mesh_to_plain_axes.py` logic
  is reused directly.
**Alternative (next phase)**: Pure-Python glTF writer (a fast path without Blender) — optional.

## Decision 4 — Material node schema (PBR / Principled BSDF)
| ATF channel | Blender connection |
|-----------|--------------------|
| diffuse   | Base Color (sRGB) |
| normal    | Normal Map node → Normal (Non-Color) |
| specular  | Specular / Roughness (Non-Color; inversion may be required) |
| glow      | Emission Color + Emission Strength |

If a channel is missing, that connection is skipped (some meshes may have fewer than 4 textures).

## Decision 5 — Intermediate model (intermediate representation)
The AWD parser does not write directly to Blender; it first writes to the dataclass-based `model.py`
structure. This makes the parser testable independently of Blender + opens up the pure-python glTF
path for the future.

## Flow (single mesh)
```
1. atf.decoder: <mesh>_<channel>_512.atf → out/<mesh>/textures/*.png
2. awd.parser:  meshes/<mesh>.awd → Scene(meshes, nodes, materials)
3. blender.build_scene: Scene + PNGs → import, wire, empties, export
4. pipeline: validate output + <mesh>_points.json, log
```

## Dependencies
- Python 3.14 (current), PIL/Pillow 12.2 (current), stdlib `zlib`/`lzma`/`struct`.
- Blender 5.1.2 (Steam): `C:\Program Files (x86)\Steam\steamapps\common\Blender\blender.exe`.
  ⚠️ 5.x API differences (EEVEE, glTF operators) will be addressed in Phase 3.
