# DarkOrbit Render Profile Reference

## Lighting values checked against the client data

The read-only reference file `NosGalaxy_2012/reference/client/spacemap/graphics/maps-config.xml`
contains 3D map lighting entries. The baseline entries for the standard home maps
(for example `map_1-1`, `map_2-1`, and `map_3-1`) repeat these values:

| Client field | Client value | Tool setting | Interpretation |
|---|---:|---|---|
| `color` | `0xA3FFFF` | `sun_color: #a3ffff` | Directional light color |
| `diffuse` | `0.8` | `sun_energy: 0.4` | Tuned Blender direct-light energy; units differ |
| `ambientColor` | `0xFF855C` | `world_color: #ff855c` | Recorded map/world color |
| `ambient` | `0.5` | `world_strength: 0.5`; `ambient_strength: 0.2` | World/background value plus tuned material fill |
| `specular` | `1.1` | `specular_strength: 0.4` | Tuned with the renderer's separate specular lobe |
| `tilt` | `100` | `sun_tilt: 100` | Directional light orientation |
| `pan` | `35` | `sun_pan: 35` | Directional light orientation |

The map values are retained separately from the material fill used by the
renderer. EEVEE does not use its World surface as ambient irradiance, and the
supplied client dump does not include DarkOrbit's material shader. Applying the
map's warm `ambientColor` directly to the current Goliath diffuse atlas turned
its blue-grey source palette brown. The previous direct and specular settings
also made the rendered albedo too bright and neutral. The DarkOrbit render
profile keeps the XML ambient values as world/background settings and uses a
renderer-specific cool material fill (`ambient_color: #aed3ff`,
`ambient_strength: 0.2`), `sun_energy: 0.4`, and `specular_strength: 0.4`.
These are visual approximations tuned against the source Goliath ATF palette,
not values extracted from the game. The specular response remains separate
from the material's specular map.

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
