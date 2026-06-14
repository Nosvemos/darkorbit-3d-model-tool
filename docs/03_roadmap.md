# Roadmap (Phases)

Principle: each phase produces an independently verifiable output. First run end-to-end
on a single mesh (cubikon), then process in batch.

## Phase 0 — Project skeleton
- [ ] `src/` package structure, `config.py`, `requirements.txt`.
- [ ] Blender exe path detection/configuration.

## Phase 1 — ATF decoder ✅
- [x] ATF header parse (new-version offset 12; format/width/height/mip).
- [x] Block structure resolved: format 2 = DXT1, 2 blocks (UI32-BE length-prefixed).
- [x] LZMA block decompress (raw LZMA, stdlib `lzma` FORMAT_RAW) → DXT1 indices.
- [x] JPEG-XR block decode (`imagecodecs`) → DXT1 endpoint planes (RGB888, lossy).
- [x] DXT1 → RGBA decode (numpy vectorized; RGB565 round-trip skipped, better quality).
- [x] PNG writing.
- [x] **Verification**: 44/44 textures decoded; diffuse/normal/glow/specular visual check
      correct (normal map blue, glow black-on-emissive). `src/atf/`, `tools/dump_atf.py`.
      Note: the old reference PNG had been deleted → visual verification was done.

## Phase 2 — AWD parser ✅
- [x] Header + zlib decompress — `AWDc` and standard `AWD\x02` variants (offset 12).
- [x] AWD2 block iterator (id/ns/type/flags/len, little-endian).
- [x] Geometry blocks (type 1) → vertex/index/uv streams (ftype 5=u16, 7=f32).
- [x] Mesh instance blocks (type 23) → node name + 3x4 transform + geom/material ref.
- [x] Material blocks (type 81) → name + flag props. With texture naming convention.
- [x] Animation clip names (type 112) → `open`/`close`/`idle`.
- [x] Robustness: f64-matrix variant + orphan geometry without an instance → synthetic
      instance; name recovery from `null~<name>` material (protegit engine_0).
- [x] **Verification**: all 11 meshes parsed; `engine_*`/`laserpoint_*` points,
      vertex/triangle counts correct. `src/awd/`, `tools/dump_awd.py`.

## Phase 3 — Blender scene builder (headless) ✅
- [x] Build mesh from intermediate model (JSON) (verts/faces/uv); local geom + `matrix_world`.
- [x] Material node graph: diffuse→Base Color, normal→Normal Map, specular→Specular,
      glow→Emission. Missing channels are skipped.
- [x] `engine_/laserpoint_/light_position` → Empty (PLAIN_AXES) at the median origin,
      parented to the main body (`mesh_to_plain_axes.py` logic).
- [x] Export: `.glb` (default, embedded textures) + optional `.gltf` / `.obj`.
- [x] Away3D Y-up → Blender Z-up axis conversion (+90° X).
- [x] **Verification**: cubikon (cube), sibelon/devolarium/protegit (ship), kristallon
      (crystal) render correctly; textures are bound; empties are preserved as nodes in the glb.
      `src/blender/build_scene.py`, `tools/preview_glb.py`.

## Phase 4 — Orchestration & batch ✅
- [x] `python -m src.pipeline <mesh>|--all [--gltf --obj --no-blender]`.
- [x] ATF decode → PNG, AWD parse → JSON intermediate, headless Blender invocation.
- [x] Robustness to missing texture channels (only existing channels are bound).
- [x] **Verification**: all 11 meshes converted to glb with a single command (`out/<mesh>/`).
      Architecture: system-Python (numpy/imagecodecs) ↔ Blender (bpy+stdlib only) kept separate.

## Phase 5 — Render scripts integration ✅
A headless render module replacing the old 3 scripts (viewport-dependent, hardcoded, legacy API).
- [x] `src/blender/render_sprites.py` (Blender 5.x, headless): glb import → world
      HDRI + sun lighting → framing camera (ortho/persp) → turntable Z rotation →
      transparent RGBA frame render → collect the screen coordinates of the
      `engine_/laserpoint_` empties → raw JSON.
- [x] `src/render.py` (orchestrator): config (defaults+CLI override) → Blender →
      stable crop with PIL + coordinate origin adjustment → `<mesh>_Coords.json`.
- [x] All hardcoded values parametrized (`config.RENDER_DEFAULTS` + CLI):
      frames, resolution, samples, HDRI, camera angle (elevation/azimuth/ortho/fov/
      margin), sun, coord origin, crop padding.
- [x] `mesh_to_plain_axes.py` logic already integrated into the pipeline in Phase 3 (empties).
- [x] **Verification**: sibelon 512px turntable; all 5 points tracked correctly every frame
      (checked with overlay: laserpoint front, engine rear nozzle, light top); stable crop
      works. Lighting is headless reproducible (material-preview dependency removed).

## Render usage
```
python -m src.render sibelon                       # default turntable (72f, 256px, ortho)
python -m src.render sibelon --frames 32           # 32 frames = automatic 360/32° step (full turn)
python -m src.render sibelon --resolution 1024 --samples 128 --persp
python -m src.render sibelon --hdri city.exr --elevation 60 --azimuth 30 --margin 1.3
python -m src.render sibelon --deg-per-frame 5 --start-angle 90 --emission 0.4
python -m src.render --all
```
Frame count is free; the step is automatic via `total_degrees / frames` (no missing/extra turn).
HDRI: studio / city / courtyard / forest / interior / night / sunrise / sunset.
CLI groups: turntable (frames/total-degrees/deg-per-frame/start-angle/frame-start),
output-quality (resolution/samples/engine/view-transform/no-crop/no-transparent/origin),
camera-lighting (hdri/world-strength/sun-energy/emission/elevation/azimuth/persp/margin).

## Output structure (grouped, professional)
```
out/<mesh>/
  model/
    <mesh>.glb               # primary, self-contained (embedded textures)
    textures/                # decoded source PNGs
    gltf/  <mesh>.gltf + .bin + textures
    obj/   <mesh>.obj + .mtl
  sprites/
    <mesh>_1.png ... <mesh>_N.png   # 1-based naming
    <mesh>_Coords.json              # flat {point: [[x,y]|"OFF",...]}, engine_/laserpoint_ only
  work/                       # intermediate files (scene/cfg/meta json)
```
Quality: EEVEE samples 96, **Standard view transform** (correct texture colors, not AgX/Filmic).
