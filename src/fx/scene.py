"""Sample original PET AWP layers for the mesh renderer, retaining XYZ depth."""
import json
import math
import os

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
    for ri, recipe in enumerate(recipes):
        effect = awp.load(ensure_awp(recipe['name']))
        for li, layer in enumerate(effect.layers):
            cancel_check()
            image = textures.get(layer.texture_url)
            if textures.missing:
                raise ValueError('Missing original particle texture: ' + ', '.join(textures.missing))
            path = os.path.join(work, recipe['name'] + '_' + str(li) + '.png')
            image.save(path)
            particles = _build_particles(layer, 1701 + ri * 100 + li)
            inst = _layer_transform(layer)
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
                    # Full particle position is transformed in Blender with the
                    # same emitter matrix as its quad (including ice-cloud Y).
                    spin = 2 * math.pi * age / p.rot_cycle if p.rot_cycle > 0 else 0
                    row.append({'position': [x, y, z], 'size': [layer.geom_w * sx, layer.geom_h * sy],
                                'color': color, 'spin': spin, 'axis': p.rot_axis,
                                'heading': p.vel})
                samples.append(row)
            output.append({'name': recipe['name'] + '_' + layer.name, 'texture': path,
                           'blend': layer.blend_mode, 'repeat': layer.repeat, 'scale': recipe['scale'],
                           'position': recipe['position'],
                           'billboard': 'ParticleBillboardNodeSubParser' in layer.nodes,
                           'heading': 'ParticleRotateToHeadingNodeSubParser' in layer.nodes,
                           'samples': samples})
    path = os.path.join(work, 'particles.scene.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(output, f)
    return path
