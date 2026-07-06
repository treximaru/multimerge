# MultiMerge (Custom Mail Merge for Inkscape)

Script Python untuk merge data CSV ke template SVG, konversi ke PDF via Inkscape, lalu gabungkan semua PDF menjadi satu file multipage via Ghostscript.

Cocok untuk cetak kupon, voucher, kartu nama, atau dokumen lain yang isinya sama tapi datanya berbeda per baris.

## Arsitektur

```
CSV + Template SVG
       │
       ▼
┌──────────────┐
│  FASE 1      │  Merge: baca CSV, generate file SVG per baris
│  (Paralel)   │  Semua CPU dipakai
└──────┬───────┘
       │  output_00000.svg, output_00001.svg, ...
       ▼
┌──────────────┐
│  FASE 2      │  Convert: SVG → PDF via Inkscape
│  (Paralel)   │  50% CPU, retry otomatis jika gagal
└──────┬───────┘
       │  output_00000.pdf, output_00001.pdf, ...
       ▼
┌──────────────┐
│  FASE 3      │  Combine: gabung semua PDF via Ghostscript
│  (Sequential)│
└──────┬───────┘
       │  output.pdf (multipage)
       ▼
┌──────────────┐
│  FASE 4      │  Cleanup: hapus file sementara
└──────────────┘
```

## Dependencies

| Tool | Fungsi | Install |
|------|--------|---------|
| Python 3.7+ | Runtime | `sudo apt install python3` |
| Inkscape | Konversi SVG → PDF | `sudo apt install inkscape` |
| Ghostscript | Gabungkan PDF | `sudo apt install ghostscript` |

## File Structure

```
project/
├── multimerge.py        # Script utama
├── template.svg         # Template SVG dengan placeholder %VAR_xxx%
├── data.csv             # File data CSV
├── README.md            # Dokumentasi ini
└── .gitignore
```

## Panduan Cara Pakai

### 1. Siapkan Template SVG

Buat file SVG di Inkscape. Untuk setiap field yang akan diisi dari CSV, tambahkan placeholder dengan format `%VAR_NAMA_KOLOM%`.

**Contoh di Inkscape:**
- Buat text object
- Isi dengan: `%VAR_nama%`
- Atau: `%VAR_alamat%`, `%VAR_no_hp%`, dll

**Contoh isi template.svg (bagian text):**
```xml
<text id="text1">
  <tspan>%VAR_a1%</tspan>
</text>
<text id="text2">
  <tspan>%VAR_b1%</tspan>
</text>
```

### 2. Siapkan File CSV

Buat file CSV dengan header yang sesuai dengan placeholder di template.

**Contoh data.csv:**
```csv
nama,alamat,no_hp,kota
Budi Santoso,Jl. Merdeka No. 1,081234567890,Jakarta
Siti Rahayu,Jl. Sudirman No. 2,085678901234,Bandung
Andi Wijaya,Jl. Gatot Subroto No. 3,089012345678,Surabaya
```

**Aturan CSV:**
- Baris pertama = header (nama kolom)
- Header harus sama dengan placeholder di template (tanpa `%VAR_` dan `%`)
- Gunakan koma (`,`) sebagai pemisah
- Jika ada koma di dalam data, bungkus dengan tanda kutip: `"Jakarta, Indonesia"`

### 3. Jalankan Script

**Dasar (otomatis):**
```bash
python3 multimerge.py
```
Ini akan mencari `template.svg` dan `data.csv` di folder yang sama, hasilnya `output.pdf`.

**Custom:**
```bash
python3 multimerge.py \
  --template voucher.svg \
  --data data_siswa.csv \
  --output voucher_final.pdf
```

**Custom tools:**
```bash
python3 multimerge.py \
  --inkscape /usr/bin/inkscape \
  --ghostscript /usr/bin/gs
```

**Custom performance:**
```bash
python3 multimerge.py \
  --timeout 180 \
  --convert-workers 4
```

### 4. Command Line Arguments

| Argument | Default | Deskripsi |
|----------|---------|-----------|
| `--template` | `template.svg` | File SVG template |
| `--data` | `data.csv` | File CSV data |
| `--output` | `output.pdf` | File output PDF |
| `--inkscape` | `inkscape` | Path ke Inkscape |
| `--ghostscript` | `gs` | Path ke Ghostscript |
| `--timeout` | `120` | Timeout per konversi SVG (detik) |
| `--convert-workers` | `50% CPU` | Jumlah worker fase konversi |

### 5. Contoh Penggunaan Nyata

**Membuat 100 voucher makan:**
```bash
# 1. Buat template voucher di Inkscape
#    Tambahkan placeholder: %VAR_nama%, %VAR_nominal%, %VAR_kode%

# 2. Buat data.csv
#    nama,nominal,kode
#    Budi Santoso,50000,VOU-001
#    Siti Rahayu,75000,VOU-002
#    ...

# 3. Jalankan
python3 multimerge.py --template voucher.svg --data data.csv --output voucher_final.pdf
```

**Membuat kartu nama 50 orang:**
```bash
python3 multimerge.py \
  --template kartu-nama.svg \
  --data daftar-karyawan.csv \
  --output kartu-nama-semua.pdf
```

## Troubleshooting

### "Inkscape tidak ditemukan"
```bash
# Install
sudo apt install inkscape

# Atau specify path
python3 multimerge.py --inkscape /usr/bin/inkscape
```

### "Ghostscript tidak ditemukan"
```bash
# Install
sudo apt install ghostscript

# Atau specify path
python3 multimerge.py --ghostscript /usr/bin/gs
```

### "File SVG gagal dikonversi"
1. Buka template SVG di Inkscape, pastikan valid
2. Coba tingkatkan timeout: `--timeout 180`
3. File SVG yang gagal tetap disimpan untuk debugging

### "Jumlah SVG != jumlah baris CSV"
1. Cek format CSV (tidak ada baris kosong)
2. Cek delimiter (harus koma)
3. Cek log error di stderr

### Error "Gio::DBus::Error"
Error ini muncul sesekali saat Inkscape dijalankan headless. **Tidak berpengaruh pada hasil** — script otomatis retry file yang gagal.

## Perubahan dari v1

| Fitur | v1 | v2 |
|-------|----|----|
| Nama | Gemini MultiMerge | MultiMerge |
| CLI args | Hardcoded | `argparse` dengan `--flags` |
| Working dir | Direct di cwd | Unik per eksekusi |
| Timeout | Tidak ada | 120 detik/file |
| Cleanup on error | Tidak ada | Selalu cleanup |
| Natural sort | `split("_")` | Regex |

## License

Internal use only.
