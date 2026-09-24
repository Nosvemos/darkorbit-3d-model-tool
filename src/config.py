"""Project paths and pipeline configuration."""
from __future__ import annotations

import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MESHES_DIR = os.path.join(ROOT, "meshes")
TEXTURES_DIR = os.path.join(ROOT, "textures")
FX_DIR = os.path.join(ROOT, "fx")
OUT_DIR = os.path.join(ROOT, "out")


def safe_output_name(name: str | None, fallback: str) -> str:
    """Return a safe file basename for exported artifacts.

    The source asset name is still used for lookup and folder layout; this only
    controls generated filenames such as .glb, sprite frames, and Coords.json.
    """
    raw = str(name or "").strip() or fallback
    raw = raw.replace("\\", "/").rsplit("/", 1)[-1]
    for ext in (".glb", ".gltf", ".obj", ".png", ".json", ".zip"):
        if raw.lower().endswith(ext):
            raw = raw[:-len(ext)]
            break
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
    cleaned = "".join(ch if ch in allowed else "_" for ch in raw).strip("._-")
    return cleaned or fallback


# --- per-mesh output layout (grouped, professional) ----------------------
#   out/<mesh>/
#     model/    <mesh>.glb (+ .gltf/.obj) and textures/
#     sprites/  <mesh>_1.png ... and <mesh>_Coords.json
#     work/     intermediates (scene/cfg/meta json)
def mesh_dir(mesh: str, base: str = OUT_DIR) -> str:
    return os.path.join(base, mesh)


def model_dir(mesh: str, base: str = OUT_DIR) -> str:
    return os.path.join(base, mesh, "model")


def sprites_dir(mesh: str, base: str = OUT_DIR) -> str:
    return os.path.join(base, mesh, "sprites")


def work_dir(mesh: str, base: str = OUT_DIR) -> str:
    return os.path.join(base, mesh, "work")


# FX meshes keep their existing layout under out/fx/<name>/; particle effects
# use a separate namespace so identical source stems cannot overwrite frames.
FX_OUT = os.path.join(OUT_DIR, "fx")
FX_EFFECTS_OUT = os.path.join(FX_OUT, "effects")


def effect_sprites_dir(name: str) -> str:
    return os.path.join(FX_EFFECTS_OUT, name, "sprites")

# Blender 5.x (Steam). Override with the BLENDER env var if installed elsewhere.
BLENDER_EXE = os.environ.get(
    "BLENDER",
    r"C:\Program Files (x86)\Steam\steamapps\common\Blender\blender.exe",
)

BUILD_SCENE_SCRIPT = os.path.join(ROOT, "src", "blender", "build_scene.py")
RENDER_SCRIPT = os.path.join(ROOT, "src", "blender", "render_sprites.py")
MODEL_BUILD_VERSION = 3  # bump when the generated GLB scene/material contract changes

# Named visual profiles applied before per-run overrides. The DarkOrbit map
# lighting values follow the default 3D map entries in the reference
# spacemap/graphics/maps-config.xml. Blender's energy/strength units are an
# approximation of Away3D's diffuse/ambient scalars; see docs/06_darkorbit_profile_reference.md.
RENDER_PROFILES = {
    "darkorbit": {
        "camera_model": "darkorbit",
        "light_model": "darkorbit",
        "use_hdri": False,
        "world_strength": 0.5,
        "world_color": "#ff855c",
        "sun_energy": 0.8,
        "sun_color": "#a3ffff",
        "specular_strength": 1.1,
        "sun_tilt": 100.0,
        "sun_pan": 35.0,
        "emission_strength": 1.0,
        "cam_ortho": False,
        "cam_fov": 30.0,
        "cam_tilt": 135.0,
        "cam_pan": 25.0,
        "cam_distance": None,
        "light_quality": "medium",
        "hero_light": False,
    },
    "studio": {
        "camera_model": "orbit",
        "light_model": "blender",
        "use_hdri": True,
        "world_hdri": "studio.exr",
        "world_strength": 0.8,
        "world_color": "#ffffff",
        "sun_energy": 1.5,
        "sun_color": "#ffffff",
        "specular_strength": 1.0,
        "sun_angle": [50.0, 0.0, 40.0],
        "emission_strength": 0.6,
        "cam_ortho": True,
        "cam_fov": 35.0,
        "cam_elevation": 55.0,
        "cam_azimuth": -90.0,
        "cam_distance": None,
        "light_quality": "medium",
        "hero_light": False,
    },
}

# Default render settings. Override per-run via src.render CLI flags; the whole
# dict is passed to Blender as JSON so every knob is configurable in one place.
RENDER_DEFAULTS = {
    "profile": "darkorbit",
    # ship  -> track engine_/laserpoint_ points, write <mesh>_Coords.json
    # item  -> plain render (ore, items like lf4, ...), no point tracking / no JSON
    # auto  -> ship behaviour if any point empties exist, else item
    "mode": "auto",
    "quality": "medium",       # extra_low, low, medium, high, extra_high, custom
    "frames": 72,              # turntable frame count (1 = single still)
    "total_degrees": 360.0,    # full sweep; per-frame step = total_degrees / frames
    "deg_per_frame": None,     # set to override the auto step (e.g. 5.0)
    "frame_start": 1,          # first frame number in filenames (<mesh>_1.png)
    "resolution": 256,         # square render, px (classic DarkOrbit sprite size)
    "engine": "BLENDER_EEVEE",
    "samples": 96,             # EEVEE TAA render samples
    "view_transform": "Standard",  # accurate texture colours (not AgX/Filmic)
    "film_transparent": True,  # RGBA output on transparent background

    "rotation": True,          # spin the model around Z (turntable)
    "anim_frame_start": 1,     # start frame for animation clip
    "anim_frame_end": None,    # end frame for animation clip (None = end of clip)

    "camera_model": "darkorbit",  # darkorbit Observer3D tilt/pan, or orbit
    "light_model": "darkorbit",   # darkorbit LightSettings tilt/pan, or blender
    "use_hdri": False,
    "world_hdri": "studio.exr",   # bundled Blender studio light (when use_hdri)
    "world_strength": 0.5,         # map ambient=0.5 (Blender strength approximation)
    "world_color": "#ff855c",     # map ambientColor=0xFF855C

    "sun_energy": 0.8,             # map diffuse=0.8 (Blender energy approximation)
    "sun_color": "#a3ffff",       # map color=0xA3FFFF
    "specular_strength": 1.1,     # map specular=1.1 (Away3D highlight multiplier)
    "sun_angle": [50.0, 0.0, 40.0],   # degrees, XYZ euler
    "sun_tilt": 100.0,         # DarkOrbit Settings3D.sunLight.directionTilt
    "sun_pan": 35.0,           # DarkOrbit Settings3D.sunLight.directionPan
    "light_quality": "medium", # low: no sun; medium: sun; high: sun + hero point
    "hero_light": False,       # optional high-quality hero-position point light
    "hero_light_color": "#2e7aff",
    "hero_light_energy": 0.6,
    "hero_light_radius": 450.0,
    "emission_strength": 1.0,  # GlowMethod shaderParams.glow default

    "cam_elevation": 55.0,     # orbit fallback: degrees above horizon
    "cam_azimuth": -90.0,      # orbit fallback: degrees around Z
    "cam_tilt": 135.0,         # DarkOrbit Observer3D.start_cameraTilt
    "cam_pan": 25.0,           # CameraManager3D.START_PAN on 3D maps
    "cam_distance": None,      # None = fit object; set 1740 for raw Observer3D distance
    "start_angle": 90.0,       # turntable rotation at frame 0 (front faces screen right)
    "cam_ortho": False,        # MapView3D uses PerspectiveLens, not ortho
    "cam_fov": 30.0,           # PerspectiveLens(30)
    "cam_margin": 1.15,        # frame padding factor (>1 zooms out)

    "coord_prefixes": ["engine_", "laserpoint_"],  # which empties go in Coords.json
    "coord_origin": "TOP_LEFT",   # or BOTTOM_LEFT, for the points JSON
    "stable_crop": True,          # crop all frames to one global alpha bbox
    "crop_padding": 4,            # px around the crop
    "hide_objects": [],           # list of object names to hide/exclude
    "crop_align": None,           # align crop bounds with a reference metadata name/file
}

# Texture channels resolved by filename convention: <mesh>_<channel>_512.atf
CHANNELS = ("diffuse", "normal", "specular", "glow", "alpha", "ao", "gal")
TEXTURE_SUFFIX = "_512"

# Scene-node name prefixes treated as reference points (exported as Empties in glb).
POINT_PREFIXES = ("engine_", "laserpoint_", "light_position")
# Subset whose screen positions are tracked into <mesh>_Coords.json.
# light_position stays an Empty in the glb but is NOT a render coord target.
COORD_PREFIXES = ("engine_", "laserpoint_")

QUALITY_PRESETS = {
    "extra_low": {"resolution": 128, "samples": 16},
    "low": {"resolution": 256, "samples": 32},
    "medium": {"resolution": 256, "samples": 96},
    "high": {"resolution": 512, "samples": 128},
    "extra_high": {"resolution": 1024, "samples": 256},
}
