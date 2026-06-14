"""Project paths and pipeline configuration."""
from __future__ import annotations

import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MESHES_DIR = os.path.join(ROOT, "meshes")
TEXTURES_DIR = os.path.join(ROOT, "textures")
OUT_DIR = os.path.join(ROOT, "out")

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
    "deg_per_frame": 5.0,      # 72 * 5 = 360 degrees
    "resolution": 256,         # square render, px (classic DarkOrbit sprite size)
    "engine": "BLENDER_EEVEE",
    "samples": 64,             # EEVEE TAA render samples
    "film_transparent": True,  # RGBA output on transparent background

    "world_hdri": "studio.exr",  # bundled Blender studio light (world env)
    "world_strength": 1.2,

    "sun_energy": 3.0,
    "sun_angle": [50.0, 0.0, 40.0],   # degrees, XYZ euler

    "cam_elevation": 55.0,     # degrees above horizon (DarkOrbit ~ top-down)
    "cam_azimuth": 45.0,       # degrees around Z
    "cam_ortho": True,         # orthographic (sprite-style) vs perspective
    "cam_fov": 35.0,           # perspective FOV (used when cam_ortho=False)
    "cam_margin": 1.15,        # frame padding factor (>1 zooms out)

    "coord_origin": "TOP_LEFT",   # or BOTTOM_LEFT, for the points JSON
    "stable_crop": True,          # crop all frames to one global alpha bbox
    "crop_padding": 4,            # px around the crop
}

# Texture channels resolved by filename convention: <mesh>_<channel>_512.atf
CHANNELS = ("diffuse", "normal", "specular", "glow")
TEXTURE_SUFFIX = "_512"

# Scene-node name prefixes treated as reference points (exported as Empties).
POINT_PREFIXES = ("engine_", "laserpoint_", "light_position")
