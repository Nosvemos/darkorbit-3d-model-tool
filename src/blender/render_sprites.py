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


def hex_to_rgb(hex_str: str) -> list[float]:
    hex_str = hex_str.lstrip('#')
    return [int(hex_str[i:i+2], 16) / 255.0 for i in (0, 2, 4)]


def away_to_blender(v: Vector) -> Vector:
    """Convert an Away3D Y-up vector to the Blender Z-up scene built by us."""
    return Vector((v.x, -v.z, v.y))


def darkorbit_light_direction(tilt, pan) -> Vector:
    """LightSettings.apply: ExtMath.tiltPan2Vector(tilt, pan, -1)."""
    t = math.radians(tilt)
    p = math.radians(pan)
    away = Vector((-math.sin(t) * math.sin(p),
                   -math.sin(t) * math.cos(p),
                   -math.cos(t)))
    return away_to_blender(away).normalized()


def darkorbit_camera_direction(tilt, pan) -> Vector:
    """Observer3D camera offset direction from lookAt to camera.

    DarkOrbit pan describes the viewing direction. This function positions the
    camera on the opposite side of its target, so its position azimuth is
    rotated by 180 degrees. Without that conversion, ship renders look from the
    engine side (the Goliath's front markers are on AWD +Z).
    """
    t = math.radians(tilt)
    p = math.radians(pan + 180.0)
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


def apply_away3d_lighting(cfg):
    """Restore the client's separate ambient and specular-light terms in EEVEE.

    An EEVEE World surface provides a background, not ambient irradiance. The
    map XML supplies ambientColor/ambient separately from the sun, so add that
    diffuse-colored fill as emission while retaining direct sun shading. The
    light's specular multiplier is likewise separate from the material map.
    """
    if cfg.get("light_model") != "darkorbit":
        return

    specular_strength = float(cfg.get("specular_strength", 1.0))
    for mat in bpy.data.materials:
        if not mat.node_tree or mat.get("darkorbit_specular_lobe"):
            continue
        nt = mat.node_tree
        packed_map = next((node for node in nt.nodes
                           if node.type == "TEX_IMAGE" and node.image and
                           "_specular_gltf" in node.image.name.lower()), None)
        bsdf = next((node for node in nt.nodes
                     if node.type == "BSDF_PRINCIPLED"), None)
        output = next((node for node in nt.nodes
                       if node.type == "OUTPUT_MATERIAL" and node.is_active_output), None)
        if packed_map is None or bsdf is None or output is None:
            continue

        # Away3D's BasicSpecularMethod uses map R as a direct Phong highlight
        # weight. Principled clamps the equivalent dielectric Fresnel response
        # to about 4%, making DarkOrbit's authored specular maps look almost
        # matte. Use a separate glossy lobe so the channel retains its strength.
        glossy = nt.nodes.new("ShaderNodeBsdfGlossy")
        glossy.name = "Away3D specular lobe"
        glossy.label = "Away3D BasicSpecularMethod"
        glossy.location = (260, -400)
        separate = nt.nodes.new("ShaderNodeSeparateColor")
        separate.name = "Away3D gloss channel"
        separate.location = (-280, -420)
        nt.links.new(packed_map.outputs["Color"], separate.inputs[0])
        gloss = separate.outputs.get("Green")
        if gloss is None:
            gloss = separate.outputs.get("G")
        if gloss is None:
            continue
        nt.links.new(gloss, glossy.inputs["Roughness"])

        strength = nt.nodes.new("ShaderNodeMath")
        strength.operation = "MULTIPLY"
        strength.name = "Away3D light specular strength"
        strength.label = f"Light specular × {specular_strength:g}"
        # Blender's normalized glossy BSDF carries more energy than Away3D's
        # empirical Phong term for the same map value. Calibrate the lobe so a
        # full-strength map stays a highlight instead of washing out the hull.
        strength.inputs[1].default_value = specular_strength * 0.1
        nt.links.new(packed_map.outputs["Alpha"], strength.inputs[0])

        try:
            color = nt.nodes.new("ShaderNodeCombineColor")
            color_inputs = ("Red", "Green", "Blue")
        except RuntimeError:
            color = nt.nodes.new("ShaderNodeCombineRGB")
            color_inputs = ("R", "G", "B")
        color.location = (0, -420)
        for input_name in color_inputs:
            nt.links.new(strength.outputs[0], color.inputs[input_name])
        nt.links.new(color.outputs[0], glossy.inputs["Color"])

        spec_input = next((bsdf.inputs[name] for name in
                           ("Specular IOR Level", "Specular") if name in bsdf.inputs), None)
        if spec_input is not None:
            for link in list(spec_input.links):
                nt.links.remove(link)
            spec_input.default_value = 0.0

        surface = output.inputs["Surface"]
        old_surface = surface.links[0].from_socket if surface.is_linked else bsdf.outputs[0]
        add_specular = nt.nodes.new("ShaderNodeAddShader")
        add_specular.name = "Away3D diffuse plus specular"
        add_specular.location = (500, 120)
        nt.links.new(old_surface, add_specular.inputs[0])
        nt.links.new(glossy.outputs[0], add_specular.inputs[1])
        for link in list(surface.links):
            nt.links.remove(link)
        nt.links.new(add_specular.outputs[0], surface)
        mat["darkorbit_specular_lobe"] = True

    ambient_strength = max(0.0, float(cfg.get("world_strength", 0.0)))
    if ambient_strength > 0:
        ambient_color = hex_to_rgb(cfg.get("world_color", "#ffffff"))
        for mat in bpy.data.materials:
            if not mat.node_tree:
                continue
            nt = mat.node_tree
            if any(node.get("darkorbit_ambient_fill") for node in nt.nodes):
                continue
            bsdf = next((node for node in nt.nodes
                         if node.type == "BSDF_PRINCIPLED"), None)
            output = next((node for node in nt.nodes
                           if node.type == "OUTPUT_MATERIAL" and node.is_active_output), None)
            if bsdf is None or output is None or "Base Color" not in bsdf.inputs:
                continue
            surface = output.inputs["Surface"]
            surface_links = list(surface.links)
            if not surface_links:
                continue

            base = bsdf.inputs["Base Color"]
            albedo = nt.nodes.new("ShaderNodeMixRGB")
            albedo.name = "DarkOrbit ambient albedo"
            albedo.label = "Away3D diffuse × ambientColor"
            albedo.blend_type = "MULTIPLY"
            albedo.inputs["Fac"].default_value = 1.0
            albedo.inputs["Color2"].default_value = ambient_color + [1.0]
            if base.is_linked:
                nt.links.new(base.links[0].from_socket, albedo.inputs["Color1"])
            else:
                albedo.inputs["Color1"].default_value = base.default_value

            fill = nt.nodes.new("ShaderNodeEmission")
            fill.name = "DarkOrbit ambient fill"
            fill.label = "Away3D ambient"
            fill.inputs["Strength"].default_value = ambient_strength
            nt.links.new(albedo.outputs["Color"], fill.inputs["Color"])

            add = nt.nodes.new("ShaderNodeAddShader")
            add.name = "DarkOrbit ambient lighting"
            add.label = "Direct + ambient"
            nt.links.new(surface_links[0].from_socket, add.inputs[0])
            nt.links.new(fill.outputs["Emission"], add.inputs[1])
            nt.links.remove(surface_links[0])
            nt.links.new(add.outputs[0], surface)
            fill["darkorbit_ambient_fill"] = True

    for mat in bpy.data.materials:
        if not mat.node_tree:
            continue
        nt = mat.node_tree
        if mat.get("darkorbit_specular_lobe"):
            continue
        for bsdf in (node for node in nt.nodes if node.type == "BSDF_PRINCIPLED"):
            socket = next((bsdf.inputs[name] for name in
                           ("Specular IOR Level", "Specular") if name in bsdf.inputs), None)
            if socket is None:
                continue
            if socket.is_linked:
                link = socket.links[0]
                source = link.from_socket
                nt.links.remove(link)
                scale = nt.nodes.new("ShaderNodeMath")
                scale.operation = "MULTIPLY"
                scale.name = "DarkOrbit light specular strength"
                scale.label = f"Away3D light specular × {specular_strength:g}"
                nt.links.new(source, scale.inputs[0])
                scale.inputs[1].default_value = specular_strength
                nt.links.new(scale.outputs[0], socket)
            else:
                socket.default_value = float(socket.default_value) * specular_strength


def setup_camera(cfg, center, radius):
    if cfg.get("camera_model") == "darkorbit":
        direction = darkorbit_camera_direction(cfg.get("cam_tilt", 135.0),
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
    apply_away3d_lighting(cfg)

    center, radius, _, _ = scene_bounds()
    root = parent_under_root(center)
    setup_world(cfg)
    setup_sun(cfg)
    cam = setup_camera(cfg, center, radius)
    setup_hero_light(cfg, center, radius)
    setup_render(cfg)
    sc = bpy.context.scene
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

    apply_emission(cfg.get("emission_strength"))
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

    for f in range(frames):
        if rotation_enabled:
            root.rotation_euler.z = math.radians(start + f * step)
        else:
            root.rotation_euler.z = math.radians(start)

        # play the morph animation across the render frames (alongside the turntable)
        if anim_end > 1:
            af = astart + (aend - astart) * (f / max(frames - 1, 1))
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
