"""Sample original PET AWP layers for the mesh renderer, retaining XYZ depth."""
import json
import math
import os
from copy import deepcopy

from src import config
from src.fx_render import ensure_awp
from . import awp
from .render import _build_particles, _layer_transform, _state, TextureCache


def prepare(recipes, work, cfg, cancel_check):
    textures = TextureCache(config.FX_DIR, config.TEXTURES_DIR)
    output = []
    frames = int(cfg['frames'])
    fps = float(cfg.get('effect_fps', 30))
    start = float(cfg.get('effect_time', 2))
    if not math.isfinite(fps) or fps <= 0 or not math.isfinite(start) or start < 0:
        raise ValueError('Effect FPS must be positive and time must be nonnegative and finite')
    recipes = deepcopy(recipes)
    # Art-directed additions are explicit and can be disabled for raw source output.
    style = cfg.get('effect_style', 'softened')
    if style not in ('softened', 'source'):
        raise ValueError('Effect style must be softened or source')
    softened = style == 'softened'
    if softened:
        for recipe in list(recipes):
            if recipe['name'] == 'fire_trail':
                scale = recipe['scale'][0]
                recipes.append({'name':'ice_cloud', 'scale':[scale*.65,scale*.3,scale*.65],
                                'position':[0,-12,0], 'tint':[1.,.24,.025], 'opacity':.65})
    for ri, recipe in enumerate(recipes):
        effect = awp.load(ensure_awp(recipe['name']))
        for li, layer in enumerate(effect.layers):
            cancel_check()
            image = textures.get(layer.texture_url)
            if textures.missing:
                raise ValueError('Missing original particle texture: ' + ', '.join(textures.missing))
            path = os.path.join(work, str(ri) + '_' + recipe['name'] + '_' + str(li) + '.png')
            image.save(path)
            particles = _build_particles(layer, 1701 + ri * 100 + li)
            inst = _layer_transform(layer)
            if recipe.get('center_on_mesh'):
                # Remove the AWP layer's fixed offset (the glow is Y=-50).
                # Preserve animated particle motion and anchor in Blender.
                inst = ((0., 0., 0.), *inst[1:])
            samples = []
            for fi in range(frames):
                cancel_check()
                t = start + fi / fps
                row = []
                for p in particles:
                    state = _state(p, layer, inst, t, depth=True)
                    if state is None:
                        row.append(None)
                        continue
                    x, y, sx, sy, color, angle, life, age, uv, z = state
                    color = list(color)
                    if recipe.get('tint'):
                        # Recolour both multiplier and additive offsets; multiplying
                        # blue source channels by yellow would lose the effect.
                        intensity = max(color[:3])
                        offset = max(color[4:7])
                        color[:3] = [intensity*c for c in recipe['tint']]
                        color[4:7] = [offset*c for c in recipe['tint']]
                    opacity = recipe.get('opacity', 1.)
                    color[3] *= opacity
                    color[7] *= opacity
                    size = .48 if softened and recipe['name'] == 'frost_ship_trail' and layer.name == 'glow' else 1.
                    # Full particle position is transformed in Blender with the
                    # same emitter matrix as its quad (including ice-cloud Y).
                    spin = 2 * math.pi * age / p.rot_cycle if p.rot_cycle > 0 else 0
                    row.append({'position': [x, y, z], 'size': [layer.geom_w * sx * size, layer.geom_h * sy * size],
                                'color': color, 'spin': spin, 'axis': p.rot_axis,
                                'heading': p.vel})
                samples.append(row)
            output.append({'name': recipe['name'] + '_' + layer.name, 'texture': path,
                           'blend': layer.blend_mode, 'repeat': layer.repeat, 'scale': recipe['scale'],
                           'position': [0,0,0] if recipe.get('center_on_mesh') else recipe['position'],
                           'center_on_mesh': recipe.get('center_on_mesh', False), 'soft_edges': softened,
                           'tint_texture': bool(recipe.get('tint')),
                           'billboard': 'ParticleBillboardNodeSubParser' in layer.nodes,
                           'heading': 'ParticleRotateToHeadingNodeSubParser' in layer.nodes,
                           'samples': samples})
    path = os.path.join(work, 'particles.scene.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(output, f)
    return path
