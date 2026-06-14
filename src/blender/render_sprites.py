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

    points = [o for o in sc.objects
              if o.type == "EMPTY" and o.name.startswith(POINT_PREFIXES)]
    coords = {p.name: [] for p in points}
    frame_paths = []

    apply_emission(cfg.get("emission_strength"))

    frames = cfg["frames"]
    start = cfg.get("start_angle", 0.0)
    for f in range(frames):
        root.rotation_euler.z = math.radians(start + f * cfg["deg_per_frame"])
        bpy.context.view_layer.update()
        path = os.path.join(out_dir, f"{name}_{f:03d}.png")
        sc.render.filepath = path
        bpy.ops.render.render(write_still=True)
        frame_paths.append(os.path.basename(path))
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
