"""ATF decoder tests: header parsing, DXT1 reconstruction, full round-trip."""
import numpy as np
import pytest

from src.atf.decoder import ATFError, _decode_dxt1, _parse_header, decode
from tests import synth


def test_parse_header_new_format():
    # new header: data[6]==0xFF -> fields at offset 12
    d = b"ATF" + bytes([0, 0, 0, 0xFF, 2, 0, 1, 0, 0]) + bytes([2, 9, 9, 10])
    fmt, w, h, mips, off = _parse_header(d)
    assert (fmt, w, h, mips, off) == (2, 512, 512, 10, 16)


def test_parse_header_old_format():
    d = b"ATF" + bytes([2, 8, 8, 1])  # old: fields at offset 6 -> here offset 3..
    # craft so data[6] != 0xFF -> base 6
    d = b"ATF" + bytes([0, 0, 0, 2, 7, 7, 1])
    fmt, w, h, mips, off = _parse_header(d)
    assert (fmt, w, h, mips, off) == (2, 128, 128, 1, 10)


def test_parse_header_bad_signature():
    with pytest.raises(ATFError):
        _parse_header(b"XYZ" + b"\x00" * 16)


def test_decode_dxt1_palette():
    # one 4x4 block; c0 / c1 plus the two interpolated palette entries
    c0, c1 = (40, 40, 40), (160, 160, 160)
    endpoints = np.array([[c0], [c1]], dtype=np.uint8)  # (2, 1, 3)
    # each row's byte selects pixels 0,1,2,3 -> palette idx 0,1,2,3
    row = 0b11_10_01_00  # 0xE4
    index_bytes = bytes([row, row, row, row])
    rgb = _decode_dxt1(endpoints, index_bytes, 4, 4)
    assert rgb.shape == (4, 4, 3)
    assert tuple(rgb[0, 0]) == c0
    assert tuple(rgb[0, 1]) == c1
    assert tuple(rgb[0, 2]) == (80, 80, 80)    # (2*c0+c1)/3
    assert tuple(rgb[0, 3]) == (120, 120, 120)  # (c0+2*c1)/3


def test_decode_rejects_unsupported_format():
    d = b"ATF" + bytes([0, 0, 0, 0xFF, 2, 0, 1, 0, 0, 0]) + bytes([1, 3, 3, 1])
    with pytest.raises(ATFError):
        decode(d)


def test_full_roundtrip():
    pytest.importorskip("imagecodecs")
    w = h = 8
    bw, bh = w // 4, h // 4         # 2x2 blocks
    # endpoints: top plane = color0, bottom plane = color1
    c0 = np.array([200, 100, 50], np.uint8)
    endpoints = np.zeros((2 * bh, bw, 3), np.uint8)
    endpoints[:bh] = c0
    endpoints[bh:] = (20, 220, 120)
    index_bytes = bytes(bw * bh * 4)        # all zero -> every pixel = color0
    atf = synth.atf_file(w, h, endpoints, index_bytes)

    rgba = decode(atf)
    assert rgba.shape == (h, w, 4)
    assert (rgba[..., 3] == 255).all()       # opaque alpha
    # all-zero indices -> color0 everywhere (JXR is near-lossless here)
    assert np.allclose(rgba[..., :3], c0, atol=12)
