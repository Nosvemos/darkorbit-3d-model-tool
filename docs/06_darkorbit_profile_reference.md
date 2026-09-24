# DarkOrbit Render Profile Reference

## Lighting values checked against the client data

The read-only reference file `NosGalaxy_2012/reference/client/spacemap/graphics/maps-config.xml`
contains 3D map lighting entries. The baseline entries for the standard home maps
(for example `map_1-1`, `map_2-1`, and `map_3-1`) repeat these values:

| Client field | Client value | Tool setting | Interpretation |
|---|---:|---|---|
| `color` | `0xA3FFFF` | `sun_color: #a3ffff` | Directional light color |
| `diffuse` | `0.8` | `sun_energy: 0.8` | Blender energy approximation |
| `ambientColor` | `0xFF855C` | `world_color: #ff855c` | Ambient/world color |
| `ambient` | `0.5` | `world_strength: 0.5` | Blender strength approximation |
| `tilt` | `100` | `sun_tilt: 100` | Directional light orientation |
| `pan` | `35` | `sun_pan: 35` | Directional light orientation |

The color and direction values transfer directly. Away3D's `diffuse` and `ambient`
are not numerically equivalent to Blender's light energy and world strength, so
the numeric settings preserve the source scalars as practical starting points,
not as a claim of pixel-identical illumination. The XML also specifies
`specular="1.1"`; the current render profile does not apply this as a separate
light multiplier. The imported material's specular texture remains connected to
the Principled BSDF by `src/blender/build_scene.py`.

Map-specific entries elsewhere in the same XML intentionally use different
colors and directions. This preset represents the repeated baseline lighting,
not every DarkOrbit map.

## Camera evidence boundary

The supplied `reference/client/_extracted` tree is a partial export: its current
AS3 files do not include the Away3D camera or lighting implementation. The
accompanying map XML has scene descriptors and camera zones, but it does not
establish the 3D observer's initial tilt/pan or lens settings. This change leaves
the existing 30-degree FOV and camera tilt/pan values untouched; those values
were not independently confirmed from this partial export.
