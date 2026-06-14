# Mevcut Blender Scriptleri İncelemesi

3 script var. Hepsi Blender Text Editor'dan elle çalıştırılmak üzere yazılmış,
bazı değerler hardcode. Pipeline'a entegre edilirken parametrize edilmeli.

## 1. `mesh_to_plain_axes.py`
**Ne yapar**: `engine_*` ve `laserpoint_*` prefix'li MESH objelerini siler, yerlerine
aynı dünya konumunda `PLAIN_AXES` Empty oluşturur ve `main` objesine parent eder.
- Origin'i geometriye taşır (`ORIGIN_GEOMETRY`/`MEDIAN`) → doğru merkez.
- `matrix_world` yedekleyip parent sonrası geri uygular → konum korunur.

**Pipeline'da rolü**: Faz 3'ün çekirdek mantığı. Yardımcı noktaları referansa çeviren
adım bu. `build_scene.py` bunu doğrudan kullanacak.
**Not**: Import sırasında bu objeler zaten mesh ise mantık birebir uyar.

## 2. `rotation_animation.py`
**Ne yapar**: Aktif objeye Z ekseninde frame başına 5° dönüş keyframe'i ekler
(frame 1→72, toplam ~360°). Mevcut animasyonu temizler.

**Pipeline'da rolü**: Faz 5. Render öncesi turntable animasyonu.
**İyileştirme**: `start/end/deg_per_frame` ve hedef obje parametre olmalı;
`bpy.context.active_object` yerine isimle (`main`) seç.

## 3. `2d_to_3d_render.py`
**Ne yapar**: En kapsamlı script. `main` + `engine_/laserpoint_` hedefleri için:
- Frame 1→72 render (Eevee, RGBA, transparent film, 200×200).
- Material Preview görünümünü (studio HDRI + ışık checkbox'ları) Scene World'e taşır
  (`sync_from_material_preview`) → viewport ile render eşleşir.
- Her frame'de hedef noktaların kamera-uzayı 2D koordinatlarını toplar.
- Tüm frame'ler için **global stable crop** hesaplar (alpha bbox + nokta padding).
- Frame'leri crop'lar, koordinatları crop'a göre düzeltir.
- `<FILE_NAME>_Coords.json` yazar (sprite + nokta koordinatları).

**Pipeline'da rolü**: Faz 5'in ana çıktısı — 3D modelden 2D sprite + nokta koordinat
üretimi. DarkOrbit tarzı sprite/animasyon pipeline'ı.
**Hardcode değerler** (parametrize edilecek): `OUTPUT_DIR="C:/RenderOutput/"`,
`FILE_NAME="goliath"`, `START/END_FRAME`, `RENDER_W/H`, `COORD_ORIGIN`, render engine.
**Bağımlılık**: PIL (mevcut), aktif 3D Viewport (headless'ta `sync_from_material_preview`
çalışmaz → headless için world/light'ı doğrudan kurmak gerekir).

## Ortak gözlemler
- `engine_`/`laserpoint_` prefix konvansiyonu 3 script + AWD node isimleri arasında
  tutarlı → pipeline bu konvansiyona dayanabilir.
- `main` ana obje ismi sabit varsayım → AWD parser bunu doğrulamalı/garanti etmeli.
- Render scriptleri viewport context'ine bağlı; tam otomasyon (cron/headless) için
  world+ışık kurulumunun context'siz versiyonu gerekir (Faz 5 işi).
