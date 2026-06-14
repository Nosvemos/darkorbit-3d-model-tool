"""Exploratory ATF walker — reverse-engineer block layout.

Usage: python tools/dump_atf.py textures/cubikon_diffuse_512.atf
"""
import lzma
import struct
import sys


def parse_header(d: bytes):
    assert d[:3] == b"ATF", f"bad sig {d[:3]!r}"
    offset = 12 if d[6] == 0xFF else 6
    fmt = d[offset]
    width = 1 << d[offset + 1]
    height = 1 << d[offset + 2]
    mips = d[offset + 3]
    data_off = offset + 4
    print(f"filesize={len(d)} new_header={offset == 12} "
          f"format={fmt}(&0x7f={fmt & 0x7f}) {width}x{height} mips={mips} "
          f"data_off={data_off}")
    return fmt, width, height, mips, data_off


def lzma_decode(block: bytes, expected: int) -> bytes:
    """block = raw LZMA: 1 prop byte + 4 dict-size + compressed (no size field)."""
    props = block[0]
    dict_size = struct.unpack_from("<I", block, 1)[0]
    pb = props // 45
    rem = props % 45
    lp = rem // 9
    lc = rem % 9
    filt = [{"id": lzma.FILTER_LZMA1, "dict_size": dict_size,
             "lc": lc, "lp": lp, "pb": pb}]
    dec = lzma.LZMADecompressor(format=lzma.FORMAT_RAW, filters=filt)
    return dec.decompress(block[5:], expected)


def walk(d: bytes):
    fmt, w, h, mips, off = parse_header(d)
    idx = 0
    while off + 4 <= len(d):
        blen = struct.unpack_from(">I", d, off)[0]
        body = d[off + 4:off + 4 + blen]
        head = body[:5].hex(" ") if body else "-"
        note = ""
        if body and body[0] == 0x5D:
            try:
                out = lzma_decode(body, 1 << 24)
                note = f"-> LZMA decompressed {len(out)} bytes"
            except Exception as e:
                note = f"-> LZMA fail: {e}"
        print(f"#{idx:<2} off={off:<8} len={blen:<7} head=[{head}] {note}")
        if blen == 0 or off + 4 + blen > len(d):
            print("  (zero/overrun -> stop)")
            break
        off += 4 + blen
        idx += 1
    print(f"ended off={off}/{len(d)}, blocks={idx}, mips={mips}")


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "textures/cubikon_diffuse_512.atf"
    walk(open(path, "rb").read())
