#!/usr/bin/env bash
# =============================================================================
# Installer terpadu VideoStudio Terpadu
# Membuat .venv/, install dependensi sistem + Python, lalu validasi.
# =============================================================================
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

VENV_DIR=".venv"

step() { echo; echo "==> $1"; }
ok()   { echo "[OK] $1"; }
fail() { echo "[GAGAL] $1"; exit 1; }

run_step() {
  local label="$1"; shift
  echo "- $label"
  if "$@"; then ok "$label"; else fail "$label"; fi
}

step "Menginstal dependensi sistem (Linux Mint/Ubuntu)"
run_step "apt update" sudo apt update
run_step "install ffmpeg, python3-pip, python3-venv, fonts" \
  sudo apt install -y ffmpeg python3-pip python3-venv fonts-dejavu

step "Membuat virtualenv"
if [ ! -d "$VENV_DIR" ]; then
  run_step "buat virtualenv $VENV_DIR" python3 -m venv "$VENV_DIR"
else
  ok "virtualenv $VENV_DIR sudah ada"
fi

PY="$ROOT_DIR/$VENV_DIR/bin/python"

step "Menginstal dependensi Python"
run_step "upgrade pip/setuptools/wheel" "$PY" -m pip install --upgrade pip setuptools wheel

echo "- install PyTorch CPU-only (untuk openai-whisper)"
if "$PY" -m pip install --index-url https://download.pytorch.org/whl/cpu "torch>=2.0.0"; then
  ok "PyTorch CPU-only"
else
  echo "[WARNING] Gagal memasang PyTorch CPU-only; lanjut, pip akan mencoba default."
fi

run_step "install requirements.txt" "$PY" -m pip install -r requirements.txt

step "Memeriksa status dependensi"
READY=1
check_cmd() {
  local label="$1"; shift
  if "$@" >/dev/null 2>&1; then ok "$label"; else echo "[GAGAL] $label"; READY=0; fi
}
check_import() {
  if "$PY" - "$1" <<'PY' >/dev/null 2>&1
import importlib, sys
importlib.import_module(sys.argv[1])
PY
  then ok "import $1"; else echo "[GAGAL] import $1"; READY=0; fi
}

check_cmd "ffmpeg" ffmpeg -version
check_cmd "ffprobe" ffprobe -version
check_cmd "yt-dlp module" "$PY" -m yt_dlp --version
check_cmd "auto-editor" "$PY" -m auto_editor --version
check_import "whisper"
check_import "faster_whisper"
check_import "numpy"
check_import "psutil"
check_import "yaml"

# OpenCV opsional (untuk --smart-crop). Tidak fatal bila tidak ada.
if "$PY" - <<'PY' >/dev/null 2>&1
import cv2  # noqa: F401
PY
then ok "import cv2 (smart-crop)"; else
  echo "[i] OpenCV belum ada — fitur --smart-crop akan fallback ke center/blur."
  echo "    Pasang: $PY -m pip install opencv-python-headless"
fi

mkdir -p input sound music_lib efek output/clips temp

# Kembalikan kepemilikan ke user jika dijalankan via sudo.
if [ -n "${SUDO_USER:-}" ] && [ "$SUDO_USER" != "root" ]; then
  chown -R "$SUDO_USER":"$SUDO_USER" "$VENV_DIR" input sound music_lib efek output temp 2>/dev/null || true
fi

echo
if [ "$READY" -eq 1 ]; then
  ok "Semua siap."
else
  echo "Beberapa dependency belum siap. Periksa pesan [GAGAL] di atas."
  exit 1
fi

echo
echo "Verifikasi:"
echo "  $VENV_DIR/bin/python videostudio.py --help"
echo
echo "Contoh clipper:"
echo "  $VENV_DIR/bin/python videostudio.py --mode clipper \"https://www.youtube.com/watch?v=XXXX\" --subtitle --max-clips 5"
