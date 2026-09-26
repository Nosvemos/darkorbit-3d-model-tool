"""Original AWP quads in the model scene, with camera-facing and depth testing."""
import json
import math

import bpy
from mathutils import Matrix, Quaternion, Vector
from away_material import Graph

AXIS = Matrix(((1, 0, 0, 0), (0, 0, 1, 0),
               (0, 1, 0, 0), (0, 0, 0, 1)))


def export_alpha():
    """Keep additive RGB outside the hull when exporting to ordinary RGBA.

    The scene itself uses additive blending. A PNG cannot encode ONE/ONE;
    use the smallest covering alpha and retain premultiplied radiance. This
    preserves the appearance over black and avoids losing zero-alpha RGB.
    """
    sc = bpy.context.scene
    sc.use_nodes = True
    nt = bpy.data.node_groups.new('Stage3D additive export', 'CompositorNodeTree')
    sc.compositing_node_group = nt
    nt.interface.new_socket(name='Image', in_out='OUTPUT', socket_type='NodeSocketColor')
    out = nt.nodes.new('NodeGroupOutput')
    render = nt.nodes.new('CompositorNodeRLayers')
    split = nt.nodes.new('CompositorNodeSeparateColor')
    nt.links.new(render.outputs['Image'], split.inputs[0])
    alpha = render.outputs['Alpha']
    for channel in ('Red', 'Green', 'Blue'):
        maximum = nt.nodes.new('ShaderNodeMath')
        maximum.operation = 'MAXIMUM'
        maximum.use_clamp = True
        nt.links.new(alpha, maximum.inputs[0])
        nt.links.new(split.outputs[channel], maximum.inputs[1])
        alpha = maximum.outputs[0]
    set_alpha = nt.nodes.new('CompositorNodeSetAlpha')
    set_alpha.inputs['Type'].default_value = 'Replace Alpha'
    nt.links.new(render.outputs['Image'], set_alpha.inputs['Image'])
    nt.links.new(alpha, set_alpha.inputs['Alpha'])
    nt.links.new(set_alpha.outputs[0], out.inputs[0])


class Scene:
    def __init__(self, path, root, camera, mesh_center=(0, 0, 0)):
        self.root, self.camera = root, camera
        self.mesh_center = Vector(mesh_center)
        export_alpha()
        self.layers = []
        # Capture the hull before creating FX meshes. Recompute its far depth
        # each frame so the mist remains behind it throughout a turntable.
        self.hull_objects = [ob for ob in root.children_recursive
                             if ob.type == 'MESH']
        with open(path, encoding='utf-8') as f:
            layers = json.load(f)
        for layer in layers:
            mesh = bpy.data.meshes.new(layer['name'])
            count = len(layer['samples'][0])
            mesh.from_pydata([(0, 0, 0)] * (count * 4), [],
                             [(i*4, i*4+1, i*4+2, i*4+3) for i in range(count)])
            uv = mesh.uv_layers.new()
            for loop in mesh.loops:
                uv.data[loop.index].uv = ((0, 0), (1, 0), (1, 1), (0, 1))[loop.vertex_index % 4]
            mult = mesh.color_attributes.new(name='particle_multiplier', type='FLOAT_COLOR', domain='CORNER')
            offset = mesh.color_attributes.new(name='particle_offset', type='FLOAT_COLOR', domain='CORNER')
            ob = bpy.data.objects.new(layer['name'], mesh)
            bpy.context.scene.collection.objects.link(ob)
            ob.parent = root
            mat = bpy.data.materials.new(layer['name'])
            mat.use_nodes = True
            mat.surface_render_method = 'BLENDED'
            mat.use_transparency_overlap = True
            g = Graph(mat)
            tex = g.texture(layer['texture'])
            tex.extension = 'REPEAT' if layer.get('repeat') else 'EXTEND'
            m = g.node('VertexColor'); m.layer_name = mult.name
            o = g.node('VertexColor'); o.layer_name = offset.name
            texture_color = tex.outputs['Color']
            if layer.get('tint_texture'):
                separate = g.node('SeparateColor')
                g.put(texture_color, separate.inputs[0])
                peak = g.math('MAXIMUM', separate.outputs[0], g.math('MAXIMUM', separate.outputs[1], separate.outputs[2]))
                texture_color = g.vec('SCALE', (1, 1, 1), peak)
            color = g.vec('ADD', g.vec('MULTIPLY', texture_color, m.outputs['Color']), o.outputs['Color'])
            alpha = g.math('ADD', g.math('MULTIPLY', tex.outputs['Alpha'], m.outputs['Alpha']), o.outputs['Alpha'], clamp=True)
            if layer.get('soft_edges'):
                uv = g.node('TexCoord').outputs['UV']
                centered = g.vec('SUBTRACT', uv, (.5, .5, 0))
                radius2 = g.vec('DOT_PRODUCT', centered, centered)
                # Circular C1 falloff: full within r=.2, zero before r=.5.
                t = g.math('DIVIDE', g.math('SUBTRACT', .24, radius2), .20, clamp=True)
                smooth = g.math('MULTIPLY', g.math('MULTIPLY', t, t), g.math('SUBTRACT', 3, g.math('MULTIPLY', 2, t)))
                alpha = g.math('MULTIPLY', alpha, smooth)
            if layer['blend'] == 'add':
                # Transparent + emission implements ONE / ONE accumulation;
                # compositor derives an export alpha from accumulated radiance.
                emission = g.node('Emission')
                g.put(g.vec('SCALE', color, alpha), emission.inputs['Color'])
                add = g.node('AddShader')
                g.put(emission.outputs[0], add.inputs[0])
                g.put(g.node('BsdfTransparent').outputs[0], add.inputs[1])
                g.put(add.outputs[0], g.node('OutputMaterial').inputs['Surface'])
            else:
                g.output(color, alpha)
            mesh.materials.append(mat)
            self.layers.append((layer, ob, mult, offset))

    def update(self, frame):
        inverse_root = self.root.matrix_world.inverted()
        eye = self.camera.matrix_world.translation
        forward = (self.camera.matrix_world.to_3x3() @ Vector((0, 0, -1))).normalized()
        far_depth = max(((ob.matrix_world @ Vector(corner) - eye).dot(forward)
                         for ob in self.hull_objects if not ob.hide_render
                         for corner in ob.bound_box), default=0.) + 1.

        for layer, ob, mult, offset in self.layers:
            behind_hull = layer.get('center_on_mesh') and layer['billboard']
            anchor = self.mesh_center if layer.get('center_on_mesh') else Vector((0, 0, 0))
            emitter = self.root.matrix_world @ Matrix.Translation(anchor) @ AXIS @ Matrix.Translation(Vector(layer['position'])) @ Matrix.Diagonal((*layer['scale'], 1))
            for i, p in enumerate(layer['samples'][frame]):
                if p is None:
                    for k in range(4):
                        ob.data.vertices[i*4+k].co = (0, 0, 0)
                    continue
                center = emitter @ Vector(p['position'])
                if layer['billboard']:
                    # ParticleBillboardState cancels rotation, but retains
                    # emitter scale. Nonuniform ice-cloud scale acts in world
                    # axes, not directly on screen width and screen height.
                    rotation = self.root.matrix_world.to_3x3() @ AXIS.to_3x3()
                    basis = emitter.to_3x3() @ rotation.transposed() @ self.camera.matrix_world.to_3x3()
                    sx = sy = 1
                else:
                    basis = emitter.to_3x3()
                    sx = sy = 1
                spin = Quaternion(Vector(p['axis']), p['spin']).to_matrix()
                if layer['heading'] and Vector(p['heading']).length > 0:
                    if layer['billboard']:
                        heading = self.camera.matrix_world.to_3x3().transposed() @ emitter.to_3x3() @ Vector(p['heading'])
                        spin = Quaternion(Vector((0, 0, 1)), math.atan2(heading.y, heading.x)).to_matrix() @ spin
                    else:
                        spin = Vector((1, 0, 0)).rotation_difference(Vector(p['heading']).normalized()).to_matrix() @ spin
                w, h = p['size']
                for k, (u, v) in enumerate(((-.5, -.5), (.5, -.5), (.5, .5), (-.5, .5))):
                    world = center + basis @ spin @ Vector((u*w*sx, v*h*sy, 0))
                    if behind_hull:
                        ray = world - eye
                        depth = ray.dot(forward)
                        if depth > 0 and depth < far_depth:
                            # Move along the viewing ray: retain the screen
                            # centre/size while the opaque hull occludes mist.
                            if self.camera.data.type == 'ORTHO':
                                world += forward * (far_depth - depth)
                            else:
                                world = eye + ray * (far_depth / depth)
                    ob.data.vertices[i*4+k].co = inverse_root @ world
                    mult.data[i*4+k].color = p['color'][:4]
                    offset.data[i*4+k].color = p['color'][4:]
            ob.data.update()
        bpy.context.view_layer.update()
