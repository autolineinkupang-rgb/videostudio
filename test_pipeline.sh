#!/usr/bin/env bash
# =============================================================================
# Validasi cepat 3 mode VideoStudio Terpadu.
# Tidak mengunduh apa pun: mode single & compile diuji dengan video sampel
# dari folder input/. Mode clipper hanya divalidasi dari sisi --help/argumen.
# =============================================================================
set -uo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

PY="$ROOT_DIR/.venv/bin/python"
[ -x "$PY" ] || PY="python3"

PASS=0; FAIL=0
check() {
  local label="$1"; shift
  echo; echo "==> $label"
  if "$@"; then echo "[OK] $label"; PASS=$((PASS+1)); else echo "[GAGAL] $label"; FAIL=$((FAIL+1)); fi
}

# 1. Help & impor modul harus selalu bisa.
check "videostudio.py --help" "$PY" videostudio.py --help
check "impor semua modul" "$PY" -c "import sys; sys.path.insert(0,'.'); from modules import utils, downloader, transcriber, moment_detector, encoder, subtitle_burner, color_grader, audio_mixer, music_finder, reporter; print('modules OK')"

# 2. Compile syntax-check semua modul.
check "compile-all py" "$PY" -m py_compile videostudio.py modules/*.py

# 3. Mode single bila ada video di input/.
SAMPLE="$(find input -maxdepth 1 -type f \( -iname '*.mp4' -o -iname '*.mov' -o -iname '*.mkv' -o -iname '*.webm' \) 2>/dev/null | head -n1)"
if [ -n "$SAMPLE" ]; then
  check "mode single" "$PY" videostudio.py --mode single "$SAMPLE" --no-auto --no-music
  check "mode compile" "$PY" videostudio.py --mode compile --duration 30
else
  echo; echo "[SKIP] Mode single/compile — tidak ada video sampel di input/."
fi

echo
echo "════════════════════════════════════"
echo "  Lulus: $PASS | Gagal: $FAIL"
echo "════════════════════════════════════"
[ "$FAIL" -eq 0 ]
