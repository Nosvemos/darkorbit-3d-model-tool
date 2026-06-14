# DarkOrbit 3D Model Tool — Overview

## Purpose
**Automatically** convert DarkOrbit game assets (`.awd` mesh + `.atf` texture) into modern 3D
formats (`.obj` / `.gltf` / `.glb`). Fully scriptify the existing manual workflow.

## Input Assets
- `meshes/*.awd` — Away3D AWD2 scene files (zlib-compressed body).
  Each file contains one main mesh (`main`) + helper points (`engine_*`, `laserpoint_*`).
- `textures/*.atf` — Adobe Texture Format (GPU texture container).
  Usually 4 channels per mesh: `diffuse`, `glow`, `normal`, `specular` (sometimes missing).

Current mesh list (11): cubikon, devolarium, kristallin, kristallon, lordakia,
lordakium, mordon, protegit, saimon, sibelon, sibelonit.

## Current Manual Workflow (to be automated)
1. **ATF2PNG** for `.atf` → `.png`.
2. **Prefab3D** to open `.awd` → `.obj` export.
3. **Blender**: import `.obj`, manually connect texture nodes in the Shading tab.
4. Export from Blender.

## Target Automated Workflow
```
.awd  ──parse──▶ geometry + node tree (main, engine_*, laserpoint_*) + material refs
.atf  ──decode─▶ .png (diffuse/normal/specular/glow)
                          │
                          ▼
              Build the scene with Blender (headless):
              - automatically connect material nodes (PBR)
              - engine_/laserpoint_ → Empty (PLAIN_AXES) reference points
                          │
                          ▼
              export: .glb / .gltf / .obj
```

## Critical Requirements
- **Helper points must not be lost**: `engine_*` and `laserpoint_*` reference points
  must be preserved (to be used later — render coordinate extraction, animation).
- **Textures must be connected correctly**: diffuse→base color, normal→normal map,
  specular→specular/roughness, glow→emission.
- **Must work in bulk**: the entire `meshes/` folder should be processable with a single command.

## Document Map
- `01_formats.md` — AWD and ATF binary format findings.
- `02_architecture.md` — pipeline architecture, modules, technical decisions.
- `03_roadmap.md` — task plan broken down into phases.
- `04_blender_scripts.md` — review of the existing 3 blender scripts.
- `05_open_questions.md` — decisions that need to be clarified.
