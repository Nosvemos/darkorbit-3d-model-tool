# Binary Format Bulguları

> Bu dosya, gerçek dosyalar üzerinde yapılan hexdump + decompress denemelerinden çıkarıldı.
> Tam parse implementasyonu sırasında detaylar doğrulanacak/genişletilecek.

## AWD (`meshes/*.awd`)

DarkOrbit, Away3D motorunu kullanır → dosyalar **AWD2** formatındadır,
zlib ile sıkıştırılmış gövdeye sahip "AWDc" varyantı.

### Header (12 byte)
```
offset  bytes              anlam
0x00    41 57 44 63        magic "AWDc"
0x04    01                 version major
0x05    e0 00              flags (uint16) — doğrulanacak
0x07    01                 compression = 1 (zlib)
0x08    51 ca 01 00        uncompressed length (uint32 LE) = 117329
0x0C    78 da ...          zlib deflate stream (gövde başlangıcı)
```

### Doğrulanan davranış (cubikon.awd)
- Dosya boyutu: 117341 byte.
- `zlib.decompress(data[12:])` → **226821 byte** açılmış gövde.
- Açılan gövde başı: `01 00 00 00 00 ff 00 46 ...`
- İçinde ASCII: `AwayBuilder`, `1.0.0` → generator metadata bloğu mevcut.

### Gövde = AWD2 blok listesi
AWD2 blok yapısı (her blok):
```
uint32  block id
uint8   namespace
uint8   type        (ör: TriangleGeometry, Container, MeshInstance, Material, Texture...)
uint8   flags
uint32  length
bytes   data[length]
```
Parser bu blokları sırayla okuyup:
- **Geometri blokları** → vertex/index/uv/normal stream'leri.
- **Container/SceneGraph blokları** → `main`, `engine_*`, `laserpoint_*` isimli node'lar + transform matrisleri.
- **Material/Texture blokları** → hangi mesh hangi texture'ı kullanıyor (isim eşleşmesi
  zaten texture dosya adlarıyla uyumlu: `cubikon_diffuse_512` vb.).

> Not: Tam AWD2 blok tip tablosu Away3D AWD2 spesifikasyonundan alınacak. Bizim için
> kritik blok tipleri: namespace 0'daki geometry, scene-graph container, mesh instance.

## ATF (`textures/*.atf`)

Adobe Texture Format — GPU'ya uygun sıkıştırılmış texture konteyneri.

### Header (cubikon_diffuse_512.atf)
```
offset  bytes              anlam
0x00    41 54 46           magic "ATF"
0x03    00 00 00 ff 02 ... format/length/version alanları (doğrulanacak)
```

### Bilinenler
- ATF blokları DXT (S3TC: BC1/BC3), PVRTC veya ETC subformatlarından biri olabilir;
  PC istemcisi büyük olasılıkla **DXT** kullanır.
- Her mipmap seviyesi raw veya **LZMA / JPEG-XR** ile ek sıkıştırılmış olabilir.
- `textures/temp_lzma_*.bin` dosyaları → önceki bir oturumda ATF içindeki **LZMA bloğu**
  çıkarma denemesi yapıldığını gösterir (LZMA sıkıştırması mevcut).
- `cubikon_diffuse_512.png` zaten var → elle ATF2PNG dönüşümünün referans çıktısı
  (decoder doğrulaması için karşılaştırma örneği olarak kullanılabilir).

### Decode zinciri (hedef)
```
.atf → header parse → subformat + mip tablosu
     → her mip: (varsa) LZMA/JPEG-XR decompress
     → DXT/BC decode → RGBA piksel
     → PIL ile .png yaz
```

### Temizlik
`textures/temp_lzma_*.bin` (5 dosya) artık geçici deneme artığı — pipeline kurulunca
silinebilir. Şimdilik referans olarak bırakılıyor.
