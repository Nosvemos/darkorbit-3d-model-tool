"""Stage3D material equations from the bundled main.swf (see docs/06).

These are unlit node graphs: Blender must not apply a second BRDF, exposure,
or sRGB transfer. Texture samples and light colours are Stage3D numeric RGB.
"""
import math
import os

import bpy


def rgb(value):
    value = value.lstrip('#')
    return tuple(int(value[i:i + 2], 16) / 255 for i in (0, 2, 4))


class Graph:
    def __init__(self, material):
        self.nt = material.node_tree
        self.nt.nodes.clear()

    def node(self, kind):
        return self.nt.nodes.new('ShaderNode' + kind)

    def put(self, value, socket):
        if hasattr(value, 'node'):
            self.nt.links.new(value, socket)
        else:
            if socket.type == 'RGBA' and len(value) == 3:
                value = (*value, 1)
            socket.default_value = value

    def math(self, op, a, b=0, clamp=False):
        n = self.node('Math')
        n.operation = op
        n.use_clamp = clamp
        self.put(a, n.inputs[0])
        self.put(b, n.inputs[1])
        return n.outputs[0]

    def vec(self, op, a, b=(0, 0, 0)):
        n = self.node('VectorMath')
        n.operation = op
        self.put(a, n.inputs[0])
        self.put(b, n.inputs[3] if op == 'SCALE' else n.inputs[1])
        return n.outputs['Value' if op == 'DOT_PRODUCT' else 'Vector']

    def texture(self, path):
        if not path or not os.path.isfile(path):
            return None
        n = self.node('TexImage')
        # Separate datablock from the sRGB portable glTF material.
        n.image = bpy.data.images.load(path, check_existing=False)
        n.image.colorspace_settings.name = 'Non-Color'
        n.image.alpha_mode = 'CHANNEL_PACKED'
        n.extension = 'REPEAT'
        return n

    def output(self, color, alpha=1):
        emission = self.node('Emission')
        self.put(color, emission.inputs['Color'])
        transparent = self.node('BsdfTransparent')
        mix = self.node('MixShader')
        self.put(alpha, mix.inputs[0])
        self.put(transparent.outputs[0], mix.inputs[1])
        self.put(emission.outputs[0], mix.inputs[2])
        self.put(mix.outputs[0], self.node('OutputMaterial').inputs['Surface'])


def material(name, textures, cfg, appearance=None):
    mat = bpy.data.materials.new(name + '_Stage3D')
    mat.use_nodes = True
    mat.use_backface_culling = True
    mat['renderer'] = 'Away3D shader equations'
    g = Graph(mat)
    tex = {k: g.texture(v) for k, v in textures.items() if k != 'specular_pbr'}
    diffuse = tex.get('diffuse')
    base = diffuse.outputs['Color'] if diffuse else (1, 1, 1)
    # EntityBasicMaterial defaults alphaBlending=false. Mask methods kill
    # fragments; their fractional RGB multiplication must not be applied again
    # through Blender's alpha mixing.
    alpha = 1
    geometry = g.node('NewGeometry')
    normal = geometry.outputs['Normal']
    if tex.get('normal'):
        n = g.node('NormalMap')
        g.put(tex['normal'].outputs['Color'], n.inputs['Color'])
        normal = n.outputs['Normal']
    view = geometry.outputs['Incoming']
    color = base
    if cfg.get('light_quality') != 'low':
        t, p = map(math.radians, (cfg['sun_tilt'], cfg['sun_pan']))
        # ExtMath.tiltPan2Vector(t,p,-1), negate for surface-to-light;
        # apply the same Y-up -> Z-up basis as the mesh importer.
        light = (math.sin(t) * math.sin(p), math.cos(t),
                 math.sin(t) * math.cos(p))
        ndl = g.math('MAXIMUM', g.vec('DOT_PRODUCT', normal, light), 0)
        direct = g.vec('SCALE', rgb(cfg['sun_color']),
                       g.math('MULTIPLY', ndl, cfg['sun_energy']))
        ambient = tuple(c * cfg['ambient_strength'] for c in rgb(cfg['ambient_color']))
        half = g.vec('NORMALIZE', g.vec('ADD', light, view))
        ndh = g.math('MAXIMUM', g.vec('DOT_PRODUCT', normal, half), 0)
        gloss, strength = 50, cfg['specular_strength']
        if tex.get('specular'):
            split = g.node('SeparateXYZ')
            g.put(tex['specular'].outputs['Color'], split.inputs[0])
            gloss = g.math('MULTIPLY', split.outputs['Y'], 50)
            strength = g.math('MULTIPLY', split.outputs['X'], strength)
        spec = g.math('MULTIPLY', g.math('POWER', ndh, gloss), strength)
        specular = g.vec('SCALE', rgb(cfg['sun_color']), spec)
        if cfg.get('hero_light') or cfg.get('light_quality') == 'high':
            delta = g.vec('SUBTRACT', cfg.get('hero_position', (0, 0, 0)), geometry.outputs['Position'])
            dist2 = g.vec('DOT_PRODUCT', delta, delta)
            falloff = max(.001, float(cfg.get('hero_light_radius', 450)))
            attenuation = g.math('SUBTRACT', 1, g.math('DIVIDE', dist2, falloff * falloff), clamp=True)
            direction = g.vec('NORMALIZE', delta)
            ndp = g.math('MAXIMUM', g.vec('DOT_PRODUCT', normal, direction), 0)
            pc = rgb(cfg.get('hero_light_color', '#2e7dff'))
            direct = g.vec('ADD', direct, g.vec('SCALE', pc,
                g.math('MULTIPLY', attenuation, g.math('MULTIPLY', ndp, cfg.get('hero_light_energy', .6)))))
            hp = g.vec('NORMALIZE', g.vec('ADD', direction, view))
            ph = g.math('POWER', g.math('MAXIMUM', g.vec('DOT_PRODUCT', normal, hp), 0), gloss)
            ps = 1.5
            if tex.get('specular'):
                ps = g.math('MULTIPLY', split.outputs['X'], ps)
            specular = g.vec('ADD', specular, g.vec('SCALE', pc,
                g.math('MULTIPLY', attenuation, g.math('MULTIPLY', ph, ps))))
        direct = g.vec('MINIMUM', direct, (1, 1, 1))
        color = g.vec('ADD', g.vec('MULTIPLY', base, g.vec('ADD', direct, ambient)), specular)
    if tex.get('alpha'):
        mask = g.node('SeparateXYZ')
        g.put(tex['alpha'].outputs['Color'], mask.inputs[0])
        coverage = g.math('GREATER_THAN', mask.outputs['X'], .499999)
        alpha = g.math('MULTIPLY', alpha, coverage)
        color = g.vec('SCALE', color, mask.outputs['X'])
    if tex.get('glow'):
        color = g.vec('ADD', color, g.vec('SCALE', tex['glow'].outputs['Color'],
                                        cfg.get('emission_strength', 1)))
    if tex.get('ao'):
        color = g.vec('MULTIPLY', color, tex['ao'].outputs['Color'])
    if tex.get('gal'):
        split = g.node('SeparateXYZ')
        g.put(tex['gal'].outputs['Color'], split.inputs[0])
        alpha = g.math('MULTIPLY', alpha, g.math('GREATER_THAN', split.outputs['Y'], .499999))
        color = g.vec('SCALE', color, g.math('MULTIPLY', split.outputs['Y'], split.outputs['Z']))
        color = g.vec('MAXIMUM', color, g.vec('SCALE', base,
            g.math('MULTIPLY', split.outputs['X'], cfg.get('emission_strength', 1))))
    if appearance and appearance.get('rim_color'):
        ndv = g.math('MULTIPLY', g.vec('DOT_PRODUCT', normal, view), 1, clamp=True)
        rim = g.math('MULTIPLY', g.math('POWER', g.math('SUBTRACT', 1, ndv),
                                     appearance['rim_power']), appearance['rim_strength'])
        # The bundled RimLightMethod MIX first attenuates target by (1-r),
        # then mixes that attenuated target again. Do not clamp r (Frozen=2).
        inv = g.math('SUBTRACT', 1, rim)
        color = g.vec('ADD', g.vec('SCALE', color, g.math('MULTIPLY', inv, inv)),
                      g.vec('SCALE', rgb(appearance['rim_color']), rim))
    g.output(color, alpha)
    return mat


def apply(scene_data, cfg):
    sources = {o['name']: o for o in scene_data['objects']}
    for ob in list(bpy.context.scene.objects):
        src = sources.get(ob.name)
        if ob.type != 'MESH' or not src or not src.get('textures'):
            continue
        appearance = scene_data.get('appearance') if not src.get('overlay') else None
        ob.data.materials.clear()
        ob.data.materials.append(material(ob.name, src['textures'], cfg, appearance))
        if appearance and appearance.get('outline_size'):
            outline(ob, appearance)


def outline(ob, appearance):
    """OutlinePass: expand local vertices along normals; cull front faces."""
    hull = ob.copy()
    hull.data = ob.data.copy()
    hull.name = ob.name + '_outline'
    bpy.context.scene.collection.objects.link(hull)
    size = appearance['outline_size']
    for vertex in hull.data.vertices:
        vertex.co += vertex.normal * size
    hull.data.update()
    mat = bpy.data.materials.new(hull.name)
    mat.use_nodes = True
    g = Graph(mat)
    g.output(rgb(appearance['rim_color']), g.node('NewGeometry').outputs['Backfacing'])
    hull.data.materials.clear()
    hull.data.materials.append(mat)
