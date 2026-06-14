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

## Faz 5 — Render scriptleri entegrasyonu ✅
Eski 3 script (viewport-bağımlı, hardcode, eski API) yerine headless render modülü.
- [x] `src/blender/render_sprites.py` (Blender 5.x, headless): glb import → world
      HDRI + sun lighting → framing kamera (ortho/persp) → turntable Z rotation →
      transparent RGBA frame render → `engine_/laserpoint_` empty'lerinin ekran
      koordinatlarını topla → ham JSON.
- [x] `src/render.py` (orchestrator): config (defaults+CLI override) → Blender →
      PIL ile stable crop + koordinat origin ayarı → `<mesh>_Coords.json`.
- [x] Tüm hardcode değerler parametrize (`config.RENDER_DEFAULTS` + CLI):
      frames, çözünürlük, samples, HDRI, kamera açısı (elevation/azimuth/ortho/fov/
      margin), sun, coord origin, crop padding.
- [x] `mesh_to_plain_axes.py` mantığı zaten Faz 3'te pipeline'a entegre (empties).
- [x] **Doğrulama**: sibelon 512px turntable; 5 nokta her frame doğru izlendi
      (overlay ile kontrol: laserpoint ön, engine arka nozül, light üst); stable crop
      çalışıyor. Lighting headless reproducible (material-preview bağımlılığı kaldırıldı).

## Render kullanımı
```
python -m src.render sibelon                       # varsayılan turntable (72f, 256px, ortho)
python -m src.render sibelon --frames 32           # 32 frame = otomatik 360/32° adım (tam tur)
python -m src.render sibelon --resolution 1024 --samples 128 --persp
python -m src.render sibelon --hdri city.exr --elevation 60 --azimuth 30 --margin 1.3
python -m src.render sibelon --deg-per-frame 5 --start-angle 90 --emission 0.4
python -m src.render --all
```
Frame sayısı serbest; `total_degrees / frames` ile adım otomatik (eksik/fazla tur olmaz).
HDRI: studio / city / courtyard / forest / interior / night / sunrise / sunset.
CLI grupları: turntable (frames/total-degrees/deg-per-frame/start-angle/frame-start),
output-quality (resolution/samples/engine/view-transform/no-crop/no-transparent/origin),
camera-lighting (hdri/world-strength/sun-energy/emission/elevation/azimuth/persp/margin).

## Çıktı yapısı (gruplu, profesyonel)
```
out/<mesh>/
  model/
    <mesh>.glb               # birincil, self-contained (texture gömülü)
    textures/                # decode edilmiş kaynak PNG'ler
    gltf/  <mesh>.gltf + .bin + textures
    obj/   <mesh>.obj + .mtl
  sprites/
    <mesh>_1.png ... <mesh>_N.png   # 1-based isimlendirme
    <mesh>_Coords.json              # düz {point: [[x,y]|"OFF",...]}, sadece engine_/laserpoint_
  work/                       # ara dosyalar (scene/cfg/meta json)
```
Kalite: EEVEE samples 96, **Standard view transform** (texture renkleri doğru, AgX/Filmic değil).
