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
        if o.type != "MESH":
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
    for o in list(bpy.context.scene.objects):
        if o is root or o.parent:
            continue
        o.parent = root
        o.matrix_parent_inverse = root.matrix_world.inverted()
    return root


def setup_world(cfg):
    hdri_dir = bpy.utils.system_resource("DATAFILES", path="studiolights/world")
    path = os.path.join(hdri_dir, cfg["world_hdri"])
    world = bpy.data.worlds.new("World")
    bpy.context.scene.world = world
    world.use_nodes = True
    nt = world.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputWorld")
    bg = nt.nodes.new("ShaderNodeBackground")
    bg.inputs["Strength"].default_value = cfg["world_strength"]
    nt.links.new(bg.outputs["Background"], out.inputs["Surface"])
    if os.path.exists(path):
        env = nt.nodes.new("ShaderNodeTexEnvironment")
        env.image = bpy.data.images.load(path, check_existing=True)
        nt.links.new(env.outputs["Color"], bg.inputs["Color"])


def setup_sun(cfg):
    data = bpy.data.lights.new("Sun", "SUN")
    data.energy = cfg["sun_energy"]
    sun = bpy.data.objects.new("Sun", data)
    sun.rotation_euler = [math.radians(a) for a in cfg["sun_angle"]]
    bpy.context.scene.collection.objects.link(sun)


def setup_camera(cfg, center, radius):
    el = math.radians(cfg["cam_elevation"])
    az = math.radians(cfg["cam_azimuth"])
    direction = Vector((math.cos(el) * math.cos(az),
                        math.cos(el) * math.sin(az),
                        math.sin(el)))
    cam_data = bpy.data.cameras.new("Cam")
    cam = bpy.data.objects.new("Cam", cam_data)
    bpy.context.scene.collection.objects.link(cam)
    dist = radius * 4.0
    cam.location = center + direction * dist
    cam.rotation_euler = (center - cam.location).to_track_quat("-Z", "Y").to_euler()
    # clip range must span the model regardless of its scale, or large assets
    # (buildings) fall outside the default 1000-unit clip and render empty.
    cam_data.clip_start = max(0.01, radius * 0.001)
    cam_data.clip_end = dist + radius * 4.0 + 1.0
    if cfg["cam_ortho"]:
        cam_data.type = "ORTHO"
        cam_data.ortho_scale = radius * 2.0 * cfg["cam_margin"]
    else:
        cam_data.type = "PERSP"
        cam_data.angle = math.radians(cfg["cam_fov"])
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
    """Override the Emission Strength of every Principled BSDF (glow tuning)."""
    if strength is None:
        return
    for mat in bpy.data.materials:
        if not mat.use_nodes:
            continue
        for node in mat.node_tree.nodes:
            if node.type == "BSDF_PRINCIPLED" and "Emission Strength" in node.inputs:
                node.inputs["Emission Strength"].default_value = strength


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

    center, radius, _, _ = scene_bounds()
    root = parent_under_root(center)
    setup_world(cfg)
    setup_sun(cfg)
    cam = setup_camera(cfg, center, radius)
    setup_render(cfg)
    sc = bpy.context.scene
    res = cfg["resolution"]

    # item mode renders a plain model (ore / items) with no reference points;
    # ship/auto track the engine_/laserpoint_ empties for the coordinates JSON.
    coord_prefixes = tuple(cfg.get("coord_prefixes", POINT_PREFIXES))
    if cfg.get("mode") == "item":
        points = []
    else:
        points = [o for o in sc.objects
                  if o.type == "EMPTY" and o.name.startswith(coord_prefixes)]
    coords = {p.name: [] for p in points}
    frame_paths = []

    apply_emission(cfg.get("emission_strength"))
    solo_first_clip()
    anim_end = animation_end()   # >1 if the glb carries a vertex (morph) animation

    frames = cfg["frames"]
    start = cfg.get("start_angle", 0.0)
    # per-frame step: explicit override, else spread total_degrees across all frames
    step = cfg.get("deg_per_frame")
    if not step:
        step = cfg.get("total_degrees", 360.0) / max(frames, 1)
    frame_start = cfg.get("frame_start", 1)
    for f in range(frames):
        root.rotation_euler.z = math.radians(start + f * step)
        # play the morph animation across the render frames (alongside the turntable)
        if anim_end > 1:
            af = 1.0 + (anim_end - 1.0) * (f / max(frames - 1, 1))
            sc.frame_set(int(af), subframe=af - int(af))
        bpy.context.view_layer.update()
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
