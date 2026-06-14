"""Extract .awp files from the fx/*.zip archives.

Each fx/<name>.zip contains a single <name>.awp, which is plain JSON describing
an Away3D particle effect (particleEvents / animationDatas / nodes). "Extraction"
is just unzipping; this tool unpacks every archive into fx/awp/ and validates
that each .awp parses as JSON.

Usage:
    python tools/extract_awp.py [fx_dir]
"""
import glob
import json
import os
import sys
import zipfile

FX_DIR = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fx")


def main():
    out_dir = os.path.join(FX_DIR, "awp")
    os.makedirs(out_dir, exist_ok=True)
    zips = sorted(glob.glob(os.path.join(FX_DIR, "*.zip")))
    extracted = bad = 0
    for zp in zips:
        try:
            with zipfile.ZipFile(zp) as zf:
                for member in zf.namelist():
                    if not member.lower().endswith(".awp"):
                        continue
                    data = zf.read(member)
                    dest = os.path.join(out_dir, os.path.basename(member))
                    with open(dest, "wb") as f:
                        f.write(data)
                    try:
                        json.loads(data)
                    except json.JSONDecodeError as e:
                        bad += 1
                        print(f"  ! {os.path.basename(member)}: not valid JSON ({e})")
                    extracted += 1
        except zipfile.BadZipFile:
            bad += 1
            print(f"  ! {os.path.basename(zp)}: not a valid zip")
    print(f"extracted {extracted} .awp from {len(zips)} archives -> {out_dir}"
          + (f" ({bad} problem(s))" if bad else ""))


if __name__ == "__main__":
    main()
