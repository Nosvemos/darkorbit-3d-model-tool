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
    def __init__(self, path, root, camera):
        self.root, self.camera = root, camera
        export_alpha()
        self.layers = []
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
            color = g.vec('ADD', g.vec('MULTIPLY', tex.outputs['Color'], m.outputs['Color']), o.outputs['Color'])
            alpha = g.math('ADD', g.math('MULTIPLY', tex.outputs['Alpha'], m.outputs['Alpha']), o.outputs['Alpha'], clamp=True)
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
        for layer, ob, mult, offset in self.layers:
            emitter = self.root.matrix_world @ AXIS @ Matrix.Translation(Vector(layer['position'])) @ Matrix.Diagonal((*layer['scale'], 1))
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
                    ob.data.vertices[i*4+k].co = inverse_root @ world
                    mult.data[i*4+k].color = p['color'][:4]
                    offset.data[i*4+k].color = p['color'][4:]
            ob.data.update()
        bpy.context.view_layer.update()
