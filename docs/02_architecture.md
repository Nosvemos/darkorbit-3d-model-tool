# Mimari & Teknik Kararlar

## Genel Yapı
Pure-Python ön işleme (parse + decode) + Blender headless (sahne + export) hibrit pipeline.

```
src/
  atf/
    decoder.py        # ATF → RGBA → PNG
    dxt.py            # BC1/BC3 (DXT1/5) decode
  awd/
    parser.py         # AWDc decompress + AWD2 blok parse → ara model (dataclass)
    model.py          # Scene / Mesh / Node / Material dataclass'ları
  blender/
    build_scene.py    # (blender --background --python) import + material wire + empties + export
  pipeline.py         # CLI orkestratör: meshes/ döngüsü
  config.py           # yollar, blender exe, çıktı formatı seçimi
  render.py             # turntable sprite render orchestrator (Faz 5)
out/
  <mesh>/
    model/   <mesh>.glb (+textures/, gltf/, obj/)
    sprites/ <mesh>_1.png ... + <mesh>_Coords.json   # engine_/laserpoint_ koordinatları
    work/    ara dosyalar (scene/cfg/meta json)
```

## Karar 1 — ATF decode: kendi decoder'ımız
**Seçim**: Pure-Python ATF decoder yaz (DXT + LZMA).
**Neden**: Tam otomasyon hedefi; ATF2PNG GUI aracına bağımlılık otomasyonu kırar.
PIL DXT decode edemez → kendi BC1/BC3 decoder'ımız (`atf/dxt.py`). LZMA için Python
stdlib `lzma`. Mevcut `cubikon_diffuse_512.png` doğrulama referansı.
**Alternatif**: ATF2PNG.exe CLI destekliyorsa subprocess ile çağır (fallback).

## Karar 2 — AWD parse: pure-Python AWD2 parser
**Seçim**: `awd/parser.py` — zlib decompress + AWD2 blok okuyucu.
**Neden**: Prefab3D GUI, scriptlenemez. AWD2 formatı dokümante. Decompress doğrulandı.
Parser, node ağacını (`main` + `engine_*` + `laserpoint_*`) ve transformları korur →
yardımcı noktalar kaybolmaz.

## Karar 3 — Export yolu: Blender headless (birincil)
**Seçim**: `blender --background --python build_scene.py`.
**Neden**:
- Kullanıcının kalite beklentisi mevcut elle Blender akışıyla aynı (material node'ları).
- Mevcut render/animasyon scriptleri zaten Blender sahnesi varsayıyor.
- glTF/glb/obj export'u Blender'da olgun; material node wiring tam kontrol.
- `engine_/laserpoint_` → Empty dönüşümü için mevcut `mesh_to_plain_axes.py` mantığı
  doğrudan tekrar kullanılır.
**Alternatif (sonraki faz)**: Pure-Python glTF yazıcı (Blender'sız hızlı yol) — opsiyonel.

## Karar 4 — Material node şeması (PBR / Principled BSDF)
| ATF kanalı | Blender bağlantısı |
|-----------|--------------------|
| diffuse   | Base Color (sRGB) |
| normal    | Normal Map node → Normal (Non-Color) |
| specular  | Specular / Roughness (Non-Color; inversiyon gerekebilir) |
| glow      | Emission Color + Emission Strength |

Eksik kanal varsa o bağlantı atlanır (bazı meshlerde 4'ten az texture olabilir).

## Karar 5 — Ara model (intermediate representation)
AWD parser doğrudan Blender'a değil, önce dataclass tabanlı `model.py` yapısına yazar.
Bu, parser'ı Blender'dan bağımsız test edilebilir yapar + ileride pure-python glTF
yolunu açar.

## Akış (tek mesh)
```
1. atf.decoder: <mesh>_<kanal>_512.atf → out/<mesh>/textures/*.png
2. awd.parser:  meshes/<mesh>.awd → Scene(meshes, nodes, materials)
3. blender.build_scene: Scene + PNG'ler → import, wire, empties, export
4. pipeline: çıktı + <mesh>_points.json doğrula, logla
```

## Bağımlılıklar
- Python 3.14 (mevcut), PIL/Pillow 12.2 (mevcut), stdlib `zlib`/`lzma`/`struct`.
- Blender 5.1.2 (Steam): `C:\Program Files (x86)\Steam\steamapps\common\Blender\blender.exe`.
  ⚠️ 5.x API farkları (EEVEE, glTF operatörleri) Faz 3'te ele alınacak.
