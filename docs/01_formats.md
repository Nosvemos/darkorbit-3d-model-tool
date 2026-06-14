# Binary Format Findings

> This file was derived from hexdump + decompress experiments performed on the actual files.
> Details will be verified/expanded during the full parse implementation.

## AWD (`meshes/*.awd`)

DarkOrbit uses the Away3D engine → the files are in **AWD2** format,
an "AWDc" variant with a zlib-compressed body.

### Header (12 byte)
```
offset  bytes              meaning
0x00    41 57 44 63        magic "AWDc"
0x04    01                 version major
0x05    e0 00              flags (uint16) — to be verified
0x07    01                 compression = 1 (zlib)
0x08    51 ca 01 00        uncompressed length (uint32 LE) = 117329
0x0C    78 da ...          zlib deflate stream (start of body)
```

### Verified behavior (cubikon.awd)
- File size: 117341 byte.
- `zlib.decompress(data[12:])` → **226821 byte** decompressed body.
- Start of decompressed body: `01 00 00 00 00 ff 00 46 ...`
- ASCII inside: `AwayBuilder`, `1.0.0` → generator metadata block present.

### Body = AWD2 block list
AWD2 block structure (each block):
```
uint32  block id
uint8   namespace
uint8   type        (e.g.: TriangleGeometry, Container, MeshInstance, Material, Texture...)
uint8   flags
uint32  length
bytes   data[length]
```
The parser reads these blocks in order and:
- **Geometry blocks** → vertex/index/uv/normal streams.
- **Container/SceneGraph blocks** → nodes named `main`, `engine_*`, `laserpoint_*` + transform matrices.
- **Material/Texture blocks** → which mesh uses which texture (name matching
  is already consistent with the texture file names: `cubikon_diffuse_512` etc.).

> Note: The full AWD2 block type table will be taken from the Away3D AWD2 specification. The
> critical block types for us are: geometry in namespace 0, scene-graph container, mesh instance.

## ATF (`textures/*.atf`)

Adobe Texture Format — a GPU-friendly compressed texture container.

### Header (cubikon_diffuse_512.atf)
```
offset  bytes              meaning
0x00    41 54 46           magic "ATF"
0x03    00 00 00 ff 02 ... format/length/version fields (to be verified)
```

### Known facts
- ATF blocks may be one of the DXT (S3TC: BC1/BC3), PVRTC or ETC subformats;
  the PC client most likely uses **DXT**.
- Each mipmap level may be raw or additionally compressed with **LZMA / JPEG-XR**.
- The `textures/temp_lzma_*.bin` files → indicate that in a previous session an attempt was made
  to extract the **LZMA block** inside the ATF (LZMA compression present).
- `cubikon_diffuse_512.png` already exists → the reference output of a manual ATF2PNG conversion
  (can be used as a comparison sample for decoder verification).

### Decode chain (target)
```
.atf → header parse → subformat + mip table
     → each mip: (if present) LZMA/JPEG-XR decompress
     → DXT/BC decode → RGBA pixel
     → write .png with PIL
```

### Cleanup
`textures/temp_lzma_*.bin` (5 files) are now leftover temporary experiment artifacts — they can be
deleted once the pipeline is set up. For now they are left in place as reference.
