"""Helpers that build synthetic AWD / ATF byte streams for tests, so the suite
runs without the (git-ignored) game assets."""
from __future__ import annotations

import lzma
import struct
import zlib

import numpy as np


# --- AWD --------------------------------------------------------------------

def _str16(s: str) -> bytes:
    b = s.encode("utf-8")
    return struct.pack("<H", len(b)) + b


def _block(block_id: int, btype: int, data: bytes) -> bytes:
    return struct.pack("<I", block_id) + bytes([0, btype, 0]) + \
        struct.pack("<I", len(data)) + data


def _stream(stype: int, ftype: int, payload: bytes) -> bytes:
    return bytes([stype, ftype]) + struct.pack("<I", len(payload)) + payload


def geometry_block(block_id: int, name: str, positions, indices, uvs,
                   geom_prop_len: int = 0) -> bytes:
    streams = b""
    streams += _stream(1, 7, struct.pack(f"<{len(positions)}f", *positions))
    streams += _stream(2, 5, struct.pack(f"<{len(indices)}H", *indices))
    if uvs:
        streams += _stream(3, 7, struct.pack(f"<{len(uvs)}f", *uvs))
    sub = struct.pack("<I", 0) + streams           # sub_prop_len + streams
    data = _str16(name) + struct.pack("<H", 1)     # name + num_subs
    # geometry-level property block (non-zero exercises the skip path)
    data += struct.pack("<I", geom_prop_len) + b"\x00" * geom_prop_len
    data += struct.pack("<I", len(sub)) + sub
    return _block(block_id, 1, data)


def material_block(block_id: int, name: str) -> bytes:
    data = _str16(name) + struct.pack("<H", 2) + struct.pack("<I", 0)
    return _block(block_id, 81, data)


def instance_block(block_id: int, name: str, matrix12, geom_id: int,
                   material_ids=()) -> bytes:
    data = struct.pack("<I", 0)                         # parent
    data += struct.pack("<12f", *matrix12)
    data += _str16(name)
    data += struct.pack("<I", geom_id)
    data += struct.pack("<H", len(material_ids))
    for mid in material_ids:
        data += struct.pack("<I", mid)
    return _block(block_id, 23, data)


def awd_file(blocks: bytes, magic4: bytes = b"AWDc") -> bytes:
    body = blocks
    header = magic4 + bytes([1, 0, 0, 1]) + struct.pack("<I", len(body))
    return header + zlib.compress(body)


# --- ATF --------------------------------------------------------------------

def lzma_raw_block(data: bytes) -> bytes:
    """Mirror the ATF raw-LZMA framing the decoder expects: props + dict + stream."""
    lc, lp, pb = 3, 0, 2
    props = pb * 45 + lp * 9 + lc            # 0x5d
    dict_size = 1 << 16
    filt = [{"id": lzma.FILTER_LZMA1, "dict_size": dict_size,
             "lc": lc, "lp": lp, "pb": pb}]
    comp = lzma.compress(data, format=lzma.FORMAT_RAW, filters=filt)
    return bytes([props]) + struct.pack("<I", dict_size) + comp


def atf_file(width: int, height: int, endpoints: np.ndarray,
             index_bytes: bytes) -> bytes:
    """Build a minimal new-header ATF (format 2 / DXT1) with the two blocks."""
    import imagecodecs
    log_w = width.bit_length() - 1
    log_h = height.bit_length() - 1
    # "ATF" + 9-byte preamble (data[6]=0xFF marks new header) + format/w/h/mips at 12
    header = b"ATF" + bytes([0, 0, 0, 0xFF, 2, 0, 1, 0, 0]) + \
        bytes([2, log_w, log_h, 1])
    blk_idx = lzma_raw_block(bytes([0xAA]) + index_bytes)  # leading flag byte
    blk_ep = imagecodecs.jpegxr_encode(endpoints)
    body = struct.pack(">I", len(blk_idx)) + blk_idx + \
        struct.pack(">I", len(blk_ep)) + blk_ep
    return header + body
