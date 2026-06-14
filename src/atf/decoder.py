"""ATF (Adobe Texture Format) decoder for DarkOrbit '.atf' textures.

These assets use ATF format 2 ("compressed") which, on desktop, stores a DXT1
texture split into two length-prefixed blocks (big-endian UI32 length each):

    block 0 : raw LZMA stream -> DXT1 colour indices (4 bytes per 4x4 block)
    block 1 : JPEG-XR image   -> DXT1 colour endpoints, as 2 RGB pixels per block
              laid out as two stacked planes: top = colour0, bottom = colour1.

Adobe stores the endpoints lossily as full RGB888 (not RGB565), so we decode
straight to RGBA by interpolating the two endpoints per the 2-bit indices,
skipping the RGB565 round-trip for better quality.

Header (16 bytes here): 'ATF', then at offset 12: format(u8), width(log2 u8),
height(log2 u8), mip count(u8). data[6]==0xFF marks the new header (offset 12).
"""
from __future__ import annotations

import lzma
import struct

import imagecodecs
import numpy as np

ATF_SIG = b"ATF"


class ATFError(Exception):
    pass


def _parse_header(d: bytes):
    if d[:3] != ATF_SIG:
        raise ATFError(f"not an ATF file (sig={d[:3]!r})")
    base = 12 if d[6] == 0xFF else 6
    fmt = d[base] & 0x7F
    width = 1 << d[base + 1]
    height = 1 << d[base + 2]
    mips = d[base + 3]
    return fmt, width, height, mips, base + 4


def _blocks(d: bytes, off: int):
    """Yield each big-endian UI32 length-prefixed block payload."""
    while off + 4 <= len(d):
        blen = struct.unpack_from(">I", d, off)[0]
        if blen == 0 or off + 4 + blen > len(d):
            break
        yield d[off + 4:off + 4 + blen]
        off += 4 + blen


def _lzma_raw(block: bytes, max_out: int) -> bytes:
    """Decode an ATF raw-LZMA block: 1 prop byte + 4-byte dict size + stream."""
    props = block[0]
    dict_size = struct.unpack_from("<I", block, 1)[0]
    filt = [{"id": lzma.FILTER_LZMA1, "dict_size": dict_size,
             "lc": (props % 45) % 9, "lp": (props % 45) // 9, "pb": props // 45}]
    dec = lzma.LZMADecompressor(format=lzma.FORMAT_RAW, filters=filt)
    return dec.decompress(block[5:], max_out)


def _decode_dxt1(endpoints: np.ndarray, index_bytes: bytes,
                 width: int, height: int) -> np.ndarray:
    """Rebuild an RGB image from DXT1 endpoint planes + colour indices.

    endpoints : (2*bh, bw, 3) uint8 — stacked colour0 / colour1 planes.
    index_bytes: bw*bh*4 bytes — 4 bytes per block, one per pixel row, 2 bits/pixel.
    """
    bw, bh = width // 4, height // 4
    c0 = endpoints[:bh].astype(np.int32)            # (bh, bw, 3)
    c1 = endpoints[bh:2 * bh].astype(np.int32)
    # palette per block: [c0, c1, (2c0+c1)/3, (c0+2c1)/3]
    pal = np.stack([c0, c1, (2 * c0 + c1) // 3, (c0 + 2 * c1) // 3], axis=2)  # (bh,bw,4,3)

    idx = np.frombuffer(index_bytes, np.uint8, count=bw * bh * 4).reshape(bh, bw, 4)
    sel = (idx[..., None] >> np.array([0, 2, 4, 6], np.uint8)) & 3   # (bh,bw,4rows,4cols)
    sel = sel.reshape(bh, bw, 16)                                    # row-major in block

    rows = np.arange(bh)[:, None, None]
    cols = np.arange(bw)[None, :, None]
    px = pal[rows, cols, sel]                       # (bh, bw, 16, 3)
    px = px.reshape(bh, bw, 4, 4, 3).transpose(0, 2, 1, 3, 4)
    return px.reshape(height, width, 3).astype(np.uint8)


def decode(raw: bytes) -> np.ndarray:
    """Decode ATF bytes into an (H, W, 4) RGBA uint8 array (mip 0)."""
    fmt, width, height, mips, off = _parse_header(raw)
    if fmt != 2:
        raise ATFError(f"unsupported ATF format {fmt} (only 2/compressed/DXT1)")

    blocks = list(_blocks(raw, off))
    if len(blocks) < 2:
        raise ATFError(f"expected 2 blocks (indices + endpoints), got {len(blocks)}")

    n_blocks = (width // 4) * (height // 4)
    index_data = _lzma_raw(blocks[0], n_blocks * 4 + 16)
    # a single leading flag byte precedes the index stream
    index_data = index_data[1:1 + n_blocks * 4] if len(index_data) > n_blocks * 4 \
        else index_data[:n_blocks * 4]

    endpoints = imagecodecs.jpegxr_decode(blocks[1])
    if endpoints.ndim == 2:
        endpoints = np.repeat(endpoints[..., None], 3, axis=2)
    endpoints = endpoints[..., :3]

    rgb = _decode_dxt1(endpoints, index_data, width, height)
    rgba = np.dstack([rgb, np.full((height, width), 255, np.uint8)])
    return rgba


def decode_file(path: str) -> np.ndarray:
    with open(path, "rb") as f:
        return decode(f.read())


def atf_to_png(in_path: str, out_path: str) -> tuple[int, int]:
    """Decode an ATF file and write it as a PNG. Returns (width, height)."""
    from PIL import Image
    rgba = decode_file(in_path)
    Image.fromarray(rgba, "RGBA").save(out_path)
    return rgba.shape[1], rgba.shape[0]
