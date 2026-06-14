# Open Questions / Decisions to Clarify

## ✅ Resolved Decisions
1. **Blender path**: `C:\Program Files (x86)\Steam\steamapps\common\Blender\blender.exe`
   — **Blender 5.1.2** (Steam, build 2026-05-19).
   ⚠️ The current blender scripts use the old API (`BLENDER_EEVEE` → changed in 5.x,
   glTF export operator names). To be adapted to the 5.x API in Phase 3/5.
2. **Primary output**: **`.glb`** (embedded texture, empties+hierarchy preserved).
   `.gltf` and `.obj` are produced via an optional flag.
3. **ATF decode**: **Our own pure-Python decoder** (DXT + LZMA). No external tool dependency.

## Remaining / points to be clarified after the first output

## 4. Empties parent behavior
`engine_/laserpoint_` → Empty + parented under `main` (like the current script).
Empties are preserved as nodes in glTF export. Confirmation: is this behavior correct?

## 5. Texture resolution / channel mapping
File names `_512` → 512×512. The specular channel may need to be inverted into roughness
(specular workflow vs PBR roughness). To be adjusted via visual inspection after the first output.

## 6. temp_lzma_*.bin
Can the 5 temporary files in `textures/` be deleted? (leftover from a previous ATF decode attempt)
