# Review of Existing Blender Scripts

There are 3 scripts. All of them are written to be run manually from the Blender Text Editor,
with some values hardcoded. They should be parameterized when integrated into the pipeline.

## 1. `mesh_to_plain_axes.py`
**What it does**: Deletes MESH objects with the `engine_*` and `laserpoint_*` prefixes, and in their place
creates a `PLAIN_AXES` Empty at the same world location, then parents it to the `main` object.
- Moves the origin to the geometry (`ORIGIN_GEOMETRY`/`MEDIAN`) → correct center.
- Backs up `matrix_world` and reapplies it after parenting → location is preserved.

**Role in the pipeline**: The core logic of Phase 3. This is the step that turns helper points into references.
`build_scene.py` will use this directly.
**Note**: If these objects are already meshes at import time, the logic applies exactly.

## 2. `rotation_animation.py`
**What it does**: Adds a 5° rotation keyframe per frame on the Z axis to the active object
(frame 1→72, ~360° total). Clears the existing animation.

**Role in the pipeline**: Phase 5. The turntable animation before rendering.
**Improvement**: `start/end/deg_per_frame` and the target object should be parameters;
select by name (`main`) instead of `bpy.context.active_object`.

## 3. `2d_to_3d_render.py`
**What it does**: The most comprehensive script. For the `main` + `engine_/laserpoint_` targets:
- Renders frame 1→72 (Eevee, RGBA, transparent film, 200×200).
- Moves the Material Preview look (studio HDRI + light checkboxes) into the Scene World
  (`sync_from_material_preview`) → the viewport and render match.
- For each frame, collects the camera-space 2D coordinates of the target points.
- Computes a **global stable crop** for all frames (alpha bbox + point padding).
- Crops the frames and adjusts the coordinates relative to the crop.
- Writes `<FILE_NAME>_Coords.json` (sprite + point coordinates).

**Role in the pipeline**: The main output of Phase 5 — generating a 2D sprite + point coordinates
from the 3D model. A DarkOrbit-style sprite/animation pipeline.
**Hardcoded values** (to be parameterized): `OUTPUT_DIR="C:/RenderOutput/"`,
`FILE_NAME="goliath"`, `START/END_FRAME`, `RENDER_W/H`, `COORD_ORIGIN`, render engine.
**Dependency**: PIL (available), an active 3D Viewport (`sync_from_material_preview` does not
work in headless mode → for headless you need to set up the world/light directly).

## Common observations
- The `engine_`/`laserpoint_` prefix convention is consistent across the 3 scripts + the AWD node names
  → the pipeline can rely on this convention.
- The `main` main-object name is a fixed assumption → the AWD parser should validate/guarantee this.
- The render scripts depend on the viewport context; for full automation (cron/headless),
  a context-free version of the world+light setup is needed (Phase 5 work).
