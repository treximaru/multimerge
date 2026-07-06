# Gemini MultiMerge v2

Script Python untuk menggabungkan data CSV ke template SVG, mengkonversi ke PDF (via Inkscape), lalu menggabungkan semua PDF menjadi satu file PDF multipage (via Ghostscript).

## Arsitektur

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  FASE 1     │ --> │  FASE 2     │ --> │  FASE 3     │ --> │  FASE 4     │
│  Merge CSV  │     │  Convert    │     │  Combine    │     │  Cleanup    │
│  -> SVG     │     │  SVG -> PDF │     │  PDF -> PDF  │     │  Hapus      │
│             │     │             │     │  multipage   │     │  file temp  │
└─────────────┘     └─────────────┘     └─────────────┘     └─────────────┘
  Paralel              Paralel              Ghostscript        Hapus file
  (semua CPU)          (50% CPU)            sequential          & workdir
```

## Dependencies

| Tool | Fungsi | Install (Debian/Ubuntu) |
|------|--------|------------------------|
| Python 3.7+ | Runtime | `sudo apt install python3` |
| Inkscape | Konversi SVG -> PDF | `sudo apt install inkscape` |
| Ghostscript | Gabungkan PDF | `sudo apt install ghostscript` |

## File Structure

```
gemini-multimerge-v2/
├── gemini-multimerge-v2.py   # Script utama
├── template.svg              # Template SVG dengan placeholder %VAR_xxx%
├── data.csv                  # File data CSV
└── README.md                 # Dokumentasi ini
```

## Format CSV

File CSV harus memiliki header yang sesuai dengan placeholder di template SVG.

**Contoh CSV:**
```csv
a1,a2,a3,a4,a5,a6,a7,a8,a9,a10,b1,b2,b3,b4,b5,b6,b7,b8,b9,b10,c1,c2
03001,03101,03201,...,Afina Rizkaningsih,Eni Purwanti,...,Juli 2026,Agustus 2026
```

**Mapping ke template:**
- Header `a1` -> placeholder `%VAR_a1%` di template SVG
- Header `c1` -> placeholder `%VAR_c1%` di template SVG
- dst.

## Template SVG

Template SVG harus menggunakan format placeholder `%VAR_NAMA_KOLOM%`:

```xml
<text id="text1">
  <tspan>%VAR_a1%</tspan>
</text>
<text id="text2">
  <tspan>%VAR_b1%</tspan>
</text>
```

## Penggunaan

### Dasar (menggunakan default)

```bash
python gemini-multimerge-v2.py
```

### Custom path

```bash
python gemini-multimerge-v2.py \
  --template template.svg \
  --data data.csv \
  --output hasil.pdf
```

### Custom Inkscape/Ghostscript path

```bash
python gemini-multimerge-v2.py \
  --inkscape /usr/bin/inkscape \
  --ghostscript /usr/bin/gs
```

### Custom timeout dan workers

```bash
python gemini-multimerge-v2.py \
  --timeout 180 \
  --convert-workers 4
```

## Command Line Arguments

| Argument | Default | Deskripsi |
|----------|---------|-----------|
| `--template` | `template.svg` | File SVG template |
| `--data` | `data.csv` | File CSV data |
| `--output` | `output.pdf` | File output PDF |
| `--inkscape` | `inkscape` | Path ke Inkscape |
| `--ghostscript` | `gs` | Path ke Ghostscript |
| `--timeout` | `120` | Timeout per konversi (detik) |
| `--convert-workers` | `setengah CPU` | Jumlah worker fase konversi |

## Perubahan dari v1

| Fitur | v1 | v2 |
|-------|----|----|
| CLI arguments | Hardcoded | `argparse` dengan `--flags` |
| Working directory | Direct di cwd | Unik per eksekusi (timestamp + PID) |
| Timeout | Tidak ada | 120 detik per file SVG |
| Cleanup on error | Tidak ada | Selalu cleanup via try/finally |
| Natural sort | `split("_")` | Regex `(\d+)` |
| ProcessPoolExecutor | Dibuat ulang tiap loop | Reuse dalam scope |
| Output progress | Terbatas | Detail per putaran (success/fail count) |
| Error reporting | `print` ke stderr | Return tuple `(success, error_msg)` |

## Troubleshooting

### "Inkscape tidak ditemukan"
```bash
# Install Inkscape
sudo apt install inkscape

# Atau specify path manual
python gemini-multimerge-v2.py --inkscape /usr/bin/inkscape
```

### "Ghostscript tidak ditemukan"
```bash
# Install Ghostscript
sudo apt install ghostscript

# Atau specify path manual
python gemini-multimerge-v2.py --ghostscript /usr/bin/gs
```

### "File SVG gagal dikonversi"
1. Cek apakah template SVG valid (bisa dibuka di Inkscape)
2. Coba tingkatkan timeout: `--timeout 180`
3. File SVG yang gagal akan tetap disimpan untuk debugging

### "Jumlah SVG != jumlah baris CSV"
1. Cek format CSV (pastikan tidak ada baris kosong)
2. Cek apakah ada karakter aneh di CSV
3. Cek log error di stderr

## License

Internal use only.
