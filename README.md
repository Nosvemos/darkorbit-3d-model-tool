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

- **ATF → PNG** — pure-Python decoder for every ATF format in the asset set:
  DXT1 (2) and DXT5 (4) via LZMA indices + JPEG-XR endpoints, raw RGB/RGBA (0/1),
  and raw DXT5 (5).
- **AWD → mesh** — pure-Python AWD2 parser: geometry, scene-graph instances with
  names and transforms, materials, and vertex (pose) animation clips.
- **glb / gltf / obj export** — built in Blender headless, with PBR materials
  wired from the diffuse / normal / specular / glow channels. Each vertex
  animation clip is exported as its own named glTF animation (morph targets).
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
pip install -r requirements.txt     # runtime deps
pip install -e .                    # optional: installs the `do3d` command
```

Set the Blender executable via the `BLENDER` environment variable if it is not at
the default Steam path (see [`src/config.py`](src/config.py)).

---

## Usage

Everything is available through a single command — `do3d` (after
`pip install -e .`) or equivalently `python -m src`:

```
do3d convert <mesh> [--all] [--fx] [--gltf] [--obj] [--no-blender]
do3d render  <mesh> [--all] [--fx] [--mode auto|ship|item] [render options]
do3d fx      <name>  [--all] [--frames N] [--resolution PX] [--margin F]
do3d extract-awp
do3d list    [meshes|fx|effects|textures|all]
do3d info    <mesh> [--fx]
do3d ui      [--host H] [--port P] [--no-browser]
```

```bash
do3d list meshes                 # what can I convert?
do3d info sibelon                # objects, reference points, clips, textures
do3d convert sibelon --gltf --obj
do3d render sibelon --frames 32
do3d fx explosion0
```

The individual modules (`python -m src.pipeline`, `python -m src.render`,
`python -m src.fx_render`) remain available and take the same options as the
matching subcommand. The detailed option tables below apply to both forms.

### Conversion — `do3d convert` / `python -m src.pipeline`

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

### Rendering — `do3d render` / `python -m src.render`

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
  cli.py         unified CLI (do3d / python -m src)
  __main__.py    `python -m src` entry point
  atf/           ATF texture decoder (DXT1 + DXT5)
  awd/           AWD2 mesh parser + scene model
  blender/       headless scene builder + sprite renderer (run inside Blender)
  fx/            .awp particle parser + 2D billboard renderer
  config.py      paths + render defaults
  pipeline.py    conversion orchestrator
  render.py      mesh turntable render orchestrator
  fx_render.py   particle-effect render orchestrator
  server.py      local web UI backend (stdlib http.server)
web/             single-page UI (index.html)
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

## Web UI

A minimal local web UI (Python stdlib `http.server` + a single vanilla-JS page —
no framework, no build step):

```bash
do3d ui            # serves http://127.0.0.1:8765 and opens the browser
```

Browse meshes / fx meshes / effects in the sidebar, inspect an asset (objects,
reference points, clips, textures), then convert to glb or render sprites /
particle effects right from the page. Rendered turntables play back inline as an
animated preview, with download links for the glb and `Coords.json`. Long Blender
renders run as background jobs that stream live progress (elapsed time + log) to
the page. It calls the same functions as the CLI, so anything the UI does is
reproducible on the command line.

**Manual textures.** Auto-detection maps `<mesh>_<channel>_512.atf` by filename;
when an asset doesn't follow that convention (many `fx_*.awd` meshes, or oddly
named ones), the UI's per-channel texture fields let you pick any `.atf` by name
(auto-completed from every texture in `textures/` and `fx/`). Picked textures
override the auto-detected ones per channel and rebuild the glb. On the CLI the
same is available by passing a `textures` dict to `pipeline.convert` /
`render.render`. (Particle effects carry their textures inside the `.awp`, so
they are resolved automatically.)

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
segmented/initial colour, rotation, billboard, orbit, oscillator, sprite-sheet
(flip-book), and UV scroll. (Follow is a no-op in standalone playback, since the
emitter is fixed at the origin.)

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
