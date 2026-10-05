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
        if (any(recipe['name'] == 'fire_trail' for recipe in recipes)
                and not any(recipe['name'] == 'ice_cloud' for recipe in recipes)):
            fire = next(recipe for recipe in recipes if recipe['name'] == 'fire_trail')
            scale = fire['scale'][0]
            recipes.append({'name':'ice_cloud', 'scale':[scale*.65,scale*.3,scale*.65],
                            'position':[0,-12,0], 'tint':[1.,.24,.025], 'opacity':.65,
                            'center_on_mesh': fire.get('center_on_mesh', False),
                            'scale_to_mesh': fire.get('scale_to_mesh', False)})
    for ri, recipe in enumerate(recipes):
        effect = awp.load(ensure_awp(recipe['name']))
        for li, layer in enumerate(effect.layers):
            if recipe.get('layers') and layer.name not in recipe['layers']:
                continue
            cancel_check()
            image = textures.get(layer.texture_url)
            if textures.missing:
                raise ValueError('Missing original particle texture: ' + ', '.join(textures.missing))
            path = os.path.join(work, str(ri) + '_' + recipe['name'] + '_' + str(li) + '.png')
            image.save(path)
            spark_multiplier = 3 if (softened and recipe.get('center_on_mesh') and
                                     'sparcl' in layer.name) else 1
            particles = _build_particles(layer, 1701 + ri * 100 + li,
                                         count_multiplier=spark_multiplier)
            inst = _layer_transform(layer)
            if recipe.get('center_on_mesh'):
                # Remove the AWP layer's fixed offset (the glow is Y=-50).
                # Preserve animated particle motion and anchor in Blender.
                inst = ((0., 0., 0.), *inst[1:])
            cloud = (softened and recipe.get('center_on_mesh') and
                     'ParticleBillboardNodeSubParser' in layer.nodes and
                     ('cloud' in layer.name or layer.name == 'glow'))
            round_halo = cloud and layer.name == 'glow'
            if round_halo:
                # One centred carrier gives a circular cloud with a stronger
                # core; four displaced glow disks make an oversized lumpy ring.
                particles = particles[:1]
            cloud_offsets = []
            if cloud:
                count = len(particles)
                radius = .30 * max(layer.geom_w, layer.geom_h)
                for index in range(count):
                    angle = index * math.pi * (3.0 - math.sqrt(5.0))
                    distance = radius * math.sqrt((index + .5) / count)
                    cloud_offsets.append((math.cos(angle) * distance, math.sin(angle) * distance))
                mean_x = sum(x for x, _ in cloud_offsets) / count
                mean_z = sum(z for _, z in cloud_offsets) / count
                cloud_offsets = [(x - mean_x, z - mean_z) for x, z in cloud_offsets]
            samples = []
            for fi in range(frames):
                cancel_check()
                t = start + fi / fps
                row = []
                for particle_index, p in enumerate(particles):
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
                    if cloud:
                        # Stable emitter-local disk offsets spread the mist instead of
                        # stacking every additive quad on the same bright centre.
                        count = len(particles)
                        x += cloud_offsets[particle_index][0]
                        z += cloud_offsets[particle_index][1]
                        # Reduce additive overlap in densely populated layers;
                        # preserve hue and the original lifetime curves.
                        density_normalizer = math.sqrt(count)
                        color[3] /= density_normalizer
                        color[7] /= density_normalizer
                    size = .50 if round_halo else (
                        .48 if softened and recipe['name'] == 'frost_ship_trail' and layer.name == 'glow' else 1.)
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
                           'distributed_cloud': bool(cloud),
                           'round_halo': bool(round_halo),
                           'tint_texture': bool(recipe.get('tint')),
                           'billboard': 'ParticleBillboardNodeSubParser' in layer.nodes,
                           'heading': 'ParticleRotateToHeadingNodeSubParser' in layer.nodes,
                           'samples': samples})
    path = os.path.join(work, 'particles.scene.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(output, f)
    return path
