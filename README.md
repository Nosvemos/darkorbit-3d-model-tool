# DarkOrbit 3D Model Tool

Automated pipeline that converts DarkOrbit game assets — Away3D `.awd` meshes and
Adobe `.atf` textures — into modern 3D formats (`.glb` / `.gltf` / `.obj`),
renders turntable sprite sequences, and bakes Away3D particle effects to sprite
frames. Driven from a single CLI or a local web UI.

It replaces a manual, GUI-driven workflow (ATF2PNG → Prefab3D → Blender) with one
repeatable command, while preserving auxiliary scene nodes (`engine_*`,
`laserpoint_*`, `light_position`) as reference points for later use.

## Features

- **ATF decoder** — pure-Python, covers every ATF format in the asset set: DXT1,
  DXT5, raw RGB/RGBA, and raw DXT5 (LZMA + JPEG-XR where needed).
- **AWD parser** — pure-Python AWD2 reader: geometry, named scene-graph instances
  with transforms, materials, and vertex (pose) animation clips.
- **Export** — glb / gltf / obj via headless Blender, with PBR materials wired
  from the diffuse / normal / specular / glow channels. Each animation clip is
  exported as a separate named glTF animation (morph targets).
- **Reference points** — `engine_*` / `laserpoint_*` / `light_position` nodes are
  preserved as Empties parented to the main body.
- **Turntable renderer** — reproducible headless lighting, any frame count,
  optional per-frame screen coordinates of the reference points.
- **Particle effects** — `.awp` effects simulated and composited to sprite frames.
- **Interfaces** — unified `do3d` CLI and a dependency-free local web UI.

## Requirements

| Dependency  | Version   | Used for                          |
|-------------|-----------|-----------------------------------|
| Python      | 3.10+     | pipeline and decoders             |
| Pillow      | ≥ 10      | PNG I/O, sprite cropping          |
| NumPy       | ≥ 1.26    | DXT decode                        |
| imagecodecs | ≥ 2024.1  | JPEG-XR decode                    |
| Blender     | 5.x       | scene build, export, rendering    |

## Installation

```bash
pip install -r requirements.txt     # runtime dependencies
pip install -e .                    # optional: install the `do3d` command
```

Blender is located at the default Steam path; override it with the `BLENDER`
environment variable (see [`src/config.py`](src/config.py)).

## Quick start

```bash
do3d list meshes                     # list convertible meshes
do3d info sibelon                    # inspect objects, points, clips, textures
do3d convert sibelon --gltf --obj    # AWD/ATF -> glb (+ gltf, obj)
do3d render sibelon --frames 32      # turntable sprite sequence + Coords.json
do3d fx explosion0                   # particle effect -> sprite frames
do3d ui                              # local web UI
```

Every command is also available as `python -m src <command>`, and the individual
modules (`python -m src.pipeline` / `src.render` / `src.fx_render`) accept the
same options as their subcommand.

## Commands

| Command       | Purpose                                              |
|---------------|------------------------------------------------------|
| `convert`     | Convert an AWD mesh (+ ATF textures) to glb/gltf/obj |
| `render`      | Render a mesh turntable to a sprite sequence         |
| `fx`          | Render an `.awp` particle effect to sprite frames    |
| `list`        | List meshes / fx meshes / effects / textures         |
| `info`        | Inspect a mesh (objects, points, clips, textures)    |
| `extract-awp` | Unpack `fx/*.zip` archives into `fx/awp/`            |
| `ui`          | Launch the local web UI                              |

A mesh name (without extension) is the positional argument for `convert`,
`render`, and `info`; omit it and pass `--all` to process the whole set.

### `convert`

| Option         | Description                                                       |
|----------------|-------------------------------------------------------------------|
| `--all`        | Convert every mesh in `meshes/` (or `fx/` with `--fx`).           |
| `--fx`         | Source from `fx/`; output under `out/fx/<mesh>/`.                 |
| `--gltf`       | Also export `.gltf` (separate) into `model/gltf/`.                |
| `--obj`        | Also export `.obj` (+ `.mtl`) into `model/obj/`.                  |
| `--no-blender` | Decode textures and emit the scene JSON only; skip Blender.       |

### `render`

`--mode` selects how reference points are handled:

| Mode   | Behaviour                                                                |
|--------|-------------------------------------------------------------------------|
| `auto` | Track points and write `Coords.json` if present; otherwise plain render. *(default)* |
| `ship` | Force point tracking and `Coords.json`.                                  |
| `item` | Plain render (ore, items) — no point tracking, no `Coords.json`.         |

**Turntable**

| Option              | Default | Description                                          |
|---------------------|---------|------------------------------------------------------|
| `--frames N`        | 72      | Frame count.                                         |
| `--total-degrees D` | 360     | Total sweep; per-frame step = `D / frames`.          |
| `--deg-per-frame D` | —       | Explicit step (overrides `total-degrees / frames`).  |
| `--start-angle D`   | 90      | Rotation at frame 1 (front faces screen-right).      |
| `--frame-start N`   | 1       | First frame number in filenames.                     |
| `--clip NAME`       | all     | Play/export a single animation clip.                 |

**Output & quality**

| Option                  | Default          | Description                              |
|-------------------------|------------------|------------------------------------------|
| `--resolution PX`       | 256              | Square render resolution.                |
| `--samples N`           | 96               | EEVEE render samples.                    |
| `--engine NAME`         | `BLENDER_EEVEE`  | Render engine.                           |
| `--view-transform NAME` | `Standard`       | Colour management (`Standard`/`AgX`/`Filmic`). |
| `--no-crop`             | off              | Disable the global stable crop.          |
| `--no-transparent`      | off              | Render on an opaque background.          |
| `--origin MODE`         | `TOP_LEFT`       | Coordinate origin (`TOP_LEFT`/`BOTTOM_LEFT`). |

**Camera & lighting**

| Option               | Default       | Description                              |
|----------------------|---------------|------------------------------------------|
| `--hdri FILE`        | `studio.exr`  | Bundled world HDRI (see below).          |
| `--world-strength F` | 0.8           | World/HDRI strength.                     |
| `--sun-energy F`     | 1.5           | Sun lamp energy.                         |
| `--emission F`       | 0.6           | Glow/emission map multiplier.            |
| `--elevation D`      | 55            | Camera elevation above the horizon.      |
| `--azimuth D`        | -90           | Camera azimuth around Z.                 |
| `--persp`            | ortho         | Perspective camera instead of orthographic. |
| `--margin F`         | 1.15          | Framing padding factor (> 1 zooms out).  |

Bundled HDRIs: `studio` · `city` · `courtyard` · `forest` · `interior` · `night`
· `sunrise` · `sunset`. All defaults live in `RENDER_DEFAULTS`
([`src/config.py`](src/config.py)).

### `fx`

| Option            | Default | Description                              |
|-------------------|---------|------------------------------------------|
| `--all`           | —       | Render every effect (`fx/*.zip`).        |
| `--frames N`      | 30      | Frames across the effect duration.       |
| `--resolution PX` | 256     | Square sprite resolution.                |
| `--margin F`      | 1.2     | Canvas padding factor.                   |

## Output structure

```
out/<mesh>/
  model/
    <mesh>.glb            # primary, self-contained (textures embedded)
    textures/             # decoded source PNGs
    gltf/                 # <mesh>.gltf + .bin + textures
    obj/                  # <mesh>.obj + .mtl
  sprites/
    <mesh>_1.png … _N.png
    <mesh>_Coords.json    # per-frame reference-point screen positions
  work/                   # intermediates (scene / config / meta JSON)
```

`<mesh>_Coords.json` is a flat map of per-frame screen positions; `"OFF"` marks a
frame where the point is off-screen, and coordinates are relative to the cropped
sprite:

```json
{
    "engine_0": [[19, 107], [20, 113], "OFF"],
    "laserpoint_leftFrontOuter": [[168, 119], [167, 121], [166, 124]]
}
```

## Web UI

```bash
do3d ui            # serves http://127.0.0.1:8765
```

A single vanilla-JS page served by the Python standard library — no framework, no
build step. Browse meshes / fx meshes / effects, inspect an asset, and convert or
render directly from the page. Rendered turntables play back inline; long Blender
runs stream live progress. Per-channel texture fields let you assign any `.atf`
when auto-detection misses, and an animation-clip selector picks which clip to
play. Every action maps to the same functions as the CLI.

## FX / particle effects

The `fx/` folder holds particle assets: `fx_*.awd` meshes, `.atf` textures, and
`<name>.zip` archives each containing one `<name>.awp`. An `.awp` is plain JSON
describing an Away3D particle effect.

`do3d fx <name>` simulates the particles in 3D and composites them as
camera-facing billboards (additive / alpha blend), decoding referenced textures
straight from the `.atf` assets. Supported nodes: time, position, velocity,
acceleration, scale, segmented/initial colour, rotation, billboard, orbit,
oscillator, sprite-sheet (flip-book), and UV scroll.

The plain `fx_*.awd` meshes (rings, spheres, shards) convert and render with the
`--fx` flag, which sources meshes and textures from `fx/` and writes under
`out/fx/<mesh>/`.

## How it works

```
.awd ──▶ AWD2 parser ──▶ geometry + named nodes + transforms ─┐
                                                              ├─▶ scene JSON ──▶ Blender ──▶ glb / gltf / obj
.atf ──▶ ATF decoder ──▶ PNG (diffuse/normal/specular/glow) ──┘                  │
                                                                                 └──▶ turntable render ──▶ sprites + Coords.json
```

System-side Python (NumPy / imagecodecs) handles decoding and parsing; Blender
runs headless with only `bpy` and the standard library. The two sides communicate
through JSON, so neither depends on the other's libraries.

## Project layout

```
src/
  cli.py          unified CLI entry point
  pipeline.py     AWD/ATF -> glb conversion orchestrator
  render.py       mesh turntable render orchestrator
  fx_render.py    particle-effect render orchestrator
  server.py       local web UI backend (stdlib http.server)
  config.py       paths and render defaults
  atf/            ATF texture decoder
  awd/            AWD2 mesh parser + scene model
  blender/        headless scene builder + sprite renderer (run inside Blender)
  fx/             .awp particle parser + 2D billboard renderer
web/              single-page web UI
tools/            standalone inspection / preview helpers
docs/             format research, architecture, roadmap
tests/            unit tests (synthetic assets, no Blender)
```

## Testing

```bash
pip install -r requirements-dev.txt
pytest
```

Tests run on synthetic AWD/ATF byte streams, so no game assets are required. They
cover the AWD2 parser, the ATF decoder, the intermediate model, the render
stable-crop / coordinate logic, the `.awp` particle parser, and the CLI. The
Blender scripts are syntax-checked rather than executed. CI runs the suite on
Python 3.10–3.12 ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)).

## Documentation

| Document | Contents |
|----------|----------|
| [`docs/00_overview.md`](docs/00_overview.md)             | Goals, manual vs. automated workflow |
| [`docs/01_formats.md`](docs/01_formats.md)               | AWD & ATF binary format findings     |
| [`docs/02_architecture.md`](docs/02_architecture.md)     | Pipeline architecture & decisions    |
| [`docs/03_roadmap.md`](docs/03_roadmap.md)               | Phased implementation status         |
| [`docs/04_blender_scripts.md`](docs/04_blender_scripts.md) | Notes on the original Blender scripts |
| [`docs/05_open_questions.md`](docs/05_open_questions.md) | Resolved decisions & open questions  |

## License

[MIT](LICENSE) © 2026 Samet Ozturk

## Disclaimer

For educational and personal use. Game assets (`meshes/`, `textures/`, `fx/`) are
the property of their respective owners and are **not** included in this
repository.
