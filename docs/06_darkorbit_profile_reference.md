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
| `specular` | `1.1` | `specular_strength: 1.1` | Specular-light multiplier |
| `tilt` | `100` | `sun_tilt: 100` | Directional light orientation |
| `pan` | `35` | `sun_pan: 35` | Directional light orientation |

The color and direction values transfer directly. Away3D's `diffuse` and `ambient`
are not numerically equivalent to Blender's light energy and world strength, so
their numeric settings remain practical approximations. EEVEE does not use its
World surface as ambient irradiance; the render path therefore adds the map's
ambient color as a diffuse-colored fill term. The specular scalar is applied
separately from the material's specular map.

The upstream [Away3D `BasicSpecularMethod` source](https://github.com/away3d/away3d-core-fp11/blob/master/src/away3d/materials/methods/BasicSpecularMethod.as)
defines the specular map's red channel as highlight strength and green channel
as gloss. Before GLB export, the pipeline packs strength into the alpha channel
and converts gloss to the glTF roughness channel. This avoids losing the gloss
conversion when the renderer imports the generated GLB.
AWD vertex normals are also carried through the scene JSON and applied as custom
split normals when present. Some ship files (including the base Goliath AWD)
omit a normal stream and continue to use normals derived from the mesh.
The sprite renderer rebuilds the specular response as a separate, calibrated
Phong-like lobe because Principled's dielectric specular is too weak for the
source map weights. This is a visual approximation; the supplied client dump
does not contain DarkOrbit's material shader implementation.

Map-specific entries elsewhere in the same XML intentionally use different
colors and directions. This preset represents the repeated baseline lighting,
not every DarkOrbit map.

## Camera evidence boundary

The supplied `reference/client/_extracted` tree contains 34 AS3 files, all
Flex/Flash watcher setup utilities; it does not include DarkOrbit's Away3D
camera or lighting implementation. The accompanying map XML has scene lighting
and camera zones, but it does not establish the observer's initial tilt/pan or
lens settings. The 30-degree FOV and camera tilt/pan values remain unverified
against the DarkOrbit implementation.
