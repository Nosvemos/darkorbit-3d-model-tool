# Yol Haritası (Fazlar)

İlke: her faz tek başına doğrulanabilir çıktı üretir. Önce 1 mesh (cubikon) üzerinde
uçtan uca çalıştır, sonra toplu işle.

## Faz 0 — Proje iskeleti
- [ ] `src/` paket yapısı, `config.py`, `requirements.txt`.
- [ ] Blender exe yolu tespiti/ayarı.

## Faz 1 — ATF decoder ✅
- [x] ATF header parse (yeni-versiyon offset 12; format/genişlik/yükseklik/mip).
- [x] Blok yapısı çözüldü: format 2 = DXT1, 2 blok (UI32-BE uzunluk önekli).
- [x] LZMA blok decompress (raw LZMA, stdlib `lzma` FORMAT_RAW) → DXT1 index'leri.
- [x] JPEG-XR blok decode (`imagecodecs`) → DXT1 endpoint plane'leri (RGB888, lossy).
- [x] DXT1 → RGBA decode (numpy vektörize; RGB565 round-trip atlandı, daha iyi kalite).
- [x] PNG yazımı.
- [x] **Doğrulama**: 44/44 texture decode; diffuse/normal/glow/specular görsel kontrol
      doğru (normal map mavi, glow siyah-üstü-emissive). `src/atf/`, `tools/dump_atf.py`.
      Not: eski referans PNG silinmişti → görsel doğrulama yapıldı.

## Faz 2 — AWD parser ✅
- [x] Header + zlib decompress — `AWDc` ve standart `AWD\x02` varyantları (offset 12).
- [x] AWD2 blok iterator (id/ns/type/flags/len, little-endian).
- [x] Geometri blokları (type 1) → vertex/index/uv stream'leri (ftype 5=u16, 7=f32).
- [x] Mesh instance blokları (type 23) → node adı + 3x4 transform + geom/material ref.
- [x] Material blokları (type 81) → ad + flag props. Texture isim konvansiyonuyla.
- [x] Animasyon klip adları (type 112) → `open`/`close`/`idle`.
- [x] Dayanıklılık: f64-matrix varyantı + instance'sız orphan geometri → synthetic
      instance; `null~<name>` materyalden ad kurtarma (protegit engine_0).
- [x] **Doğrulama**: 11 mesh'in tamamı parse oldu; `engine_*`/`laserpoint_*` noktaları,
      vertex/üçgen sayıları doğru. `src/awd/`, `tools/dump_awd.py`.

## Faz 3 — Blender sahne kurucu (headless) ✅
- [x] Ara modelden (JSON) mesh oluştur (verts/faces/uv); local geom + `matrix_world`.
- [x] Material node graph: diffuse→Base Color, normal→Normal Map, specular→Specular,
      glow→Emission. Eksik kanal atlanır.
- [x] `engine_/laserpoint_/light_position` → Empty (PLAIN_AXES) median origin'de,
      ana body'ye parent (`mesh_to_plain_axes.py` mantığı).
- [x] Export: `.glb` (varsayılan, texture gömülü) + opsiyonel `.gltf` / `.obj`.
- [x] Away3D Y-up → Blender Z-up eksen dönüşümü (+90° X).
- [x] **Doğrulama**: cubikon (küp), sibelon/devolarium/protegit (gemi), kristallon
      (kristal) doğru render; texture'lar bağlı; glb'de empties node olarak korunuyor.
      `src/blender/build_scene.py`, `tools/preview_glb.py`.

## Faz 4 — Orkestrasyon & batch ✅
- [x] `python -m src.pipeline <mesh>|--all [--gltf --obj --no-blender]`.
- [x] ATF decode → PNG, AWD parse → JSON intermediate, Blender headless çağrısı.
- [x] Eksik texture kanalına dayanıklılık (sadece var olan kanallar bağlanır).
- [x] **Doğrulama**: 11 mesh'in tamamı tek komutla glb'ye dönüştü (`out/<mesh>/`).
      Mimari: sistem-Python (numpy/imagecodecs) ↔ Blender (sadece bpy+stdlib) ayrık.

## Faz 5 — Render scriptleri entegrasyonu (opsiyonel/sonraki)
- [ ] Mevcut `rotation_animation.py`, `mesh_to_plain_axes.py`, `2d_to_3d_render.py`'i
      pipeline çıktısıyla çalışacak şekilde uyarla (bkz `04_blender_scripts.md`).
- [ ] `FILE_NAME`/yol gibi hardcode değerleri parametrize et.

## Önce yapılacak ilk somut adım
Faz 1 + Faz 2'yi paralel başlat (birbirinden bağımsız), cubikon üzerinde doğrula.
