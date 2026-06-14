# Açık Sorular / Netleştirilecek Kararlar

## ✅ Çözülen Kararlar
1. **Blender yolu**: `C:\Program Files (x86)\Steam\steamapps\common\Blender\blender.exe`
   — **Blender 5.1.2** (Steam, build 2026-05-19).
   ⚠️ Mevcut blender scriptleri eski API kullanıyor (`BLENDER_EEVEE` → 5.x'te değişti,
   glTF export operatör adları). Faz 3/5'te 5.x API'sine uyarlanacak.
2. **Birincil çıktı**: **`.glb`** (texture gömülü, empties+hiyerarşi korunur).
   `.gltf` ve `.obj` opsiyonel bayrakla üretilir.
3. **ATF decode**: **Kendi pure-Python decoder** (DXT + LZMA). Harici araç bağımlılığı yok.

## Kalan / İlk çıktıda netleşecek noktalar

## 4. Empties parent davranışı
`engine_/laserpoint_` → Empty + `main` altına parent (mevcut script gibi).
glTF export'ta empties node olarak korunur. Onay: bu davranış doğru mu?

## 5. Texture çözünürlüğü / kanal eşleme
Dosya adları `_512` → 512×512. specular kanalının roughness'a inversiyonu gerekebilir
(specular workflow vs PBR roughness). İlk çıktıda görsel kontrolle ayarlanacak.

## 6. temp_lzma_*.bin
`textures/` içindeki 5 geçici dosya silinebilir mi? (önceki ATF decode denemesi artığı)
