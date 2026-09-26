"""Headless turntable sprite renderer (Blender 5.x).

Run via:
    blender --background --python src/blender/render_sprites.py -- \
        <model.glb> <out_dir> <config.json>

Imports a glb produced by the pipeline, sets up world-HDRI lighting + a sun +
a framing camera, spins the whole model around Z over N frames, renders each
frame on a transparent background, and tracks the screen-space position of the
engine_/laserpoint_ empties. Frames are cropped to one global alpha bbox and a
<name>_Coords.json with the per-frame point pixel positions is written.

This is the automated, headless successor to the old viewport-bound
2d_to_3d_render.py — no Material-Preview context needed; lighting is set up
explicitly so renders are reproducible from the command line.

Blender renders full-resolution frames and writes raw per-frame point pixel
coordinates; the stable crop + coordinate adjustment happens afterwards in
src/render.py (system Python + Pillow), so this script needs only bpy + stdlib.
"""
import json
import math
import os
import sys

import bpy
import bpy_extras
from mathutils import Vector

POINT_PREFIXES = ("engine_", "laserpoint_", "light_position")


def args_after_dashes():
    return sys.argv[sys.argv.index("--") + 1:]


def scene_bounds():
    """World-space bounding box of all mesh objects -> (center, radius)."""
    mn = Vector((1e18, 1e18, 1e18))
    mx = -mn
    for o in bpy.context.scene.objects:
        if o.type != "MESH" or o.hide_render:
            continue
        for corner in o.bound_box:
            w = o.matrix_world @ Vector(corner)
            mn = Vector(map(min, mn, w))
            mx = Vector(map(max, mx, w))
    center = (mn + mx) / 2
    radius = (mx - mn).length / 2 or 1.0
    return center, radius, mn, mx


def parent_under_root(center):
    """Parent every top-level object under a new empty at `center` so the whole
    model (meshes + reference empties) can be spun as one."""
    root = bpy.data.objects.new("turntable_root", None)
    bpy.context.scene.collection.objects.link(root)
    root.location = center
    bpy.context.view_layer.update()
    for o in list(bpy.context.scene.objects):
        if o is root or o.parent:
            continue
        o.parent = root
        o.matrix_parent_inverse = root.matrix_world.inverted()
    return root


def hex_to_rgb(hex_str: str) -> list[float]:
    hex_str = hex_str.lstrip('#')
    return [int(hex_str[i:i+2], 16) / 255.0 for i in (0, 2, 4)]


def away_to_blender(v: Vector) -> Vector:
    """Convert an Away3D Y-up vector to the Blender Z-up scene built by us."""
    return Vector((v.x, v.z, v.y))


def darkorbit_light_direction(tilt, pan) -> Vector:
    """LightSettings.apply: ExtMath.tiltPan2Vector(tilt, pan, -1)."""
    t = math.radians(tilt)
    p = math.radians(pan)
    away = Vector((-math.sin(t) * math.sin(p),
                   -math.sin(t) * math.cos(p),
                   -math.cos(t)))
    return away_to_blender(away).normalized()


def darkorbit_camera_direction(tilt, pan) -> Vector:
    """Observer3D.validate position minus lookAt; no extra pan rotation."""
    t = math.radians(tilt)
    p = math.radians(pan)
    away = Vector((math.sin(t) * math.sin(p),
                   -math.cos(t),
                   -math.sin(t) * math.cos(p)))
    return away_to_blender(away).normalized()


def fit_camera_distance(radius, fov, margin):
    half = math.radians(max(1.0, min(float(fov), 179.0)) * 0.5)
    return max(radius * float(margin) / max(math.sin(half), 0.001),
               radius * 2.0)


def setup_world(cfg):
    hdri_dir = bpy.utils.system_resource("DATAFILES", path="studiolights/world")
    hdri = cfg.get("world_hdri") or ""
    path = os.path.join(hdri_dir, hdri)
    world = bpy.data.worlds.new("World")
    bpy.context.scene.world = world
    if world.node_tree is None:           # use_nodes deprecated in Blender 6.0
        world.use_nodes = True
    nt = world.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputWorld")
    bg = nt.nodes.new("ShaderNodeBackground")
    bg.inputs["Strength"].default_value = cfg["world_strength"]
    nt.links.new(bg.outputs["Background"], out.inputs["Surface"])

    world_color_hex = cfg.get("world_color", "#ffffff")
    color_rgb = hex_to_rgb(world_color_hex)

    if cfg.get("use_hdri", True) and hdri and os.path.exists(path):
        env = nt.nodes.new("ShaderNodeTexEnvironment")
        env.image = bpy.data.images.load(path, check_existing=True)
        # Try to multiply the texture with the color using Mix node
        try:
            mix = nt.nodes.new("ShaderNodeMix")
            mix.data_type = 'RGBA'
            mix.blend_type = 'MULTIPLY'
            mix.inputs["Factor"].default_value = 1.0
            nt.links.new(env.outputs["Color"], mix.inputs["A"])
            mix.inputs["B"].default_value = color_rgb + [1.0]
            nt.links.new(mix.outputs["Result"], bg.inputs["Color"])
        except Exception:
            try:
                mix = nt.nodes.new("ShaderNodeMixRGB")
                mix.blend_type = 'MULTIPLY'
                mix.inputs["Fac"].default_value = 1.0
                nt.links.new(env.outputs["Color"], mix.inputs["Color1"])
                mix.inputs["Color2"].default_value = color_rgb + [1.0]
                nt.links.new(mix.outputs["Color"], bg.inputs["Color"])
            except Exception:
                # Fallback to direct connection if both mix nodes fail
                nt.links.new(env.outputs["Color"], bg.inputs["Color"])
    else:
        bg.inputs["Color"].default_value = color_rgb + [1.0]


def setup_sun(cfg):
    if cfg.get("light_quality") == "low":
        return None
    data = bpy.data.lights.new("Sun", "SUN")
    data.energy = cfg["sun_energy"]
    sun_color_hex = cfg.get("sun_color", "#ffffff")
    data.color = hex_to_rgb(sun_color_hex)
    if hasattr(data, "use_shadow"):
        data.use_shadow = False
    sun = bpy.data.objects.new("Sun", data)
    if cfg.get("light_model") == "darkorbit":
        direction = darkorbit_light_direction(cfg.get("sun_tilt", 100.0),
                                              cfg.get("sun_pan", 35.0))
        sun.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    else:
        sun.rotation_euler = [math.radians(a) for a in cfg["sun_angle"]]
    bpy.context.scene.collection.objects.link(sun)
    return sun


def setup_hero_light(cfg, center, radius):
    if not (cfg.get("hero_light") or cfg.get("light_quality") == "high"):
        return None
    data = bpy.data.lights.new("HeroPositionLight", "POINT")
    data.color = hex_to_rgb(cfg.get("hero_light_color", "#2e7aff"))
    data.energy = float(cfg.get("hero_light_energy", 0.6)) * 250.0
    if hasattr(data, "use_shadow"):
        data.use_shadow = False
    if hasattr(data, "use_custom_distance"):
        data.use_custom_distance = True
        data.cutoff_distance = max(float(cfg.get("hero_light_radius", 450.0)),
                                   radius * 2.0)
    light = bpy.data.objects.new("HeroPositionLight", data)
    light.location = center
    bpy.context.scene.collection.objects.link(light)
    return light


def setup_camera(cfg, center, radius):
    if cfg.get("camera_model") == "darkorbit":
        zoom = max(1.0, min(3.0, float(cfg.get("cam_zoom", 1))))
        tilt = cfg.get("cam_tilt", 135.0) - (zoom - 1) * 10
        direction = darkorbit_camera_direction(tilt,
                                               cfg.get("cam_pan", 25.0))
    else:
        el = math.radians(cfg["cam_elevation"])
        az = math.radians(cfg["cam_azimuth"])
        direction = Vector((math.cos(el) * math.cos(az),
                            math.cos(el) * math.sin(az),
                            math.sin(el)))
    cam_data = bpy.data.cameras.new("Cam")
    cam = bpy.data.objects.new("Cam", cam_data)
    bpy.context.scene.collection.objects.link(cam)
    fixed_dist = cfg.get("cam_distance")
    if fixed_dist is not None:
        dist = float(fixed_dist)
        if cfg.get("camera_model") == "darkorbit":
            dist /= zoom
    elif cfg["cam_ortho"]:
        dist = radius * 4.0
    else:
        dist = fit_camera_distance(radius, cfg["cam_fov"], cfg["cam_margin"])
    cam.location = center + direction * dist
    cam.rotation_euler = (center - cam.location).to_track_quat("-Z", "Y").to_euler()
    # clip range must span the model regardless of its scale, or large assets
    # (buildings) fall outside the default 1000-unit clip and render empty.
    cam_data.clip_start = max(0.01, radius * 0.001)
    cam_data.clip_end = dist + radius * 4.0 + 1.0
    if cfg.get('camera_model') == 'darkorbit':
        cam_data.clip_start, cam_data.clip_end = 10.0, 80000.0
    cam_data.sensor_fit = 'VERTICAL'
    if cfg["cam_ortho"]:
        cam_data.type = "ORTHO"
        cam_data.ortho_scale = radius * 2.0 * cfg["cam_margin"]
    else:
        cam_data.type = "PERSP"
        cam_data.angle = math.radians(cfg["cam_fov"])
        if fixed_dist is not None and cfg.get("camera_framing") == "sprite":
            # Crop/enlarge the projection rather than dollying toward the mesh.
            # Perspective foreshortening and view-dependent rim stay at the
            # original Observer3D distance. Native retains the full game FOV.
            cam_data.angle = 2 * math.asin(min(.99, radius * cfg['cam_margin'] / dist))
        cam_data['reference_fov'] = cfg['cam_fov']
        cam_data['reference_distance'] = dist
    bpy.context.scene.camera = cam
    return cam


def setup_render(cfg):
    sc = bpy.context.scene
    sc.render.engine = cfg["engine"]
    res = cfg["resolution"]
    sc.render.resolution_x = sc.render.resolution_y = res
    sc.render.resolution_percentage = 100
    sc.render.film_transparent = cfg["film_transparent"]
    sc.render.image_settings.file_format = "PNG"
    sc.render.image_settings.color_mode = "RGBA"
    try:
        sc.eevee.taa_render_samples = cfg["samples"]
    except AttributeError:
        pass
    # Standard view transform -> texture colours render as authored (game sprites),
    # instead of AgX/Filmic tone mapping which desaturates and shifts hues.
    vt = cfg.get("view_transform")
    if vt:
        try:
            sc.view_settings.view_transform = vt
        except TypeError:
            pass


def animation_end():
    """Last frame of any imported shape-key (morph) animation, else 1.

    Covers both an active action and NLA strips (clips are imported as NLA tracks)."""
    end = 1.0
    for ob in bpy.context.scene.objects:
        sk = getattr(ob.data, "shape_keys", None)
        ad = sk.animation_data if sk else None
        if not ad:
            continue
        if ad.action:
            end = max(end, ad.action.frame_range[1])
        for tr in ad.nla_tracks:
            if tr.mute:
                continue
            for st in tr.strips:
                end = max(end, st.frame_end)
    return end


def solo_first_clip():
    """When a model carries several clips (NLA tracks), play only the first so
    the turntable shows one clean animation instead of all clips blended."""
    for ob in bpy.context.scene.objects:
        sk = getattr(ob.data, "shape_keys", None)
        ad = sk.animation_data if sk else None
        if ad and len(ad.nla_tracks) > 1:
            for i, tr in enumerate(ad.nla_tracks):
                tr.mute = (i != 0)


def apply_emission(strength):
    """Override material emission strength (GlowMethod shaderParams.glow)."""
    if strength is None:
        return
    for mat in bpy.data.materials:
        if not mat.node_tree:
            continue
        for node in mat.node_tree.nodes:
            if node.type == "BSDF_PRINCIPLED" and "Emission Strength" in node.inputs:
                node.inputs["Emission Strength"].default_value = strength
            elif node.type == "EMISSION" and "Strength" in node.inputs:
                node.inputs["Strength"].default_value = strength


def cam_coord(scene, cam, world_pos, res):
    co = bpy_extras.object_utils.world_to_camera_view(scene, cam, world_pos)
    if co.z < 0 or not (0 <= co.x <= 1 and 0 <= co.y <= 1):
        return None
    return [co.x * (res - 1), (1.0 - co.y) * (res - 1)]


def main():
    a = args_after_dashes()
    glb, out_dir, cfg_path = a[0], a[1], a[2]
    with open(cfg_path, encoding="utf-8") as f:
        cfg = json.load(f)
    name = os.path.splitext(os.path.basename(glb))[0]
    os.makedirs(out_dir, exist_ok=True)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=glb)
    mesh_center = scene_bounds()[0]  # geometry only, before outline/particles
    sys.path.insert(0, os.path.dirname(__file__))
    if cfg.get("light_model") == "darkorbit":
        import away_material
        with open(cfg["source_scene"], encoding="utf-8") as f:
            away_material.apply(json.load(f), cfg)
    else:
        apply_emission(cfg.get("emission_strength"))

    center, radius, mn, mx = scene_bounds()
    if cfg.get('camera_model') == 'darkorbit':
        if cfg.get('mode') == 'item':
            # Keep item-mode framing at entity origin.
            radius = max(Vector((x, y, z)).length for x in (mn.x, mx.x)
                         for y in (mn.y, mx.y) for z in (mn.z, mx.z))
            center = Vector((0, 0, 0))
        else:
            # Keep ship geometry's midpoint at the turntable/camera center.
            # Several source meshes are offset from entity origin; rotating
            # around that origin makes the hull orbit within a stable crop.
            center = mesh_center.copy()
            radius = max((Vector((x, y, z)) - center).length
                         for x in (mn.x, mx.x)
                         for y in (mn.y, mx.y) for z in (mn.z, mx.z))
    root = parent_under_root(center)
    particle_anchor = root.matrix_world.inverted() @ mesh_center
    setup_world(cfg)
    if cfg.get('light_model') != 'darkorbit':
        setup_sun(cfg)
    frame_radius = radius
    if cfg.get('particle_scene'):
        with open(cfg['particle_scene'], encoding='utf-8') as f:
            for layer in json.load(f):
                scale = layer['scale']
                for row in layer['samples']:
                    for p in row:
                        if p:
                            pos = Vector([p['position'][i] * scale[i] + layer['position'][i] for i in range(3)])
                            if layer.get('center_on_mesh'):
                                pos = away_to_blender(pos) + particle_anchor
                            extent = math.hypot(p['size'][0] * scale[0], p['size'][1] * scale[1]) / 2
                            frame_radius = max(frame_radius, pos.length + extent)
    cam = setup_camera(cfg, center, frame_radius)
    if cfg.get('light_model') != 'darkorbit':
        setup_hero_light(cfg, center, radius)
    setup_render(cfg)
    sc = bpy.context.scene
    particles = None
    if cfg.get("particle_scene"):
        import away_particles
        particles = away_particles.Scene(cfg["particle_scene"], root, cam, particle_anchor)
    res = cfg["resolution"]

    hide_list = cfg.get("hide_objects") or []
    if hide_list:
        for o in sc.objects:
            if any(h in o.name for h in hide_list):
                o.hide_viewport = True
                o.hide_render = True

    # item mode renders a plain model (ore / items) with no reference points;
    # ship/auto track the engine_/laserpoint_ empties for the coordinates JSON.
    coord_prefixes = tuple(cfg.get("coord_prefixes", POINT_PREFIXES))
    if cfg.get("mode") == "item":
        points = []
    else:
        points = [o for o in sc.objects
                  if o.type == "EMPTY" and o.name.startswith(coord_prefixes) and not o.hide_render]
    coords = {p.name: [] for p in points}
    frame_paths = []

    solo_first_clip()
    anim_end = animation_end()   # >1 if the glb carries a vertex (morph) animation

    astart = max(1.0, min(float(cfg.get("anim_frame_start", 1)), anim_end))
    aend = float(cfg.get("anim_frame_end") or anim_end)
    aend = max(1.0, min(aend, anim_end))

    frames = cfg["frames"]
    start = cfg.get("start_angle", 0.0)
    # per-frame step: explicit override, else spread total_degrees across all frames
    step = cfg.get("deg_per_frame")
    if not step:
        step = cfg.get("total_degrees", 360.0) / max(frames, 1)
    frame_start = cfg.get("frame_start", 1)
    rotation_enabled = cfg.get("rotation", True)
    rotation_sign = -1 if cfg.get('camera_model') == 'darkorbit' else 1

    for f in range(frames):
        if rotation_enabled:
            root.rotation_euler.z = math.radians(start + rotation_sign * f * step)
        else:
            root.rotation_euler.z = math.radians(start)

        # play the morph animation across the render frames (alongside the turntable)
        if anim_end > 1:
            af = astart + (aend - astart) * (f / max(frames - 1, 1))
            sc.frame_set(int(af), subframe=af - int(af))
        bpy.context.view_layer.update()
        if particles:
            particles.update(f)
        if f == 0 and cfg.get("blend_path"):
            bpy.context.preferences.filepaths.save_version = 0
            bpy.ops.file.pack_all()
            bpy.ops.wm.save_as_mainfile(filepath=cfg["blend_path"])
        if '--scene-only' in a:
            return
        fname = f"{name}_{frame_start + f}.png"
        path = os.path.join(out_dir, fname)
        sc.render.filepath = path
        bpy.ops.render.render(write_still=True)
        frame_paths.append(fname)
        for p in points:
            coords[p.name].append(cam_coord(sc, cam, p.matrix_world.translation, res))

    # Raw, full-resolution data; src/render.py does the stable crop + origin flip.
    raw = {"name": name, "resolution": res, "frames": frame_paths, "points": coords}
    with open(os.path.join(out_dir, f"{name}_render_raw.json"), "w",
              encoding="utf-8") as f:
        json.dump(raw, f)
    print(f"[render_sprites] {frames} frames + raw coords -> {out_dir} "
          f"({len(points)} points)")


if __name__ == "__main__":
    main()
