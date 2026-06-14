# DarkOrbit 3D Model Tool

Convert DarkOrbit game assets — Away3D `.awd` meshes and Adobe `.atf` textures —
into modern 3D formats (`.glb` / `.gltf` / `.obj`) and render turntable sprite
sequences, fully automated from the command line.

It replaces a manual, GUI-driven workflow (ATF2PNG → Prefab3D → Blender) with a
single repeatable pipeline, while **preserving auxiliary scene nodes**
(`engine_*`, `laserpoint_*`, `light_position`) as reference points for later
rendering and animation.

---

## Features

- **ATF → PNG** — pure-Python decoder for ATF (format 2 / DXT1): LZMA colour
  indices + JPEG-XR endpoints decoded straight to RGBA.
- **AWD → mesh** — pure-Python AWD2 parser: geometry, scene-graph instances with
  names and transforms, materials, and animation-clip names.
- **glb / gltf / obj export** — built in Blender headless, with PBR materials
  wired from the diffuse / normal / specular / glow channels.
- **Reference points preserved** — `engine_*` / `laserpoint_*` / `light_position`
  nodes are exported as Empties parented to the main body.
- **Turntable sprite renderer** — headless, reproducible lighting, any frame
  count, with per-frame screen coordinates of the reference points.
- **Batch** — convert or render the whole asset set with one command.

---

## Requirements

| Dependency | Version | Used by |
|------------|---------|---------|
| Python     | 3.10+   | pipeline, decoders |
| Pillow     | ≥ 10    | PNG I/O, sprite cropping |
| NumPy      | ≥ 1.26  | DXT1 decode |
| imagecodecs| ≥ 2024.1| JPEG-XR decode |
| Blender    | 5.x     | scene build, glTF/obj export, rendering |

```bash
pip install -r requirements.txt
```

Set the Blender executable via the `BLENDER` environment variable if it is not at
the default Steam path (see [`src/config.py`](src/config.py)).

---

## Usage

### Conversion — `python -m src.pipeline`

```bash
python -m src.pipeline sibelon              # one mesh -> out/sibelon/model/sibelon.glb
python -m src.pipeline sibelon --gltf --obj # also emit gltf and obj
python -m src.pipeline --all                # every mesh in meshes/
```

| Argument | Description |
|----------|-------------|
| `mesh` | Mesh name without extension (e.g. `sibelon`). Omit when using `--all`. |
| `--all` | Convert every `.awd` in `meshes/` (or `fx/` with `--fx`). |
| `--fx` | Read `fx_*.awd` + textures from `fx/`; output under `out/fx/<mesh>/`. |
| `--gltf` | Also export `.gltf` (separate) into `model/gltf/`. |
| `--obj` | Also export `.obj` (+ `.mtl`) into `model/obj/`. |
| `--no-blender` | Only decode textures and emit the scene JSON; skip Blender. |

Texture lookup prefers the highest resolution available
(`<mesh>_<channel>_512/256/128.atf`) and falls back to a single `<mesh>.atf`
bound as the base colour (used by `fx/` meshes, which have no channel naming).

### Rendering — `python -m src.render`

```bash
python -m src.render sibelon                       # 72-frame turntable, 256 px
python -m src.render sibelon --frames 32           # any count -> full 360° turntable
python -m src.render lf4 --mode item               # plain item/ore render, no points
python -m src.render sibelon --resolution 1024 --samples 128 --persp
python -m src.render sibelon --hdri city.exr --elevation 60 --azimuth 30
python -m src.render --all
```

If the `.glb` does not exist yet, the renderer builds it first.

**Render mode** — `--mode`:

| Mode | Behaviour |
|------|-----------|
| `auto` *(default)* | Track points and write `Coords.json` if the model has `engine_*` / `laserpoint_*` nodes; otherwise a plain render. |
| `ship` | Force point tracking + `Coords.json`. |
| `item` | Plain render (ore, items such as `lf4`, …) — no point tracking, no `Coords.json`. |

**Turntable**

| Argument | Default | Description |
|----------|---------|-------------|
| `--frames N` | 72 | Frame count. |
| `--total-degrees D` | 360 | Total sweep; per-frame step = `D / frames`. |
| `--deg-per-frame D` | — | Explicit step, overrides `total-degrees / frames`. |
| `--start-angle D` | 90 | Turntable rotation at frame 1 (front faces screen-right). |
| `--frame-start N` | 1 | First frame number in filenames (`<mesh>_1.png`). |

**Output / quality**

| Argument | Default | Description |
|----------|---------|-------------|
| `--resolution PX` | 256 | Square render resolution. |
| `--samples N` | 96 | EEVEE render samples. |
| `--engine NAME` | `BLENDER_EEVEE` | Render engine. |
| `--view-transform NAME` | `Standard` | Colour management (`Standard` / `AgX` / `Filmic`). |
| `--no-crop` | off | Disable the global stable crop. |
| `--no-transparent` | off | Render on an opaque background. |
| `--origin MODE` | `TOP_LEFT` | Coordinate origin (`TOP_LEFT` / `BOTTOM_LEFT`). |

**Camera / lighting**

| Argument | Default | Description |
|----------|---------|-------------|
| `--hdri FILE` | `studio.exr` | Bundled world HDRI (see below). |
| `--world-strength F` | 0.8 | World/HDRI strength. |
| `--sun-energy F` | 1.5 | Sun lamp energy. |
| `--emission F` | 0.6 | Glow/emission map multiplier. |
| `--elevation D` | 55 | Camera elevation above the horizon. |
| `--azimuth D` | -90 | Camera azimuth around Z. |
| `--persp` | ortho | Use a perspective camera instead of orthographic. |
| `--margin F` | 1.15 | Framing padding factor (> 1 zooms out). |

Bundled HDRIs: `studio` · `city` · `courtyard` · `forest` · `interior` · `night`
· `sunrise` · `sunset`.

All defaults live in `RENDER_DEFAULTS` in [`src/config.py`](src/config.py).

---

## Output structure

```
out/<mesh>/
  model/
    <mesh>.glb              # primary, self-contained (textures embedded)
    textures/               # decoded source PNGs (diffuse/normal/specular/glow)
    gltf/  <mesh>.gltf + .bin + textures
    obj/   <mesh>.obj + .mtl
  sprites/
    <mesh>_1.png … <mesh>_N.png
    <mesh>_Coords.json      # per-frame reference-point screen positions
  work/                     # intermediates (scene / config / meta JSON)
```

`<mesh>_Coords.json` is a flat map of the per-frame screen positions of the
`engine_*` / `laserpoint_*` points:

```json
{
    "engine_0": [[19, 107], [20, 113], "OFF", ...],
    "laserpoint_leftFrontOuter": [[168, 119], ...]
}
```

`"OFF"` marks a frame where the point is off-screen. Coordinates are relative to
the cropped sprite.

---

## How it works

```
.awd ──▶ AWD2 parser ──▶ geometry + named nodes + transforms ─┐
                                                              ├─▶ scene JSON ──▶ Blender ──▶ glb/gltf/obj
.atf ──▶ ATF decoder ──▶ PNG (diffuse/normal/specular/glow) ──┘                    │
                                                                                   └──▶ turntable render ──▶ sprites + Coords.json
```

System-side Python (NumPy / imagecodecs) handles decoding and parsing; Blender
runs headless with only `bpy` + the standard library. The two sides communicate
through JSON, so neither depends on the other's libraries.

---

## Project layout

```
src/
  atf/           ATF texture decoder
  awd/           AWD2 mesh parser + scene model
  blender/       headless scene builder + sprite renderer (run inside Blender)
  config.py      paths + render defaults
  pipeline.py    conversion orchestrator
  render.py      render orchestrator
tools/           standalone inspection/preview helpers
docs/            format research, architecture, roadmap
```

---

## Documentation

| Doc | Contents |
|-----|----------|
| [`docs/00_overview.md`](docs/00_overview.md) | Goals, manual vs. automated workflow |
| [`docs/01_formats.md`](docs/01_formats.md) | AWD & ATF binary format findings |
| [`docs/02_architecture.md`](docs/02_architecture.md) | Pipeline architecture & decisions |
| [`docs/03_roadmap.md`](docs/03_roadmap.md) | Phased implementation status |
| [`docs/04_blender_scripts.md`](docs/04_blender_scripts.md) | Notes on the original Blender scripts |
| [`docs/05_open_questions.md`](docs/05_open_questions.md) | Resolved decisions & open questions |

---

## FX / particle assets

The `fx/` folder holds particle-effect assets: `fx_*.awd` meshes, `.atf` textures,
and `<name>.zip` archives that each contain a single `<name>.awp`. An `.awp` is
**plain JSON** describing an Away3D particle effect (`particleEvents`,
`animationDatas`, `nodes`, material/geometry references).

**Render an effect to sprite frames** — `python -m src.fx_render`:

```bash
python -m src.fx_render explosion0                 # -> out/fx/explosion0/sprites/
python -m src.fx_render explosion0 --frames 24 --resolution 256
python -m src.fx_render --all
```

The particles are simulated in 3D and composited as camera-facing billboards with
the layer's blend mode (additive / alpha). The referenced textures are decoded
straight from the `.atf` assets (DXT1 + DXT5). The `.zip` is unpacked
automatically; to just extract the JSON:

```bash
python tools/extract_awp.py        # unpack every fx/*.zip into fx/awp/ and validate JSON
```

| Argument | Default | Description |
|----------|---------|-------------|
| `name` | — | Effect name (without `.zip`/`.awp`). Omit with `--all`. |
| `--all` | — | Render every `fx/*.zip`. |
| `--frames N` | 30 | Frames across the effect duration. |
| `--resolution PX` | 256 | Square sprite resolution. |
| `--margin F` | 1.2 | Canvas padding factor. |

Supported particle nodes: time, position, velocity, acceleration, scale,
segmented/initial colour, rotation, billboard. (Orbit / oscillator / sprite-sheet
/ UV / follow are not modelled yet.)

The plain `fx_*.awd` meshes in `fx/` (rings, spheres, shards, …) convert and
render with the `--fx` flag, which sources both meshes and textures from `fx/`
and writes under `out/fx/<mesh>/`:

```bash
python -m src.pipeline fx_crystal_shard --fx       # -> out/fx/fx_crystal_shard/model/
python -m src.render fx_ring --fx                  # turntable sprites
python -m src.pipeline --all --fx                  # every fx_*.awd
```

## Testing

Unit tests run on synthetic AWD/ATF byte streams, so no game assets are
required:

```bash
pip install -r requirements-dev.txt
pytest
```

Tests cover the AWD2 parser (both header variants, geometry/instance/material
decoding, orphan-name recovery, the property-skip regression), the ATF decoder
(header parsing, DXT1 reconstruction, full encode→decode round-trip), the
intermediate model, the render stable-crop / coordinate logic, and the `.awp`
particle parser (value samplers, segmented colour, effect loading). The Blender
scripts (which need `bpy`) are syntax-checked rather than executed.

CI runs the suite on Python 3.10–3.12 via GitHub Actions
([`.github/workflows/ci.yml`](.github/workflows/ci.yml)).

## License

[MIT](LICENSE) © 2026 Samet Ozturk

## Disclaimer

For educational and personal use. Game assets (`meshes/`, `textures/`) are the
property of their respective owners and are **not** included in this repository.
