"""Utilitas bersama untuk semua modul VideoStudio Terpadu.

Berisi: loader config, runner subprocess dengan logging, helper ffprobe,
sanitasi nama file, konversi waktu, dan pengecekan RAM.
"""
import os
import re
import shlex
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Root project = folder satu tingkat di atas modules/
ROOT_DIR = Path(__file__).resolve().parent.parent

# Cache config agar tidak dibaca berulang kali
_CONFIG_CACHE: Optional[Dict[str, Any]] = None

# Konfigurasi default — dipakai jika config.yaml tidak ada atau PyYAML belum terpasang.
DEFAULT_CONFIG: Dict[str, Any] = {
    "video": {
        "width": 1080,
        "height": 1920,
        "fps": 30,
        "crf": 18,
        "preset": "medium",
        "max_clip_mb": 50,
        "profile": "high",
        "level": "4.1",
    },
    "audio": {"codec": "aac", "bitrate": "192k", "sample_rate": 48000, "channels": 2},
    "encode": {"threads": 4, "seek_preroll": 2.0},
    "transcription": {"model": "base", "engine": "whisper", "lang": "id", "ram_guard_gb": 3.0},
    "music": {"volume": 0.20},
    "clip": {"min_sec": 15, "target_sec": 25, "max_sec": 100},
    "compile": {"target_duration": 60},
    "paths": {
        "font_bold": "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "font_regular": "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    },
}


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    # Gabungkan dua dict secara rekursif (override menimpa base).
    result = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """Baca config.yaml dan gabungkan dengan default. Aman jika file/lib hilang."""
    global _CONFIG_CACHE
    if _CONFIG_CACHE is not None and config_path is None:
        return _CONFIG_CACHE

    path = Path(config_path) if config_path else (ROOT_DIR / "config.yaml")
    config = dict(DEFAULT_CONFIG)
    if path.exists():
        try:
            import yaml  # PyYAML opsional; fallback ke default jika tidak ada.

            with open(path, "r", encoding="utf-8") as fh:
                loaded = yaml.safe_load(fh) or {}
            config = _deep_merge(DEFAULT_CONFIG, loaded)
        except ImportError:
            print("[WARNING] PyYAML belum terpasang — memakai konfigurasi default.")
        except Exception as exc:
            print(f"[WARNING] Gagal membaca config.yaml ({exc}) — memakai default.")

    if config_path is None:
        _CONFIG_CACHE = config
    return config


def ensure_dir(path: str) -> str:
    """Pastikan folder ada; kembalikan path-nya."""
    os.makedirs(path, exist_ok=True)
    return path


def ensure_parent_dir(path: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def resolve_path(value: str) -> str:
    """Path relatif dihitung dari ROOT_DIR agar aman dijalankan dari folder mana pun."""
    p = Path(value).expanduser()
    return str(p) if p.is_absolute() else str(ROOT_DIR / p)


def sanitize_filename(value: str, max_len: int = 80) -> str:
    """Bersihkan judul agar aman dipakai sebagai nama file di Linux."""
    safe = re.sub(r"[^0-9a-zA-Z\-_. ]+", "", value or "")
    safe = re.sub(r"\s+", "_", safe).strip("_-")
    return safe[:max_len] or "video"


def format_hhmmss(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def hhmmss_to_sec(ts: str) -> float:
    parts = [float(p) for p in str(ts).split(":")]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    return parts[0]


def write_log(log_path: str, message: str) -> None:
    """Log sederhana agar kegagalan bisa ditelusuri setelah pipeline selesai."""
    try:
        ensure_parent_dir(log_path)
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(message.rstrip() + "\n")
    except Exception:
        # Logging tidak boleh menghentikan pipeline.
        pass


def run_cmd(cmd: List[str], check: bool = False) -> Tuple[bool, str]:
    """Jalankan perintah, kembalikan (sukses, output/stderr).

    Tidak pernah melempar kecuali check=True dan perintah gagal.
    """
    try:
        p = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError:
        msg = f"Perintah tidak ditemukan: {cmd[0]}"
        if check:
            raise RuntimeError(msg)
        return False, msg
    if p.returncode != 0:
        msg = (p.stderr or p.stdout or "").strip()
        if check:
            raise RuntimeError(msg)
        return False, msg
    return True, (p.stdout or "").strip()


def run_step(command: List[str], step_name: str, log_path: str, allow_fail: bool = False) -> bool:
    """Jalankan perintah panjang sambil streaming output ke terminal + log."""
    command_text = " ".join(shlex.quote(str(x)) for x in command)
    print(f"\n[{step_name}] menjalankan: {command_text}")
    write_log(log_path, f"\n[{datetime.now().isoformat(timespec='seconds')}] {step_name}")
    write_log(log_path, f"$ {command_text}")
    try:
        process = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1
        )
        if process.stdout is not None:
            for line in process.stdout:
                print(line, end="")
                write_log(log_path, line)
        process.wait()
        if process.returncode != 0:
            message = f"[ERROR] {step_name} gagal dengan kode {process.returncode}."
            print(message)
            write_log(log_path, message)
            return allow_fail
        return True
    except FileNotFoundError:
        message = f"[ERROR] Perintah tidak ditemukan: {command[0]}"
        print(message)
        write_log(log_path, message)
        return False
    except Exception as exc:
        message = f"[ERROR] {step_name} gagal: {exc}"
        print(message)
        write_log(log_path, message)
        return allow_fail


def ffprobe_duration(path: str) -> float:
    """Durasi video/audio dalam detik via ffprobe. 0.0 jika gagal."""
    ok, out = run_cmd([
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", path,
    ])
    if not ok or not out:
        return 0.0
    try:
        return float(out)
    except ValueError:
        return 0.0


def ffprobe_resolution(path: str) -> Tuple[int, int]:
    """Kembalikan (width, height) video; (0,0) jika gagal."""
    ok, out = run_cmd([
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "csv=s=x:p=0", path,
    ])
    if not ok or "x" not in out:
        return 0, 0
    try:
        w, h = out.split("x")[:2]
        return int(w), int(h)
    except Exception:
        return 0, 0


def has_audio_stream(path: str) -> bool:
    """True jika file punya minimal satu stream audio. False bila gagal/tidak ada."""
    ok, out = run_cmd([
        "ffprobe", "-v", "error", "-select_streams", "a",
        "-show_entries", "stream=index",
        "-of", "csv=p=0", path,
    ])
    return ok and bool(out.strip())


def available_ram_gb() -> Optional[float]:
    """RAM tersedia dalam GB, atau None jika psutil tidak ada."""
    try:
        import psutil

        return psutil.virtual_memory().available / (1024 ** 3)
    except Exception:
        return None


def guard_model_for_ram(model: str, threshold_gb: float = 3.0) -> str:
    """Turunkan model Whisper ke 'tiny' jika RAM tersedia di bawah threshold."""
    avail = available_ram_gb()
    if avail is not None and avail < threshold_gb and model != "tiny":
        print(f"[WARNING] RAM tersedia rendah ({avail:.2f} GB). Model diturunkan ke 'tiny'.")
        return "tiny"
    return model


def find_video_in_dir(directory: str, exts=(".mp4", ".mov", ".mkv", ".webm", ".avi")) -> Optional[str]:
    """Cari file video pertama (alfabetis) dalam folder."""
    if not os.path.isdir(directory):
        return None
    files = sorted(f for f in os.listdir(directory) if f.lower().endswith(exts))
    return os.path.join(directory, files[0]) if files else None


def find_subtitle_file(subtitle_dir: str, basename: str = "", exts=(".srt",)) -> Optional[str]:
    """Cari file subtitle di folder. Utamakan stem yang cocok dengan `basename`,
    fallback ke file pertama (alfabetis). None bila folder kosong/tidak ada."""
    subtitle_dir = resolve_path(subtitle_dir)
    if not os.path.isdir(subtitle_dir):
        return None
    files = sorted(f for f in os.listdir(subtitle_dir) if f.lower().endswith(exts))
    if not files:
        return None
    if basename:
        stem = os.path.splitext(os.path.basename(basename))[0].lower()
        for f in files:
            if os.path.splitext(f)[0].lower() == stem:
                return os.path.join(subtitle_dir, f)
    return os.path.join(subtitle_dir, files[0])


def find_font(preferred: str) -> str:
    """Kembalikan font path valid; fallback ke fc-match jika preferred tidak ada."""
    if preferred and os.path.exists(preferred):
        return preferred
    ok, out = run_cmd(["fc-match", "-f", "%{file}", "sans:bold"])
    if ok and out and os.path.exists(out):
        return out
    return preferred  # biarkan FFmpeg yang memutuskan fallback terakhir


def check_dependencies(required=("ffmpeg", "ffprobe")) -> List[str]:
    """Kembalikan daftar dependency yang TIDAK ditemukan di PATH."""
    return [cmd for cmd in required if shutil.which(cmd) is None]
