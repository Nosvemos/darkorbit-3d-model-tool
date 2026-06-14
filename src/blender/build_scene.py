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
    return ob


def load_image(path, non_color=False):
    if not path or not os.path.exists(path):
        return None
    img = bpy.data.images.load(path, check_existing=True)
    if non_color:
        img.colorspace_settings.name = "Non-Color"
    return img


def build_material(name, textures):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])

    def tex(path, non_color=False, x=-600, y=0):
        img = load_image(path, non_color)
        if not img:
            return None
        node = nt.nodes.new("ShaderNodeTexImage")
        node.image = img
        node.location = (x, y)
        return node

    diffuse = tex(textures.get("diffuse"), y=300)
    if diffuse:
        nt.links.new(diffuse.outputs["Color"], bsdf.inputs["Base Color"])

    specular = tex(textures.get("specular"), non_color=True, y=0)
    if specular and "Specular IOR Level" in bsdf.inputs:
        nt.links.new(specular.outputs["Color"], bsdf.inputs["Specular IOR Level"])

    glow = tex(textures.get("glow"), y=-300)
    if glow:
        nt.links.new(glow.outputs["Color"], bsdf.inputs["Emission Color"])
        bsdf.inputs["Emission Strength"].default_value = 1.0

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
    for ob in points:
        to_empty(ob, main)

    # glb is the self-contained primary in model/; the separate gltf and obj
    # formats go in their own subdirs so their sidecar files (bin/mtl/textures)
    # don't clutter model/.
    base = os.path.dirname(out_glb)
    name = os.path.splitext(os.path.basename(out_glb))[0]
    os.makedirs(base, exist_ok=True)
    bpy.ops.export_scene.gltf(filepath=out_glb, export_format="GLB",
                              export_yup=True, use_visible=True)
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
