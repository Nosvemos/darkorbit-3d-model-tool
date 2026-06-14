# Yol Haritası (Fazlar)

İlke: her faz tek başına doğrulanabilir çıktı üretir. Önce 1 mesh (cubikon) üzerinde
uçtan uca çalıştır, sonra toplu işle.

## Faz 0 — Proje iskeleti
- [ ] `src/` paket yapısı, `config.py`, `requirements.txt`.
- [ ] Blender exe yolu tespiti/ayarı.

## Faz 1 — ATF decoder
- [ ] ATF header tam parse (subformat + mip tablosu).
- [ ] LZMA blok decompress (stdlib `lzma`; `temp_lzma_*.bin` ile karşılaştır).
- [ ] BC1/BC3 (DXT1/5) decoder → RGBA.
- [ ] PNG yazımı.
- [ ] **Doğrulama**: `cubikon_diffuse_512` çıktısını mevcut `cubikon_diffuse_512.png`
      ile karşılaştır (pixel/yapı eşleşmesi).
- [ ] 4 kanalı da (diffuse/normal/specular/glow) batch decode.

## Faz 2 — AWD parser
- [ ] `AWDc` header + zlib decompress (doğrulandı).
- [ ] AWD2 blok iterator (id/ns/type/flags/len).
- [ ] Geometri blokları → vertex/index/uv/normal.
- [ ] Scene-graph blokları → node ağacı + isim + transform matris.
- [ ] Material/texture ref blokları → mesh↔texture eşleşmesi.
- [ ] **Doğrulama**: `main`, `engine_*`, `laserpoint_*` node'ları + üçgen sayısı doğru;
      ara model JSON dump'ı incelenebilir.

## Faz 3 — Blender sahne kurucu (headless)
- [ ] Ara modelden mesh oluştur (verts/faces/uv/normal).
- [ ] Material node graph (Karar 4 şeması) + PNG bağlama.
- [ ] `engine_/laserpoint_` mesh'lerini Empty (PLAIN_AXES) yap, `main` altına parent et
      (mevcut `mesh_to_plain_axes.py` mantığı).
- [ ] Export: `.glb` (varsayılan) + opsiyonel `.gltf` / `.obj`.
- [ ] `<mesh>_points.json` yaz (referans nokta koordinatları).
- [ ] **Doğrulama**: cubikon.glb modern viewer'da doğru görünür, texture'lar bağlı,
      empties yerinde.

## Faz 4 — Orkestrasyon & batch
- [ ] `pipeline.py` CLI: tek mesh / tüm klasör, format bayrakları (`--glb/--gltf/--obj`).
- [ ] Eksik texture kanalına dayanıklılık.
- [ ] Hata raporu + log.
- [ ] **Doğrulama**: 11 mesh'in tamamı tek komutla dönüşür.

## Faz 5 — Render scriptleri entegrasyonu (opsiyonel/sonraki)
- [ ] Mevcut `rotation_animation.py`, `mesh_to_plain_axes.py`, `2d_to_3d_render.py`'i
      pipeline çıktısıyla çalışacak şekilde uyarla (bkz `04_blender_scripts.md`).
- [ ] `FILE_NAME`/yol gibi hardcode değerleri parametrize et.

## Önce yapılacak ilk somut adım
Faz 1 + Faz 2'yi paralel başlat (birbirinden bağımsız), cubikon üzerinde doğrula.
