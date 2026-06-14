# DarkOrbit 3D Model Tool — Genel Bakış

## Amaç
DarkOrbit oyun varlıklarını (`.awd` mesh + `.atf` texture) **otomatik** olarak modern 3D
formatlarına (`.obj` / `.gltf` / `.glb`) dönüştürmek. Mevcut elle yapılan iş akışını
tamamen scriptleştirmek.

## Girdi Varlıkları
- `meshes/*.awd` — Away3D AWD2 sahne dosyaları (zlib sıkıştırılmış gövde).
  Her dosya bir ana mesh (`main`) + yardımcı noktalar (`engine_*`, `laserpoint_*`) içerir.
- `textures/*.atf` — Adobe Texture Format (GPU texture konteyneri).
  Mesh başına genelde 4 kanal: `diffuse`, `glow`, `normal`, `specular` (bazen eksik).

Mevcut mesh listesi (11): cubikon, devolarium, kristallin, kristallon, lordakia,
lordakium, mordon, protegit, saimon, sibelon, sibelonit.

## Mevcut Elle İş Akışı (otomatikleştirilecek)
1. **ATF2PNG** ile `.atf` → `.png`.
2. **Prefab3D** ile `.awd` aç → `.obj` export.
3. **Blender**: `.obj` import, Shading sekmesinde texture node'larını elle bağla.
4. Blender'dan export.

## Hedef Otomatik İş Akışı
```
.awd  ──parse──▶ geometri + node ağacı (main, engine_*, laserpoint_*) + material refs
.atf  ──decode─▶ .png (diffuse/normal/specular/glow)
                          │
                          ▼
              Blender (headless) ile sahne kur:
              - material node'ları otomatik bağla (PBR)
              - engine_/laserpoint_ → Empty (PLAIN_AXES) referans noktaları
                          │
                          ▼
              export: .glb / .gltf / .obj
```

## Kritik Gereksinimler
- **Yardımcı noktalar kaybolmamalı**: `engine_*` ve `laserpoint_*` referans noktaları
  korunmalı (ileride kullanılacak — render koordinat çıkarımı, animasyon).
- **Texture'lar doğru bağlanmalı**: diffuse→base color, normal→normal map,
  specular→specular/roughness, glow→emission.
- **Toplu çalışmalı**: tüm `meshes/` klasörü tek komutla işlenebilmeli.

## Doküman Haritası
- `01_formats.md` — AWD ve ATF binary format bulguları.
- `02_architecture.md` — pipeline mimarisi, modüller, teknik kararlar.
- `03_roadmap.md` — fazlara bölünmüş görev planı.
- `04_blender_scripts.md` — mevcut 3 blender scriptinin incelemesi.
- `05_open_questions.md` — netleştirilmesi gereken kararlar.
