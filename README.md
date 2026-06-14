# DarkOrbit 3D Model Tool

Automated pipeline that converts DarkOrbit game assets — Away3D `.awd` meshes and
Adobe `.atf` textures — into modern 3D formats (`.glb` / `.gltf` / `.obj`) ready for
use in current 3D applications.

The goal is to replace a manual, GUI-driven workflow (ATF2PNG → Prefab3D → Blender)
with a single repeatable command, while **preserving auxiliary scene nodes**
(`engine_*`, `laserpoint_*`) as reference points for later rendering and animation.

## Pipeline

```
.awd  ──parse──▶ geometry + node tree (main, engine_*, laserpoint_*) + material refs
.atf  ──decode─▶ .png (diffuse / normal / specular / glow)
                          │
                          ▼
          Blender (headless): build scene, wire PBR material nodes,
          convert engine_/laserpoint_ to Empties, export
                          │
                          ▼
                  .glb (primary) / .gltf / .obj
```

## Key facts

- **AWD** — `AWDc` magic, 12-byte header + zlib-compressed body (AWD2 block list inside).
- **ATF** — GPU texture container (DXT + LZMA), decoded by a pure-Python decoder.
- **Output** — `.glb` is primary (single file, embedded textures, preserves node
  hierarchy and empties). `.gltf` / `.obj` are optional.
- **Blender** — headless export via Blender 5.x.

## Requirements

- Python 3.14+ with [Pillow](https://python-pillow.org/)
- Blender 5.x (for the scene-build / export stage)

## Documentation

Full plan and format research live in [`docs/`](docs/):

| Doc | Contents |
|-----|----------|
| [`00_overview.md`](docs/00_overview.md) | Goals, manual vs. automated workflow |
| [`01_formats.md`](docs/01_formats.md) | AWD & ATF binary format findings |
| [`02_architecture.md`](docs/02_architecture.md) | Pipeline architecture & technical decisions |
| [`03_roadmap.md`](docs/03_roadmap.md) | Phased implementation plan |
| [`04_blender_scripts.md`](docs/04_blender_scripts.md) | Review of existing Blender scripts |
| [`05_open_questions.md`](docs/05_open_questions.md) | Resolved decisions & remaining questions |

## Usage

```bash
# Convert a mesh (or --all) to glb (+ optional gltf/obj)
python -m src.pipeline sibelon --gltf --obj
python -m src.pipeline --all

# Render a turntable sprite sequence + reference-point coordinates
python -m src.render sibelon --frames 32
python -m src.render sibelon --resolution 1024 --samples 128 --hdri city.exr
python -m src.render --all
```

Output is grouped per mesh:

```
out/<mesh>/
  model/    <mesh>.glb, textures/, gltf/, obj/
  sprites/  <mesh>_1.png … <mesh>_N.png, <mesh>_Coords.json
  work/     intermediates
```

`<mesh>_Coords.json` is a flat `{point_name: [[x, y] | "OFF", ...]}` map of the
per-frame screen positions of the `engine_*` / `laserpoint_*` points.

Render is fully configurable via CLI flags (frame count, resolution, samples,
camera elevation/azimuth, HDRI, lighting, view transform, …) or
`config.RENDER_DEFAULTS`. Frame step is derived from `total_degrees / frames`,
so any frame count produces a full turntable.

## Status

✅ Working end to end: all 11 meshes convert to glb and render turntable sprites.
ATF decoder, AWD parser, Blender scene builder, batch pipeline, and headless
sprite renderer are implemented and verified. See [`docs/`](docs/) for details.

## License

[MIT](LICENSE) © 2026 Samet Ozturk

## Disclaimer

This tool is for educational and personal use. Game assets (`meshes/`, `textures/`)
are property of their respective owners and are **not** included in this repository.
