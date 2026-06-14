"""Project paths and pipeline configuration."""
from __future__ import annotations

import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MESHES_DIR = os.path.join(ROOT, "meshes")
TEXTURES_DIR = os.path.join(ROOT, "textures")
OUT_DIR = os.path.join(ROOT, "out")


# --- per-mesh output layout (grouped, professional) ----------------------
#   out/<mesh>/
#     model/    <mesh>.glb (+ .gltf/.obj) and textures/
#     sprites/  <mesh>_1.png ... and <mesh>_Coords.json
#     work/     intermediates (scene/cfg/meta json)
def mesh_dir(mesh: str) -> str:
    return os.path.join(OUT_DIR, mesh)


def model_dir(mesh: str) -> str:
    return os.path.join(OUT_DIR, mesh, "model")


def sprites_dir(mesh: str) -> str:
    return os.path.join(OUT_DIR, mesh, "sprites")


def work_dir(mesh: str) -> str:
    return os.path.join(OUT_DIR, mesh, "work")

# Blender 5.x (Steam). Override with the BLENDER env var if installed elsewhere.
BLENDER_EXE = os.environ.get(
    "BLENDER",
    r"C:\Program Files (x86)\Steam\steamapps\common\Blender\blender.exe",
)

BUILD_SCENE_SCRIPT = os.path.join(ROOT, "src", "blender", "build_scene.py")
RENDER_SCRIPT = os.path.join(ROOT, "src", "blender", "render_sprites.py")

# Default render settings. Override per-run via src.render CLI flags; the whole
# dict is passed to Blender as JSON so every knob is configurable in one place.
RENDER_DEFAULTS = {
    "frames": 72,              # turntable frame count (1 = single still)
    "total_degrees": 360.0,    # full sweep; per-frame step = total_degrees / frames
    "deg_per_frame": None,     # set to override the auto step (e.g. 5.0)
    "frame_start": 1,          # first frame number in filenames (<mesh>_1.png)
    "resolution": 256,         # square render, px (classic DarkOrbit sprite size)
    "engine": "BLENDER_EEVEE",
    "samples": 96,             # EEVEE TAA render samples
    "view_transform": "Standard",  # accurate texture colours (not AgX/Filmic)
    "film_transparent": True,  # RGBA output on transparent background

    "world_hdri": "studio.exr",  # bundled Blender studio light (world env)
    "world_strength": 0.8,

    "sun_energy": 1.5,
    "sun_angle": [50.0, 0.0, 40.0],   # degrees, XYZ euler
    "emission_strength": 0.6,  # glow/emission map multiplier (lower = subtler)

    "cam_elevation": 55.0,     # degrees above horizon (DarkOrbit ~ top-down)
    "cam_azimuth": -90.0,      # degrees around Z; -90 puts model +X at screen right
    "start_angle": 90.0,       # turntable rotation at frame 0 (front faces screen right)
    "cam_ortho": True,         # orthographic (sprite-style) vs perspective
    "cam_fov": 35.0,           # perspective FOV (used when cam_ortho=False)
    "cam_margin": 1.15,        # frame padding factor (>1 zooms out)

    "coord_prefixes": ["engine_", "laserpoint_"],  # which empties go in Coords.json
    "coord_origin": "TOP_LEFT",   # or BOTTOM_LEFT, for the points JSON
    "stable_crop": True,          # crop all frames to one global alpha bbox
    "crop_padding": 4,            # px around the crop
}

# Texture channels resolved by filename convention: <mesh>_<channel>_512.atf
CHANNELS = ("diffuse", "normal", "specular", "glow")
TEXTURE_SUFFIX = "_512"

# Scene-node name prefixes treated as reference points (exported as Empties in glb).
POINT_PREFIXES = ("engine_", "laserpoint_", "light_position")
# Subset whose screen positions are tracked into <mesh>_Coords.json.
# light_position stays an Empty in the glb but is NOT a render coord target.
COORD_PREFIXES = ("engine_", "laserpoint_")
