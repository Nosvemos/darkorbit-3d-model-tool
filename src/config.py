"""Project paths and pipeline configuration."""
from __future__ import annotations

import os
from copy import deepcopy

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
    # Accept either a stem or a source/output filename. Repeatedly remove
    # known suffixes so inputs such as ``ship.awd.glb`` still resolve to the
    # same export stem as ``ship``.
    extensions = (".glb", ".gltf", ".obj", ".png", ".json", ".zip",
                  ".awd", ".atf", ".awp")
    while True:
        matched = next((ext for ext in extensions if raw.lower().endswith(ext)), None)
        if not matched:
            break
        raw = raw[:-len(matched)]
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
MODEL_BUILD_VERSION = 10  # appearance data and scene-bounds-aware mesh effects

# PET appearance presets reconstructed from reference/client ships.xml. These
# designs share pet-15 geometry and the ordinary PET texture set; their game
# shader uses the bundled RimLightMethod MIX equations and OutlinePass.
PET_DESIGNS = {
    "pet-frozen": {
        "label": "Frozen PET",
        "geometry": "pet-15",
        "visual_size": 1.1,
        "textures": {
            "diffuse": "pet_diffuse_512",
            "normal": "pet_normal_512",
            "specular": "pet_specular_512",
            "glow": "pet_glow_512",
        },
        "rim_color": "#33CCFF",
        "rim_strength": 2.0,
        "rim_power": 2.0,
        "outline_size": 1.5,
        "particles": [
            {"name": "frost_ship_trail", "scale": [0.6, 0.6, 0.6], "position": [0, 0, 0]},
            {"name": "ice_cloud", "scale": [0.8, 0.2, 0.8], "position": [0, -30, 0]},
        ],
    },
    "pet-inferno": {
        "label": "Inferno PET",
        "geometry": "pet-15",
        "visual_size": 1.4,
        "textures": {
            "diffuse": "pet_diffuse_512",
            "normal": "pet_normal_512",
            "specular": "pet_specular_512",
            "glow": "pet_glow_512",
        },
        "rim_color": "#FF0000",
        "rim_strength": 1.0,
        "rim_power": 1.0,
        "outline_size": 0.25,
        "particles": [
            {"name": "fire_trail", "scale": [1.5, 1.5, 1.5], "position": [0, 0, 0]},
        ],
    },
}

# Source recipes and explicitly labelled custom appearances share one registry.
DESIGNS = deepcopy(PET_DESIGNS)
for preset in DESIGNS.values():
    preset['meshes'] = [f'pet-{level}' for level in range(1, 16)]
    preset['source'] = 'ships.xml'

DESIGNS['pet-legend'] = deepcopy(DESIGNS['pet-frozen'])
DESIGNS['pet-legend'].update(label='Legend PET (custom)', source='custom yellow PET variant',
                            rim_color='#FFD135', rim_strength=2.0, outline_size=0.5)
for recipe in DESIGNS['pet-legend']['particles']:
    recipe['tint'] = [1.0, 0.70, 0.08]

# Each channel override follows PrefabMaterialManager.assembleTextureResKey.
# Diminisher frost replaces the whole texture stem; it has no normal/specular ATF.
for ship, cloud, fire, scale in (
        ('solace', 2, 2, .85), ('sentinel', 3, 1.5, .85),
        ('venom', 2, 2, .85), ('spectrum', 1.5, 1.5, .85),
        ('diminisher', 1.5, 2, .7)):
    geometry = 'goliath-' + ship
    for style in ('frozen', 'inferno'):
        preset = deepcopy(DESIGNS['pet-' + style])
        preset.update(label=ship.title() + ' ' + style.title(), geometry=geometry,
                      meshes=[geometry], mesh_scale=scale, visual_size=1.4 if ship in ('spectrum', 'diminisher') else 1.7,
                      textures={}, source='ships.xml')
        if style == 'frozen':
            preset['particles'] = [
                {'name':'frost_ship_trail', 'scale':[1,1,1], 'position':[0,0,0]},
                {'name':'ice_cloud', 'scale':[cloud,.5,cloud], 'position':[0,-30,0]}]
            if ship in ('solace', 'diminisher'):
                preset['textures'] = {c:f'{ship}-frost_{c}_512' for c in ('diffuse','glow')}
            if ship == 'diminisher':
                preset['textures'].update(normal='none', specular='none')
        else:
            preset['particles'] = [{'name':'fire_trail', 'scale':[fire]*3, 'position':[0,0,0]}]
            if ship == 'solace':
                preset['textures']['diffuse'] = 'goliath-solace-blaze_diffuse_512'
        DESIGNS[ship + '-' + style] = preset
    legend_stem = {'sentinel':'goliath-sentinel_design_legend',
                   'spectrum':'spectrum-design-legend',
                   'diminisher':'ship_diminisher_design_legend'}.get(ship)
    if legend_stem:
        preset = deepcopy(DESIGNS[ship + '-inferno'])
        channels = ('diffuse','glow','specular') if ship == 'sentinel' else ('diffuse','glow')
        preset.update(label=ship.title() + ' Legend', rim_color='#FFD135', rim_strength=9.,
                      rim_power=2.5, outline_size=0., particles=[],
                      textures={c:f'{legend_stem}_{c}_512' for c in channels})
        DESIGNS[ship + '-legend'] = preset


# Keep source recipes selectable while making the everyday presets texture-independent.
for key, preset in list(DESIGNS.items()):
    if preset['source'] == 'ships.xml':
        original = deepcopy(preset)
        original['label'] += ' (source)'
        DESIGNS[key + '-source'] = original
for family in ('pet', 'solace', 'spectrum', 'sentinel', 'diminisher', 'venom'):
    frozen = deepcopy(DESIGNS[family + '-frozen'])
    for style, color, strength, tint in (
            ('frozen', '#33CCFF', 2.0, .35),
            ('inferno', '#FF0000', 1.5, .55),
            ('legend', '#FFD135', 7.0, .70)):
        preset = deepcopy(frozen)
        preset.update(label=family.title() + ' ' + style.title() + ' (tunable)',
                      source='custom base-texture preset', rim_color=color,
                      rim_strength=strength, rim_power={"frozen":2., "inferno":1., "legend":2.5}[style], outline_size=.4,
                      body_tint=tint, particle_intensity=1., particle_scale=1.)
        if family != 'pet':
            preset['textures'] = {}
        rgb = [int(color[i:i+2],16)/255 for i in (1,3,5)]
        for recipe in preset['particles']:
            recipe['tint'] = rgb
            recipe['center_on_mesh'] = True
        DESIGNS[family + '-' + style] = preset

DEFAULT_APPEARANCE = {
    'rim_color': '#FFFFFF', 'rim_strength': 0., 'rim_power': 2.,
    'outline_size': 0., 'body_tint': 0., 'particle_color': None,
    'particle_intensity': 1., 'particle_scale': 1.,
}

# These are geometry-independent effect recipes. scale_to_mesh makes the
# particle field adapt to the selected AWD's bounds at render time; each mesh
# can still use a regular design preset for its own geometry and textures.
MESH_EFFECT_PRESETS = {
    'frost': {
        'label': 'Frost', 'rim_color': '#33CCFF', 'rim_strength': 2.,
        'rim_power': 2., 'outline_size': 0., 'body_tint': .35,
        'particle_color': '#33CCFF', 'particle_intensity': 1.,
        'particle_scale': 1.,
        'particles': [
            {'name': 'frost_ship_trail', 'scale': [.7, .7, .7],
             'position': [0, 0, 0], 'center_on_mesh': True,
             'scale_to_mesh': True},
            {'name': 'ice_cloud', 'scale': [1.3, .42, 1.3],
             'position': [0, 0, 0], 'center_on_mesh': True,
             'scale_to_mesh': True, 'opacity': .72},
        ],
    },
    'inferno': {
        'label': 'Inferno', 'rim_color': '#FF210C', 'rim_strength': 2.2,
        'rim_power': 1.15, 'outline_size': 0., 'body_tint': .38,
        'particle_color': '#F21B08', 'particle_intensity': 1.,
        'particle_scale': 1.,
        'particles': [
            {'name': 'fire_trail', 'scale': [.78, .78, .78],
             'position': [0, 0, 0], 'center_on_mesh': True,
             'scale_to_mesh': True},
            {'name': 'ice_cloud', 'scale': [.68, .32, .68],
             'position': [0, 0, 0], 'center_on_mesh': True,
             'scale_to_mesh': True, 'tint': [1., .1, .025], 'opacity': .52},
        ],
    },
    'legend': {
        'label': 'Legend', 'rim_color': '#FFD135', 'rim_strength': 4.5,
        'rim_power': 2.5, 'outline_size': 0., 'body_tint': .48,
        'particle_color': '#FFD135', 'particle_intensity': .9,
        'particle_scale': .9,
        'particles': [
            {'name': 'fire_trail', 'scale': [.66, .66, .66],
             'position': [0, 0, 0], 'center_on_mesh': True,
             'scale_to_mesh': True},
            {'name': 'ice_cloud', 'scale': [.72, .32, .72],
             'position': [0, 0, 0], 'center_on_mesh': True,
             'scale_to_mesh': True, 'opacity': .38},
        ],
    },
}
EFFECT_PRESET_CHOICES = ('auto', 'none', *MESH_EFFECT_PRESETS)


def resolve_effect_preset(effect_preset='auto', design=None):
    """Resolve auto/design, no-particle, or mesh-wide effect settings."""
    key = str(effect_preset or 'auto').strip().lower()
    if key == 'auto':
        return DESIGNS.get(design) if design else None
    if key == 'none':
        return None
    if key in MESH_EFFECT_PRESETS:
        return MESH_EFFECT_PRESETS[key]
    raise ValueError(f"unknown effect preset '{effect_preset}' (choose "
                     + ', '.join(EFFECT_PRESET_CHOICES) + ')')


def appearance_ui_defaults(preset=None):
    """Map a resolved appearance preset to the browser/CLI control names."""
    source = preset or DEFAULT_APPEARANCE
    rim_color = source.get('rim_color', DEFAULT_APPEARANCE['rim_color'])
    return {
        'design_color': rim_color,
        'rim_strength': source.get('rim_strength', DEFAULT_APPEARANCE['rim_strength']),
        'rim_power': source.get('rim_power', DEFAULT_APPEARANCE['rim_power']),
        'body_tint': source.get('body_tint', DEFAULT_APPEARANCE['body_tint']),
        'particle_color': source.get('particle_color') or rim_color,
        'particle_intensity': source.get('particle_intensity', DEFAULT_APPEARANCE['particle_intensity']),
        'particle_scale': source.get('particle_scale', DEFAULT_APPEARANCE['particle_scale']),
    }


APPEARANCE_KEYS = ('design_color', 'rim_strength', 'rim_power', 'body_tint',
                   'particle_color', 'particle_intensity', 'particle_scale')


def appearance_settings(preset, cfg):
    import math
    import re
    preset = preset or DEFAULT_APPEARANCE
    result = {k:preset.get(k, DEFAULT_APPEARANCE[k])
              for k in ('rim_color','rim_strength','rim_power','outline_size')}
    result['body_tint'] = preset.get('body_tint', 0.)
    result['particle_intensity'] = preset.get('particle_intensity', 1.)
    result['particle_scale'] = preset.get('particle_scale', 1.)
    result['particle_color'] = preset.get('particle_color')
    for source, target in (('design_color','rim_color'), ('particle_color','particle_color')):
        value = cfg.get(source)
        if value not in (None, ''):
            if not re.fullmatch(r'#[0-9a-fA-F]{6}', str(value)):
                raise ValueError(f'{source} must be #RRGGBB')
            result[target] = value
    if result['particle_color'] is None and preset.get('body_tint') is not None:
        result['particle_color'] = result['rim_color']
    for key, lo, hi in (('rim_strength',0,12), ('rim_power',.1,12), ('body_tint',0,1),
                        ('particle_intensity',0,5), ('particle_scale',.1,4)):
        value = cfg.get(key)
        if value not in (None, ''):
            value = float(value)
            if not math.isfinite(value) or not lo <= value <= hi:
                raise ValueError(f'{key} must be between {lo} and {hi}')
            result[key] = value
    return result


def resolve_appearance_settings(effect_preset='auto', design=None, overrides=None):
    """Resolve preset appearance plus user overrides, or return ``None``."""
    preset = resolve_effect_preset(effect_preset, design)
    overrides = overrides or {}
    has_overrides = any(value not in (None, '') for value in overrides.values())
    if preset is None and not has_overrides:
        return None, None
    return preset, appearance_settings(preset, overrides)


def design_particles(preset, appearance, mesh_radius=100.):
    if not preset:
        return []
    recipes = deepcopy(preset['particles'])
    mesh_scale = effect_scale_for_radius(mesh_radius)
    for recipe in recipes:
        automatic_scale = mesh_scale if recipe.get('scale_to_mesh') else 1.
        recipe['scale'] = [v*appearance['particle_scale']*automatic_scale
                           for v in recipe['scale']]
        recipe['opacity'] = recipe.get('opacity',1.)*appearance['particle_intensity']
        color = appearance['particle_color']
        if color:
            recipe['tint'] = [int(color[i:i+2],16)/255 for i in (1,3,5)]
        recipe.pop('scale_to_mesh', None)
    return recipes


def effect_scale_for_radius(mesh_radius):
    """Scale universal particle recipes against a representative 100-unit hull."""
    import math
    try:
        radius = float(mesh_radius)
    except (TypeError, ValueError):
        return 1.
    if not math.isfinite(radius) or radius <= 0:
        return 1.
    return max(.15, min(3., radius / 100.))


def designs_for(mesh):
    return {key: value for key, value in DESIGNS.items() if mesh.lower() in value['meshes']}


# Named visual profiles applied before per-run overrides. The DarkOrbit map
# lighting values follow the default 3D map entries in the reference
# spacemap/graphics/maps-config.xml, map 1-1. Stage3D shader arithmetic uses
# these scalars directly; see docs/06_darkorbit_profile_reference.md.
RENDER_PROFILES = {
    "darkorbit": {
        "camera_model": "darkorbit",
        "light_model": "darkorbit",
        "use_hdri": False,
        "world_strength": 0.5,
        "world_color": "#ff855c",
        "ambient_strength": 0.5,
        "ambient_color": "#ff855c",
        "sun_energy": 0.8,
        "sun_color": "#a3ffff",
        "specular_strength": 1.1,
        "view_transform": "Raw",
        "sun_tilt": 100.0,
        "sun_pan": 35.0,
        "emission_strength": 1.0,
        "cam_ortho": False,
        "cam_fov": 30.0,
        "cam_tilt": 135.0,
        "cam_pan": 25.0,
        "cam_distance": 1740.0,
        "camera_framing": "sprite",
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
    "world_strength": 0.5,         # background strength (not material ambient)
    "world_color": "#ff855c",     # map ambientColor=0xFF855C
    "ambient_strength": 0.5,       # Away3D ambient scalar
    "ambient_color": "#ffffff",    # material fill color; profile-specific

    "sun_energy": 0.8,             # Away3D diffuse scalar in darkorbit mode
    "sun_color": "#a3ffff",       # map color=0xA3FFFF
    "specular_strength": 1.1,     # map specular=1.1 (Away3D highlight multiplier)
    "sun_angle": [50.0, 0.0, 40.0],   # degrees, XYZ euler
    "sun_tilt": 100.0,         # DarkOrbit Settings3D.sunLight.directionTilt
    "sun_pan": 35.0,           # DarkOrbit Settings3D.sunLight.directionPan
    "light_quality": "medium", # low: no sun; medium: sun; high: sun + hero point
    "hero_light": False,       # optional high-quality hero-position point light
    "hero_light_color": "#2e7dff",
    "hero_light_energy": 0.6,
    "hero_light_radius": 450.0,
    "emission_strength": 1.0,  # GlowMethod shaderParams.glow default

    "cam_elevation": 55.0,     # orbit fallback: degrees above horizon
    "cam_azimuth": -90.0,      # orbit fallback: degrees around Z
    "cam_tilt": 135.0,         # DarkOrbit Observer3D.start_cameraTilt
    "cam_pan": 25.0,           # CameraManager3D.START_PAN on 3D maps
    "cam_distance": None,      # None = fit object; set 1740 for raw Observer3D distance
    "camera_framing": "sprite", # crop projection at fixed distance; native = full game FOV
    "cam_zoom": 1.0,
    "effect_time": 2.0,         # seconds after activation, avoids an empty first frame
    "effect_fps": 30.0,
    "design_particles": True,
    **{key: None for key in APPEARANCE_KEYS},
    "effect_style": "softened",  # softened quads / warm scattered cloud, or source
    "start_angle": 90.0,        # reflected Ship3D rotationY = heading - 90
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
