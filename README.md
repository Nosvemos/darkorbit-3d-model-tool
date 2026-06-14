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

## Status

🚧 Planning complete. Implementation starts with the ATF decoder (Phase 1) and
AWD parser (Phase 2), validated end-to-end on a single mesh first.

## License

[MIT](LICENSE) © 2026 Samet Ozturk

## Disclaimer

This tool is for educational and personal use. Game assets (`meshes/`, `textures/`)
are property of their respective owners and are **not** included in this repository.
