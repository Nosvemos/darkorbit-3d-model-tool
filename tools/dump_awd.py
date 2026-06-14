"""Exploratory AWD2 block walker — reverse-engineer block layout.

Usage: python tools/dump_awd.py meshes/cubikon.awd
Decompresses the AWDc zlib body, then walks the AWD2 block list printing
id / namespace / type / flags / length and a short hex+ascii preview.
"""
import struct
import sys
import zlib


def ascii_preview(b: bytes, n: int = 48) -> str:
    chunk = b[:n]
    return "".join(chr(c) if 32 <= c < 127 else "." for c in chunk)


def decompress(path: str) -> bytes:
    raw = open(path, "rb").read()
    assert raw[:4] == b"AWDc", f"bad magic {raw[:4]!r}"
    ver_major = raw[4]
    flags = struct.unpack("<H", raw[5:7])[0]
    compression = raw[7]
    ulen = struct.unpack("<I", raw[8:12])[0]
    print(f"header: ver_major={ver_major} flags=0x{flags:04x} "
          f"compression={compression} ulen={ulen} filesize={len(raw)}")
    body = zlib.decompress(raw[12:])
    print(f"decompressed body = {len(body)} bytes (declared {ulen})\n")
    return body


def walk(body: bytes) -> None:
    off = 0
    idx = 0
    while off + 11 <= len(body):
        block_id = struct.unpack_from("<I", body, off)[0]
        ns = body[off + 4]
        btype = body[off + 5]
        flags = body[off + 6]
        length = struct.unpack_from("<I", body, off + 7)[0]
        data_off = off + 11
        data = body[data_off:data_off + length]
        print(f"#{idx:<3} off={off:<8} id={block_id:<5} ns={ns:<3} "
              f"type={btype:<4} flags=0x{flags:02x} len={length:<7} "
              f"| {ascii_preview(data)}")
        if length > len(body) or data_off + length > len(body):
            print("  !! length overruns body — layout assumption wrong, stop")
            break
        off = data_off + length
        idx += 1
    print(f"\nwalked {idx} blocks, ended at off={off} / {len(body)}")


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "meshes/cubikon.awd"
    walk(decompress(path))
