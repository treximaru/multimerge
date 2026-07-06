#!/usr/bin/env python3
"""
Gemini MultiMerge v2 — Script untuk menggabungkan data CSV ke template SVG,
mengkonversi ke PDF (via Inkscape), lalu menggabungkan semua PDF
menjadi satu file PDF multipage (via Ghostscript).

Arsitektur:
  Fase 1 (Merge)     : Baca CSV, generate file SVG secara paralel
  Fase 2 (Convert)   : Konversi SVG -> PDF via Inkscape secara paralel (retry loop)
  Fase 3 (Combine)   : Gabungkan semua PDF via Ghostscript
  Fase 4 (Cleanup)   : Hapus file sementara

Dependencies:
  - Python 3.7+
  - Inkscape (CLI) — untuk konversi SVG -> PDF
  - Ghostscript (gs) — untuk menggabungkan PDF

Usage:
  python gemini-multimerge-v2.py [--template FILE] [--data FILE] [--output FILE]
                                 [--inkscape PATH] [--ghostscript PATH]
                                 [--timeout SECONDS] [--convert-workers N]
"""

import argparse
import csv
import glob
import os
import re
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path


# =============================================================================
# Konstanta
# =============================================================================
DEFAULT_TEMPLATE = "template.svg"
DEFAULT_DATA = "data.csv"
DEFAULT_OUTPUT = "output.pdf"
DEFAULT_INKSCAPE = "inkscape"
DEFAULT_GHOSTSCRIPT = "gs"
DEFAULT_TIMEOUT = 120  # detik per konversi Inkscape
DEFAULT_CONVERT_WORKERS_RATIO = 0.5  # gunakan 50% CPU untuk konversi


# =============================================================================
# Fungsi Utilitas
# =============================================================================
def find_executable(name, custom_path=None):
    """Cari executable di PATH atau custom path."""
    if custom_path:
        if os.path.isfile(custom_path) and os.access(custom_path, os.X_OK):
            return custom_path
        # Coba cari di PATH juga
        from shutil import which
        found = which(custom_path)
        if found:
            return found

    from shutil import which
    found = which(name)
    if found:
        return found

    return None


def natural_sort_key(filename):
    """Sort key untuk filename dengan angka (output_00001.pdf)."""
    base = os.path.basename(filename)
    match = re.search(r'(\d+)', base)
    return int(match.group(1)) if match else 0


def create_safe_workdir(base_dir=None):
    """Buat working directory unik untuk setiap eksekusi."""
    if base_dir is None:
        base_dir = os.getcwd()
    timestamp = int(time.time() * 1000)
    workdir_name = f".gemini_merge_work_{timestamp}_{os.getpid()}"
    workdir = os.path.join(base_dir, workdir_name)
    os.makedirs(workdir, exist_ok=True)
    return workdir


# =============================================================================
# Fungsi Konversi
# =============================================================================
def generate_pdf_from_svg(inkscape_path, inkscape_args, input_svg, output_pdf, timeout=120):
    """
    Konversi file SVG ke PDF menggunakan Inkscape.
    Akan timeout jika proses lebih lama dari `timeout` detik.
    """
    full_command = [
        inkscape_path,
        *inkscape_args,
        input_svg,
        "--export-filename=" + output_pdf,
    ]
    subprocess.run(
        full_command,
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


# =============================================================================
# Worker Functions (untuk ProcessPoolExecutor)
# =============================================================================
def _merge_worker(idx, row, template_svg, workdir):
    """
    Worker untuk FASE 1: Baca 1 baris CSV, generate 1 file SVG.
    return: (idx, success, error_msg)
    """
    output_svg = os.path.join(workdir, f"output_{idx:05d}.svg")

    try:
        with open(template_svg, "r", encoding="utf-8") as f:
            template_content = f.read()

        for key, value in row.items():
            # Abaikan kolom tanpa header (key=None dari restkey)
            if key is None:
                continue

            val = value if value is not None else ""

            # Jika header duplikat (value jadi list), ambil item pertama
            if isinstance(val, list):
                val = val[0] if val else ""

            template_content = template_content.replace(f"%VAR_{key}%", val)

        with open(output_svg, "w", encoding="utf-8") as f:
            f.write(template_content)

        return (idx, True, None)

    except Exception as e:
        return (idx, False, str(e))


def _convert_worker(svg_file, inkscape_path, inkscape_args, timeout):
    """
    Worker untuk FASE 2: Konversi 1 file SVG -> PDF.
    Jika sukses, hapus file SVG.
    return: (svg_file, success, error_msg)
    """
    pdf_file = svg_file.replace(".svg", ".pdf")

    try:
        generate_pdf_from_svg(inkscape_path, inkscape_args, svg_file, pdf_file, timeout)

        # Hapus SVG jika konversi sukses
        if os.path.exists(svg_file):
            os.remove(svg_file)
        return (svg_file, True, None)

    except subprocess.CalledProcessError as e:
        return (svg_file, False, e.stderr.strip() if e.stderr else "Unknown Inkscape error")
    except subprocess.TimeoutExpired:
        return (svg_file, False, f"Inkscape timeout setelah {timeout} detik")
    except Exception as e:
        return (svg_file, False, str(e))


# =============================================================================
# Fase 1: Merge CSV -> SVG
# =============================================================================
def run_merge_phase(template_svg, data_csv, workdir):
    """
    FASE 1: Membaca CSV dan membuat semua file .svg secara paralel.
    return: (success, total_rows)
    """
    print("=" * 60)
    print("FASE 1: Merge CSV -> SVG")
    print("=" * 60)

    # --- Validasi file template ---
    if not os.path.isfile(template_svg):
        print(f"ERROR: File template tidak ditemukan: {template_svg}", file=sys.stderr)
        return False, 0

    # --- Baca CSV ---
    try:
        with open(data_csv, "r", encoding="utf-8") as csv_file:
            csv_reader = list(
                csv.DictReader(csv_file, restkey=None, restval="")
            )

        total_rows = len(csv_reader)
        if total_rows == 0:
            print("ERROR: File CSV tidak memiliki baris data.", file=sys.stderr)
            return False, 0

        print(f"  File CSV    : {data_csv}")
        print(f"  Total baris : {total_rows}")

    except FileNotFoundError:
        print(f"ERROR: File CSV tidak ditemukan: {data_csv}", file=sys.stderr)
        return False, 0
    except Exception as e:
        print(f"ERROR saat membaca CSV: {e}", file=sys.stderr)
        return False, 0

    # --- Proses paralel (semua CPU) ---
    worker_count = os.cpu_count() or 4
    print(f"  Workers     : {worker_count} (semua CPU)")

    errors = []
    with ProcessPoolExecutor(max_workers=worker_count) as executor:
        futures = {
            executor.submit(_merge_worker, idx, row, template_svg, workdir): idx
            for idx, row in enumerate(csv_reader)
        }

        for future in as_completed(futures):
            idx, success, error_msg = future.result()
            if not success:
                errors.append((idx, error_msg))
                print(f"  ERROR baris {idx}: {error_msg}", file=sys.stderr)

    # --- Verifikasi ---
    svg_files = glob.glob(os.path.join(workdir, "output_*.svg"))
    svg_count = len(svg_files)

    print(f"  SVG dibuat  : {svg_count} / {total_rows}")

    if errors:
        print(f"  PERINGATAN : {len(errors)} baris gagal diproses.", file=sys.stderr)

    if svg_count == 0:
        print("  ERROR: Tidak ada file SVG yang dibuat.", file=sys.stderr)
        return False, 0

    if svg_count != total_rows:
        print("  PERINGATAN: Jumlah SVG != jumlah baris CSV.", file=sys.stderr)

    print("  FASE 1 selesai.\n")
    return True, total_rows


# =============================================================================
# Fase 2: Convert SVG -> PDF
# =============================================================================
def run_convert_phase(inkscape_path, inkscape_args, workdir, timeout, convert_workers):
    """
    FASE 2: Mengonversi semua .svg ke .pdf secara paralel.
    Menggunakan retry loop dengan deteksi macet.
    return: success (bool)
    """
    print("=" * 60)
    print("FASE 2: Konversi SVG -> PDF")
    print("=" * 60)
    print(f"  Workers     : {convert_workers} ({int(DEFAULT_CONVERT_WORKERS_RATIO*100)}% CPU)")
    print(f"  Timeout     : {timeout} detik per file")

    gagal_sebelumnya = -1
    putaran = 0

    while True:
        svg_files = sorted(
            glob.glob(os.path.join(workdir, "output_*.svg")),
            key=natural_sort_key,
        )

        if not svg_files:
            print("  Semua file SVG telah dikonversi.\n")
            return True

        putaran += 1
        gagal_saat_ini = len(svg_files)
        print(f"  Putaran {putaran}: {gagal_saat_ini} file tersisa...")

        # Deteksi macet
        if gagal_saat_ini == gagal_sebelumnya:
            print(f"\n  ERROR KRITIS: {gagal_saat_ini} file tidak dapat dikonversi.", file=sys.stderr)
            print("  Kemungkinan file SVG rusak atau Inkscape error.", file=sys.stderr)
            print("  Menghentikan FASE 2.", file=sys.stderr)
            return False

        gagal_sebelumnya = gagal_saat_ini

        # Proses paralel
        with ProcessPoolExecutor(max_workers=convert_workers) as executor:
            futures = [
                executor.submit(_convert_worker, svg_file, inkscape_path, inkscape_args, timeout)
                for svg_file in svg_files
            ]

            success_count = 0
            fail_count = 0
            for future in as_completed(futures):
                svg_file, success, error_msg = future.result()
                if success:
                    success_count += 1
                else:
                    fail_count += 1
                    basename = os.path.basename(svg_file)
                    print(f"    GAGAL {basename}: {error_msg}", file=sys.stderr)

        print(f"  Hasil putaran {putaran}: {success_count} sukses, {fail_count} gagal")
        time.sleep(1)  # Jeda agar sistem 'bernapas'


# =============================================================================
# Fase 3: Gabung PDF
# =============================================================================
def merge_to_multipage_pdf(ghostscript_path, workdir, output_pdf):
    """
    FASE 3: Menggabungkan semua file output_*.pdf menjadi satu file PDF.
    return: success (bool)
    """
    print("=" * 60)
    print("FASE 3: Gabung PDF")
    print("=" * 60)

    pdf_files = sorted(
        glob.glob(os.path.join(workdir, "output_*.pdf")),
        key=natural_sort_key,
    )

    if not pdf_files:
        print("  Tidak ada file PDF ditemukan untuk digabung.", file=sys.stderr)
        return False

    print(f"  File PDF    : {len(pdf_files)} file")
    print(f"  Output      : {output_pdf}")

    try:
        subprocess.run(
            [
                ghostscript_path,
                "-q",
                "-dNOPAUSE",
                "-dBATCH",
                "-sDEVICE=pdfwrite",
                f"-sOutputFile={output_pdf}",
                *pdf_files,
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=300,  # 5 menit timeout untuk merge
        )
    except subprocess.CalledProcessError as e:
        print(f"  GAGAL saat menggabung PDF: {e.stderr}", file=sys.stderr)
        return False
    except FileNotFoundError:
        print(f"  GAGAL: Ghostscript tidak ditemukan: {ghostscript_path}", file=sys.stderr)
        print("  Pastikan Ghostscript terinstal dan ada di PATH.", file=sys.stderr)
        return False
    except subprocess.TimeoutExpired:
        print("  GAGAL: Ghostscript timeout (lebih dari 5 menit).", file=sys.stderr)
        return False

    print("  FASE 3 selesai.\n")
    return True


# =============================================================================
# Fase 4: Cleanup
# =============================================================================
def cleanup_intermediate_files(workdir, output_pdf):
    """Hapus semua file sementara di working directory."""
    print("=" * 60)
    print("FASE 4: Cleanup")
    print("=" * 60)

    count = 0
    for f in glob.glob(os.path.join(workdir, "*")):
        try:
            os.remove(f)
            count += 1
        except OSError as e:
            print(f"  Warning: Gagal menghapus {f}: {e}", file=sys.stderr)

    # Hapus workdir juga
    try:
        os.rmdir(workdir)
        print(f"  Working directory dihapus: {workdir}")
    except OSError:
        print(f"  Working directory tidak bisa dihapus (mungkin masih ada file): {workdir}")

    print(f"  {count} file sementara dihapus.")
    print("  FASE 4 selesai.\n")


# =============================================================================
# Main
# =============================================================================
def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Gemini MultiMerge v2 — Gabungkan CSV + SVG template -> PDF multipage",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Contoh penggunaan:
  python gemini-multimerge-v2.py
  python gemini-multimerge-v2.py --template template.svg --data data.csv --output hasil.pdf
  python gemini-multimerge-v2.py --timeout 180 --convert-workers 4
        """,
    )
    parser.add_argument("--template", default=DEFAULT_TEMPLATE, help=f"File SVG template (default: {DEFAULT_TEMPLATE})")
    parser.add_argument("--data", default=DEFAULT_DATA, help=f"File CSV data (default: {DEFAULT_DATA})")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help=f"File output PDF (default: {DEFAULT_OUTPUT})")
    parser.add_argument("--inkscape", default=DEFAULT_INKSCAPE, help=f"Path ke Inkscape (default: {DEFAULT_INKSCAPE})")
    parser.add_argument("--ghostscript", default=DEFAULT_GHOSTSCRIPT, help=f"Path ke Ghostscript (default: {DEFAULT_GHOSTSCRIPT})")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help=f"Timeout per konversi SVG dalam detik (default: {DEFAULT_TIMEOUT})")
    parser.add_argument("--convert-workers", type=int, default=None, help="Jumlah worker untuk fase konversi (default: setengah CPU)")
    return parser.parse_args()


def check_dependencies(inkscape_path, ghostscript_path):
    """Cek apakah Inkscape dan Ghostscript tersedia."""
    all_ok = True

    if not inkscape_path:
        print("ERROR: Inkscape tidak ditemukan di PATH.", file=sys.stderr)
        print("  Install: sudo apt install inkscape  (Debian/Ubuntu)", file=sys.stderr)
        all_ok = False
    else:
        print(f"  Inkscape    : {inkscape_path}")

    if not ghostscript_path:
        print("ERROR: Ghostscript tidak ditemukan di PATH.", file=sys.stderr)
        print("  Install: sudo apt install ghostscript  (Debian/Ubuntu)", file=sys.stderr)
        all_ok = False
    else:
        print(f"  Ghostscript : {ghostscript_path}")

    return all_ok


def main():
    """Fungsi utama."""
    args = parse_args()

    print()
    print("=" * 60)
    print("  Gemini MultiMerge v2")
    print("=" * 60)
    print()

    # --- Cari executable ---
    inkscape_path = find_executable(args.inkscape, args.inkscape)
    ghostscript_path = find_executable(args.ghostscript, args.ghostscript)

    # --- Cek dependencies ---
    print("Mengecek dependencies...")
    if not check_dependencies(inkscape_path, ghostscript_path):
        sys.exit(1)
    print()

    # --- Hitung workers untuk konversi ---
    total_cpu = os.cpu_count() or 4
    convert_workers = args.convert_workers or max(1, int(total_cpu * DEFAULT_CONVERT_WORKERS_RATIO))
    print(f"  Total CPU   : {total_cpu}")
    print(f"  Convert WS  : {convert_workers}")
    print()

    # --- Buat working directory unik ---
    workdir = create_safe_workdir(os.path.dirname(os.path.abspath(args.output)) or os.getcwd())
    print(f"  Working dir : {workdir}")
    print()

    try:
        # --- FASE 1: Merge ---
        sukses_merge, total_rows = run_merge_phase(args.template, args.data, workdir)
        if not sukses_merge:
            raise RuntimeError("FASE 1 (Merge) gagal. Cek log di atas.")

        # --- FASE 2: Convert ---
        sukses_konversi = run_convert_phase(
            inkscape_path, [], workdir, args.timeout, convert_workers
        )
        if not sukses_konversi:
            print("  PERINGATAN: Beberapa file SVG gagal dikonversi.", file=sys.stderr)
            print("  Melanjutkan ke FASE 3 dengan file PDF yang tersedia...\n")

        # --- FASE 3: Gabung PDF ---
        sukses_gabung = merge_to_multipage_pdf(ghostscript_path, workdir, args.output)
        if not sukses_gabung:
            raise RuntimeError("FASE 3 (Gabung PDF) gagal. Cek log di atas.")

        # --- FASE 4: Cleanup ---
        cleanup_intermediate_files(workdir, args.output)

        # --- Selesai ---
        print("=" * 60)
        print("  SKRIP SELESAI SUKSES")
        print(f"  Output: {args.output}")
        print("=" * 60)
        print()

    except Exception as e:
        print(f"\nSKRIP GAGAL: {e}", file=sys.stderr)
        # Cleanup tetap dijalankan meski gagal
        if os.path.exists(workdir):
            cleanup_intermediate_files(workdir, args.output)
        sys.exit(1)


if __name__ == "__main__":
    main()
