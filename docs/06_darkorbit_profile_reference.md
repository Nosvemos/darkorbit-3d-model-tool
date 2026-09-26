# DarkOrbit rendering: source audit and implementation

## Evidence (2026-09-26)

Reference: `C:/Users/PC/Desktop/NosGalaxy_2012/reference/client/spacemap/main.swf`.
SHA-256: `4010085bbe313f68fc2cf1e26ca89091619f3ca7195194e7ec8daecca94c7b58`.

The earlier statement that this client lacked the rendering classes was wrong.
The pre-existing extracted directory was incomplete. FFDec's `-dumpAS3` found
the classes in main.swf and targeted extraction recovered their implementations.
The extracted files are in ignored `out/reference-as3/scripts/`; they are study
material, not runtime dependencies or files to redistribute with the tool.

Reproduce from the supplied SWF (Java and the existing FFDec jar):

```powershell
java -jar C:/Users/PC/Desktop/NosGalaxy_2012/tools/ffdec.jar -selectclass 'net.bigpoint.darkorbit.map.view3D.++,away3d.materials.methods.++,away3d.materials.passes.++,away3d.lights.++,away3d.cameras.lenses.++' -export script out/reference-as3 C:/Users/PC/Desktop/NosGalaxy_2012/reference/client/spacemap/main.swf
```

Relevant classes under `net/bigpoint/darkorbit/map/view3D/`:

- `utils/Observer3D.as`: `validate`, start distance 1740, tilt 135, FOV 30.
- `utils/CameraManager3D.as`: map pan 25, lookAt, lens clipping and zoom.
- `utils/ExtMath.as`: exact tilt/pan-to-vector formula.
- `settings/LightSettings.as`: apply light scalars and direction.
- `display3D/LightsManager.as`: low = no lights; medium = sun; high = sun + hero.
- `display3D/materials/EntityBasicMaterial.as`: shader setup, gloss 50,
  specularity 1, ATF sampling, supported channels and effect ordering.
- `display3D/materials/methods/GlowMethod.as`, `AlphaMaskMethod.as`,
  `CombinedGALMethod.as`: emission, red-channel mask and packed GAL processing.
- `display3D/ship/Ship3D.as`: heading minus 90 degrees about Away3D Y.

Also inspected `away3d/materials/methods/{BasicAmbientMethod,BasicDiffuseMethod,
BasicSpecularMethod,RimLightMethod}.as`, `away3d/materials/passes/OutlinePass.as`,
and particle billboard/heading/rotation nodes and states. `UberDisplayTrait`
reads visualSize for visual bounds; it is not a model scale instruction.

## Camera and handedness

`Observer3D.validate` places the camera relative to its target at:

```
x = distance * sin(tilt) * sin(pan)
y = -distance * cos(tilt)
z = -distance * sin(tilt) * cos(pan)
distance = 1740 / zoom
limitedTilt = tilt - clamp((zoom - 1) / 2 * 20, 0, 20)
```

There is no extra 180-degree pan offset. Away3D to Blender conversion is
`(x,z,y)`, including its reflection, for geometry, normals, lights, camera and
particles. A rotation alone produces the wrong screen handedness. The model
rotates about the entity origin, not its bounding-box centre.

Default `sprite` framing crops/enlarges the projection at the game distance;
it does not dolly the camera close to the object. `native` framing uses the
full configured FOV. Thus sprite output pixel size is an export choice, not a
claim about the game's full viewport resolution. Explicit distance/FOV remain
editable. Zoom is limited to 1..3 as in the normal client setting.

## Light and colour equations

Default profile is specifically **map 1-1**, from `spacemap/graphics/maps-config.xml`:

| Parameter | Source value |
| --- | --- |
| Directional RGB | A3FFFF |
| Diffuse | 0.8 |
| Specular | 1.1 |
| Ambient RGB | FF855C |
| Ambient | 0.5 |
| Tilt / pan | 100 / 35 |

Other maps can have different values. The former cool ambient AED3FF, diffuse
0.4, specular 0.4 and extra glossy-lobe calibration factor were removed.

`src/blender/away_material.py` constructs explicit arithmetic shader nodes.
Blender emission is used only to output the calculated result; EEVEE's PBR BRDF
and world irradiation do not light these materials a second time.

For the default opaque material:

```
L = -LightSettings.direction
H = normalize(L + V)
diffuseLight = saturate(sum(lightRGB * diffuse * max(dot(N,L),0)))
C = albedo * (ambientRGB * ambient + diffuseLight)
C += sum(lightRGB * lightSpecular * map.R * max(dot(N,H),0) ** (50 * map.G))
C += glowTexture * glowParameter
```

Normal maps supply N. High quality adds the hero point light with source colour
2E7DFF, diffuse 0.6, specular 1.5, radius 0 and falloff 450 using the squared-distance
attenuation. Its default position is the entity origin (isolated hero preview).
Low quality follows the no-lights material path. Alpha masks use **R**, with the
source 0.5 kill threshold; GAL uses R for glow, G for alpha, B for lightmap.

ATF samples and hexadecimal light colours are numeric Stage3D RGB. Textures are
Non-Color and output uses Raw, with no extra sRGB decoding/encoding or filmic
look. Switching to Standard/AgX is an intentional departure from this profile.
The portable glTF material remains a PBR approximation, separate from the
reference shader in the packed Blender scene.

## PET recipes

Source: `_extracted/main_xml_current/ships.xml`, assets 160 and 189.
Both designs use **pet-15** geometry and ordinary `pet` ATFs, regardless of the
input PET level. `visualSize` is retained as metadata, not applied as scale.

| Recipe | Rim RGB / strength / power | Outline size | AWP attachments |
| --- | --- | --- | --- |
| Frozen | 33CCFF / 2 / 2 | 1.5 | frost_ship_trail scale .6; ice_cloud position Y=-30, scale (.8,.2,.8) |
| Inferno | FF0000 / 1 / 1 | .25 | fire_trail scale 1.5 |

Bundled `RimLightMethod` defaults to MIX. Its actual AGAL first attenuates the
incoming colour and then mixes again:

```
r = strength * (1 - saturate(dot(N,V))) ** power
Cout = Cin * (1-r) ** 2 + rimRGB * r
```

The intermediate r is not clamped; this matters for Frozen strength 2. The
previous Fresnel ramp and arbitrary start/end thresholds were incorrect.
OutlinePass expands local positions by vertex normal * size and culls front
faces. The Blender hull uses the same expansion and backface visibility.

Normal PET Legend has no asset recipe in this supplied client. The Legend
shader exists (FFD135 / 9 / 2.5), but the PET recipes referencing it use other
geometries such as Chimera and Mirage. The requested yellow normal-PET variant is
now available as `pet-legend`, explicitly labelled custom. It uses the normal
PET maps, yellow rim (strength 2, power 2) and recoloured Frozen particles; it
is not presented as a discovered original asset.

## Particles and outputs

`src/fx/scene.py` samples the original AWP data; `away_particles.py` builds the
quads in the same scene. XYZ motion, plane sizes, original ATFs, colour tracks,
rotation, emitter transforms and depth occlusion are retained. Billboard
rotation follows the view; nonuniform emitter scale stays in emitter axes.
Sphere sampling follows the actual volume/cube-normalization setter. Follow
has no positional history for this stationary turntable preview.

The particle shader uses additive transparent + emission with BLENDED surfaces;
dithered transparency would discard its zero-alpha emission. A compositor
preserves additive radiance when writing RGBA. A conventional PNG cannot retain
ONE/ONE blending on every future background: the exported covering alpha matches
the rendered result over black. The Blender scene retains the additive material.

`convert` and `render` write packed `.blend` files with source materials, camera
and the chosen particle-time snapshot. GLB/glTF/OBJ remain portable base-model
exports. The turntable renderer samples the particle timeline per frame; the
saved .blend snapshot is not an exported procedural AWP simulator.

Examples:

```powershell
python -m src render pet-15 --design pet-frozen --frames 32 --resolution 768 --output-name pet-frozen
python -m src render pet-15 --design pet-inferno --effect-time 2 --effect-fps 30 --frames 32 --output-name pet-inferno
python -m src convert pet-15 --design pet-inferno --output-name pet-inferno-model
python -m src render goliath --camera-framing native --cam-zoom 1 --resolution 1024
```

## Scope of parity

This reproduces the inspected camera and basic ship shader equations and the
listed PET recipes, not the entire running game. There is no captured live-game
frame with matching map, viewport, heading, quality, time and random particle
seed for a pixel comparison. EEVEE rasterization, tangent generation, filtering
and hull overlap/stencil behaviour can differ from Stage3D. Dynamic map combat
lights, engine trails and movement history are not synthesized for an isolated
stationary model. Do not describe output as pixel-identical without that comparison.


## Ship designs and softened effects (2026-09-26)

The design picker is populated from the server registry for the selected AWD.
The five supported AWDs are `goliath-solace`, `goliath-spectrum`,
`goliath-sentinel`, `goliath-diminisher`, and `goliath-venom`.

| Ship | Frozen / Frost maps | Inferno maps | Legend maps |
| --- | --- | --- | --- |
| Solace | solace-frost diffuse + glow | goliath-solace-blaze diffuse | No normal-ship recipe in inspected XML |
| Spectrum | Shared base maps | Shared base maps | spectrum-design-legend diffuse + glow |
| Sentinel | Shared base maps | Shared base maps | goliath-sentinel_design_legend diffuse + glow + specular |
| Diminisher | diminisher-frost diffuse + glow; no normal/specular maps | Shared base maps | ship_diminisher_design_legend diffuse + glow |
| Venom | Shared base maps | Shared base maps | No normal-ship recipe in inspected XML |

Unchanged channels are inherited except for Diminisher Frost, which replaces
`texture` itself. `PrefabMaterialManager.assembleTextureResKey` resolves the
per-channel attribute, then `texture`, then `geometry`; it does not fall back
to base-ship normal/specular maps after a whole texture-set replacement.
The resource manifest and local texture directory contain only diffuse/glow
for `diminisher-frost`. Explicit `none` overrides suppress those absent channels.
No remote ATF downloads were required: all referenced maps were already local.
Solace-plus Legend is a different geometry and is not substituted for Solace.

The source XML mesh scale is applied to ship geometry and hardpoints: .85 for
Solace/Sentinel/Venom/Spectrum and .7 for Diminisher. Source particle emitter
scales and positions remain independent. Legend ship rim parameters are the
source FFD135 / 9 / 2.5, without an outline or invented particle layer.

`effect_style=softened` is the default requested visual adjustment:

- Frozen's 400-unit glow planes use 48% size; spark geometry is unchanged.
- All particle quads have a circular smoothstep alpha falloff before the edges.
- Inferno adds a scattered warm recolouring of `ice_cloud` at reduced opacity.
- Custom PET Legend recolours both texture intensity and particle colour tracks,
  preserving alpha rather than multiplying yellow into blue texture channels.

Choose **effects: source** or `--effect-style source` for the original particle
sizes/layers and unmodified edge alpha. This option does not make the custom
PET Legend an original game design. The appearance adjustments remain in the
packed Blender scene and sprite output; portable GLB does not encode AWP effects.
Manual texture edits still override presets; automatically displayed base maps
are no longer sent back as manual overrides masking a design's textures.

Examples:

```powershell
python -m src render pet-15 --design pet-legend --frames 4 --output-name pet-legend
python -m src render goliath-sentinel --design sentinel-frozen --frames 4
python -m src render goliath-spectrum --design spectrum-legend --frames 4
python -m src render goliath-solace --design solace-inferno --effect-style source --frames 4
```


## Tunable base-texture presets

The unsuffixed design IDs (`spectrum-legend`, `solace-inferno`, etc.) now select
custom, tunable presets. All five ship families and normal PET have Frozen,
Inferno and Legend variants: 18 presets total. These use base textures, with
no design-specific diffuse or glow dependency. Solace/Venom Legend are explicitly
custom variants. Source recipes from the table above remain selectable with
`-source` appended; no nonexistent source Legend recipe is invented.

All tunable presets share the family's Frozen `frost_ship_trail` and `ice_cloud`
emitters, recoloured blue/orange/gold. Softened edges remain the default. Body
colour blends the lit surface toward colour times its brightest RGB channel, preserving
texture detail and light/shadow modulation. Rim remains a separate contribution.
Portable GLB still carries the base material; these procedural adjustments are
stored in the packed `.blend` and rendered PNGs.

| Control / CLI flag | Range | Purpose |
| --- | --- | --- |
| `--design-color` | #RRGGBB | Body and rim colour; mist follows unless overridden |
| `--body-tint` | 0–1 | Blend from original surface to tinted peak-channel brightness |
| `--rim-strength` | 0–12 | Rim intensity |
| `--rim-power` | 0.1–12 | Rim falloff; larger values concentrate it nearer the silhouette |
| `--particle-color` | #RRGGBB | Independent mist colour |
| `--particle-intensity` | 0–5 | Particle opacity multiplier; zero hides particles |
| `--particle-scale` | 0.1–4 | Emitter extent and particle size multiplier |

These controls apply to both Render and Convert. The picker loads preset defaults;
Reset preset restores them. Only changed appearance values are submitted as overrides.
Preset rim strengths are Frozen 2, Inferno 1.5, Legend 7, with powers 2/1/2.5;
body tint strengths are .35/.55/.70. Inferno uses pure #FF0000. Recolouring
preserves peak-channel brightness instead of luminance-weighted darkening.
Source recipes retain their original values.

```powershell
python -m src render goliath-venom --design venom-legend --design-color '#FFD135' --body-tint .8 --rim-strength 1.8 --particle-intensity 1.2
python -m src convert goliath-spectrum --design spectrum-legend --particle-color '#FFC850' --particle-scale 1.1
python -m src render goliath-spectrum --design spectrum-legend-source --effect-style source
```


### Mist centering

Tunable presets anchor emitters to the imported hull bounds centre, measured
before outline or particles are added. Both the recipe offset (`ice_cloud`
Y=-30) and fixed AWP layer translation (glow Y=-50) are removed for these
presets. Animated motion, emitter scale, colours, and intensity are unchanged.
The anchor is in the turntable root's local coordinates, so it rotates with the
ship. Camera fitting includes the same anchor. Source recipes retain their
original offsets. This applies to sprite renders and packed Blender snapshots.


### Hull visibility through mist

For centred tunable effects, billboard cloud/halo quads are moved behind the
furthest visible hull bound along camera viewing rays. The bound is recomputed
per frame, including turntable rotation. Perspective ray projection preserves
the apparent centre and size; orthographic cameras use a parallel depth offset.
The hull then occludes the mist with ordinary depth testing. Non-billboard sparks
keep their original depth, and source recipes keep their original placement.
