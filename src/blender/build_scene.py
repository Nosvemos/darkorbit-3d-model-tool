"""Blender headless scene builder (Blender 5.x).

Run via:
    blender --background --python src/blender/build_scene.py -- \
        <scene.json> <out.glb> [--gltf] [--obj] [--preview]

Reads a scene JSON emitted by src/pipeline.py (geometry in local space + a
4x4 world matrix per object + texture paths), builds meshes and PBR materials,
converts engine_/laserpoint_/light_position nodes into PLAIN_AXES Empties
parented to the main body, then exports glb (and optionally gltf/obj).

Only depends on bpy + stdlib — no numpy/imagecodecs inside Blender.
"""
import json
import math
import os
import sys

import bpy
from mathutils import Matrix

POINT_PREFIXES = ("engine_", "laserpoint_", "light_position")
# Away3D is Y-up/left-handed; rotate +90deg about X so the model sits Z-up in
# Blender. glTF export then converts back to its own Y-up convention.
AXIS_CONV = Matrix.Rotation(math.radians(90.0), 4, "X")


def argv_after_dashes():
    return sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def reset_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def make_matrix(flat16):
    return Matrix([flat16[i:i + 4] for i in range(0, 16, 4)])


def build_mesh(obj):
    verts = [tuple(obj["positions"][i:i + 3]) for i in range(0, len(obj["positions"]), 3)]
    idx = obj["indices"]
    faces = [tuple(idx[i:i + 3]) for i in range(0, len(idx), 3)]
    mesh = bpy.data.meshes.new(obj["name"])
    mesh.from_pydata(verts, [], faces)
    mesh.validate()

    # AWD2 can carry authored vertex normals. Keep them instead of replacing
    # them with Blender's newly averaged smooth normals; DarkOrbit's faceting
    # and highlight placement depend on this stream. Some ships (including
    # Goliath) omit it, in which case smooth normals are generated as before.
    flat_normals = obj.get("normals") or []
    if len(flat_normals) == len(verts) * 3:
        vertex_normals = []
        valid = True
        for i in range(0, len(flat_normals), 3):
            x, y, z = map(float, flat_normals[i:i + 3])
            length = math.sqrt(x * x + y * y + z * z)
            if not math.isfinite(length) or length <= 1e-12:
                valid = False
                break
            vertex_normals.append((x / length, y / length, z / length))
        if valid:
            mesh.normals_split_custom_set_from_vertices(vertex_normals)

    uvs = obj.get("uvs") or []
    if uvs:
        uv_layer = mesh.uv_layers.new(name="UVMap")
        for loop in mesh.loops:
            u, v = uvs[loop.vertex_index * 2], uvs[loop.vertex_index * 2 + 1]
            uv_layer.data[loop.index].uv = (u, 1.0 - v)  # flip V for Blender

    mesh.shade_smooth()
    ob = bpy.data.objects.new(obj["name"], mesh)
    bpy.context.scene.collection.objects.link(ob)
    ob.matrix_world = AXIS_CONV @ make_matrix(obj["matrix"])
    _add_clips(ob, obj.get("clips") or [])
    if obj.get("hide"):
        ob.hide_viewport = True
        ob.hide_render = True
    return ob


def _clip_keyframes(keys):
    """Keyframe a clip's shape keys so pose i is fully on at frame i+1 (crossfading
    between consecutive poses). Goes into the Key's currently-active action."""
    for i, key in enumerate(keys):
        for f, val in ((i, 0.0), (i + 1, 1.0), (i + 2, 0.0)):
            if 1 <= f <= len(keys):
                key.value = val
                key.keyframe_insert("value", frame=f)


def _add_clips(ob, clips):
    """Add shape keys for every pose and build one named action per clip, so the
    glTF export emits a separate named animation (e.g. 'open', 'close')."""
    if not clips:
        return
    ob.shape_key_add(name="basis", from_mix=False)
    groups = []
    for clip in clips:
        keys = []
        for fi, frame in enumerate(clip["frames"]):
            key = ob.shape_key_add(name=f"{clip['name']}_{fi}", from_mix=False)
            for v in range(len(key.data)):
                key.data[v].co = (frame[v * 3], frame[v * 3 + 1], frame[v * 3 + 2])
            keys.append(key)
        groups.append((clip["name"], keys))

    keyblock = ob.data.shape_keys
    ad = keyblock.animation_data_create()
    longest = max(len(k) for _, k in groups)
    bpy.context.scene.frame_start = 1
    bpy.context.scene.frame_end = max(2, longest)
    # each clip -> its own action on its own NLA track, so the glTF NLA_TRACKS
    # export emits one named animation per clip (e.g. 'open', 'close')
    for name, keys in groups:
        action = bpy.data.actions.new(name)
        ad.action = action
        _clip_keyframes(keys)
        track = ad.nla_tracks.new()
        track.name = name
        track.strips.new(name, 1, action)
        ad.action = None


def load_image(path, non_color=False):
    if not path or not os.path.exists(path):
        return None
    img = bpy.data.images.load(path, check_existing=True)
    if non_color:
        img.colorspace_settings.name = "Non-Color"
    return img


def build_material(name, textures):
    mat = bpy.data.materials.new(name)
    mat.use_backface_culling = False
    if mat.node_tree is None:             # use_nodes deprecated in Blender 6.0
        mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])

    def input_any(node, names):
        for input_name in names:
            if input_name in node.inputs:
                return node.inputs[input_name]
        return None

    def set_input(node, names, value):
        socket = input_any(node, names)
        if socket is not None:
            socket.default_value = value

    set_input(bsdf, ["Metallic"], 0.0)
    set_input(bsdf, ["Specular IOR Level", "Specular"], 1.0)
    # Away3D EntityBasicMaterial defaults gloss=50; this is the closest roughness
    # approximation in Blender's PBR model.
    set_input(bsdf, ["Roughness"], 0.2)

    def tex(path, non_color=False, x=-600, y=0):
        img = load_image(path, non_color)
        if not img:
            return None
        node = nt.nodes.new("ShaderNodeTexImage")
        node.image = img
        node.extension = "REPEAT"          # EntityBasicMaterial.repeat = true
        node.interpolation = "Linear"      # TEXTURE_FILTERING.medium/high
        node.location = (x, y)
        return node

    def multiply_color(a, b, x=-250, y=250):
        mix = nt.nodes.new("ShaderNodeMixRGB")
        mix.blend_type = "MULTIPLY"
        mix.inputs["Fac"].default_value = 1.0
        mix.location = (x, y)
        nt.links.new(a, mix.inputs["Color1"])
        nt.links.new(b, mix.inputs["Color2"])
        return mix.outputs["Color"]

    def scalar_to_color(value_socket, x=-430, y=80):
        try:
            comb = nt.nodes.new("ShaderNodeCombineColor")
            inputs = ("Red", "Green", "Blue")
            output = "Color"
        except RuntimeError:
            comb = nt.nodes.new("ShaderNodeCombineRGB")
            inputs = ("R", "G", "B")
            output = "Image"
        comb.location = (x, y)
        for input_name in inputs:
            nt.links.new(value_socket, comb.inputs[input_name])
        return comb.outputs[output]

    def separate_rgb(color_socket, x=-320, y=-220):
        try:
            sep = nt.nodes.new("ShaderNodeSeparateColor")
        except RuntimeError:
            sep = nt.nodes.new("ShaderNodeSeparateRGB")
        sep.location = (x, y)
        nt.links.new(color_socket, sep.inputs[0])
        return sep

    def sep_out(sep, names):
        for output_name in names:
            if output_name in sep.outputs:
                return sep.outputs[output_name]
        return None

    diffuse = tex(textures.get("diffuse"), y=300)
    base_color = diffuse.outputs["Color"] if diffuse else None

    ao = tex(textures.get("ao"), non_color=True, y=100)
    if base_color is not None and ao:
        base_color = multiply_color(base_color, ao.outputs["Color"], y=220)

    gal = tex(textures.get("gal"), non_color=True, y=-170)
    gal_sep = separate_rgb(gal.outputs["Color"], y=-170) if gal else None
    if base_color is not None and gal_sep:
        gal_lightmap = sep_out(gal_sep, ["Blue", "B"])
        if gal_lightmap:
            base_color = multiply_color(base_color, scalar_to_color(gal_lightmap), y=120)

    if diffuse:
        nt.links.new(base_color, bsdf.inputs["Base Color"])

    # The pipeline pre-packs Away3D R strength into alpha and translates G
    # gloss into glTF's G roughness channel. Linking those channels directly
    # survives Blender's GLB export/import round trip used by the renderer.
    specular = tex(textures.get("specular_pbr"), non_color=True, y=0)
    specular_input = input_any(bsdf, ["Specular IOR Level", "Specular"])
    if specular and specular_input is not None:
        specular_sep = separate_rgb(specular.outputs["Color"], y=0)
        specular_strength = specular.outputs.get("Alpha")
        specular_roughness = sep_out(specular_sep, ["Green", "G"])
        if specular_strength:
            nt.links.new(specular_strength, specular_input)
        if specular_roughness:
            roughness_input = input_any(bsdf, ["Roughness"])
            if roughness_input is not None:
                nt.links.new(specular_roughness, roughness_input)

    glow = tex(textures.get("glow"), y=-300)
    if glow:
        emission_color = input_any(bsdf, ["Emission Color"])
        emission_strength = input_any(bsdf, ["Emission Strength"])
        if emission_color is not None:
            nt.links.new(glow.outputs["Color"], emission_color)
        if emission_strength is not None:
            emission_strength.default_value = 1.0
    elif gal and "Emission Color" in bsdf.inputs:
        nt.links.new(gal.outputs["Color"], bsdf.inputs["Emission Color"])
        if "Emission Strength" in bsdf.inputs:
            bsdf.inputs["Emission Strength"].default_value = 1.0

    alpha = tex(textures.get("alpha"), non_color=True, y=-460)
    alpha_input = input_any(bsdf, ["Alpha"])
    alpha_source = None
    if alpha:
        alpha_source = alpha.outputs["Alpha"] if "Alpha" in alpha.outputs else alpha.outputs["Color"]
    elif gal_sep:
        alpha_source = sep_out(gal_sep, ["Green", "G"])
    if alpha_source is not None and alpha_input is not None:
        nt.links.new(alpha_source, alpha_input)
        mat.blend_method = "BLEND"
        if hasattr(mat, "show_transparent_back"):
            mat.show_transparent_back = True

    normal = tex(textures.get("normal"), non_color=True, y=-600)
    if normal:
        nmap = nt.nodes.new("ShaderNodeNormalMap")
        nmap.location = (-300, -600)
        nt.links.new(normal.outputs["Color"], nmap.inputs["Color"])
        nt.links.new(nmap.outputs["Normal"], bsdf.inputs["Normal"])
    return mat


def to_empty(ob, parent):
    """Replace a marker mesh with a PLAIN_AXES empty at its geometry median."""
    bpy.ops.object.select_all(action="DESELECT")
    ob.select_set(True)
    bpy.context.view_layer.objects.active = ob
    bpy.ops.object.origin_set(type="ORIGIN_GEOMETRY", center="MEDIAN")
    world = ob.matrix_world.copy()
    name = ob.name
    bpy.data.objects.remove(ob, do_unlink=True)

    empty = bpy.data.objects.new(name, None)
    empty.empty_display_type = "PLAIN_AXES"
    empty.empty_display_size = 5.0
    bpy.context.scene.collection.objects.link(empty)
    if parent:
        empty.parent = parent
    empty.matrix_world = world
    return empty


def main():
    args = argv_after_dashes()
    scene_json, out_glb = args[0], args[1]
    want_gltf = "--gltf" in args
    want_obj = "--obj" in args

    with open(scene_json, encoding="utf-8") as f:
        scene = json.load(f)

    reset_scene()

    meshes, points = [], []
    for obj in scene["objects"]:
        ob = build_mesh(obj)
        if obj.get("textures"):
            ob.data.materials.append(build_material(ob.name + "_mat", obj["textures"]))
        (points if obj["name"].startswith(POINT_PREFIXES) else meshes).append(ob)

    # main body = largest mesh; points become empties parented to it
    main = max(meshes, key=lambda o: len(o.data.vertices), default=None)
    hidden_lookup = {obj["name"]: obj.get("hide", False) for obj in scene["objects"]}
    for ob in points:
        name = ob.name
        empty = to_empty(ob, main)
        if hidden_lookup.get(name):
            empty.hide_viewport = True
            empty.hide_render = True

    # glb is the self-contained primary in model/; the separate gltf and obj
    # formats go in their own subdirs so their sidecar files (bin/mtl/textures)
    # don't clutter model/.
    base = os.path.dirname(out_glb)
    name = os.path.splitext(os.path.basename(out_glb))[0]
    os.makedirs(base, exist_ok=True)
    bpy.ops.export_scene.gltf(filepath=out_glb, export_format="GLB",
                              export_yup=True, use_visible=True,
                              export_morph=True, export_animations=True,
                              export_animation_mode="NLA_TRACKS")
    if want_gltf:
        d = os.path.join(base, "gltf")
        os.makedirs(d, exist_ok=True)
        bpy.ops.export_scene.gltf(filepath=os.path.join(d, name + ".gltf"),
                                  export_format="GLTF_SEPARATE", export_yup=True)
    if want_obj:
        d = os.path.join(base, "obj")
        os.makedirs(d, exist_ok=True)
        bpy.ops.wm.obj_export(filepath=os.path.join(d, name + ".obj"))
    print(f"[build_scene] exported {out_glb} "
          f"({len(meshes)} meshes, {len(points)} points)")


if __name__ == "__main__":
    main()
