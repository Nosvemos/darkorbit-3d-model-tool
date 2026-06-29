# Open Questions / Decisions to Clarify

## ✅ Resolved Decisions
1. **Blender path**: `C:\Program Files (x86)\Steam\steamapps\common\Blender\blender.exe`
   — **Blender 5.1.2** (Steam, build 2026-05-19).
   ⚠️ The current blender scripts use the old API (`BLENDER_EEVEE` → changed in 5.x,
   glTF export operator names). To be adapted to the 5.x API in Phase 3/5.
2. **Primary output**: **`.glb`** (embedded texture, empties+hierarchy preserved).
   `.gltf` and `.obj` are produced via an optional flag.
3. **ATF decode**: **Our own pure-Python decoder** (DXT + LZMA). No external tool dependency.

## ✅ Resolved Remaining Decisions (Post-Launch)

4. **Empties parent behavior**:
   Confirmed. `engine_*` and `laserpoint_*` are parented under the main object as Empty axes and are preserved in glTF. This behavior is correct and verified.

5. **Texture resolution / channel mapping**:
   Specular channel is successfully mapped to PBR Specular/Roughness and verified visually.

6. **temp_lzma_*.bin**:
   Leftover temp files were deleted. The current pipeline performs all decoding in memory/isolated streams without creating persistent temporary binary files.
