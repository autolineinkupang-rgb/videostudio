"""Download video + metadata menggunakan yt-dlp.

Berasal dari clipper/download_video.py, disesuaikan untuk struktur modul terpadu.
"""
import json
import os
import re
import shutil
from pathlib import Path
from typing import Dict, Optional, Tuple

from . import utils

FFMPEG_THREADS = utils.load_config()["encode"]["threads"]


def build_download_error(error: str) -> str:
    """Buat pesan kegagalan eksplisit agar user tahu langkah perbaikan berikutnya."""
    text = error or ""
    lower = text.lower()
    if "403" in text or "forbidden" in lower:
        return (
            "YouTube menolak akses (HTTP 403/Forbidden). "
            "Export cookies baru dari browser yang sudah login, lalu jalankan dengan --cookies cookies.txt. "
            f"Detail: {text}"
        )
    if "sign in to confirm" in lower or "bot" in lower:
        return (
            "YouTube meminta verifikasi login/bot. "
            "Buka YouTube di browser, login, tonton sebentar, export cookies baru, lalu pakai --cookies. "
            f"Detail: {text}"
        )
    if "file is empty" in lower or "downloaded file is empty" in lower:
        return (
            "File hasil download kosong. Biasanya cookies tidak valid atau video dilindungi. "
            f"Detail: {text}"
        )
    return f"Gagal download video: {text}"


def download_video(
    url: str,
    output_dir: str,
    cookies: Optional[str] = None,
    browser_cookies: Optional[str] = None,
) -> Tuple[str, str, Dict]:
    """Download video dari URL dan simpan metadata JSON.

    Mengembalikan (mp4_path, metadata_path, metadata).
    """
    try:
        from yt_dlp import YoutubeDL
    except Exception:
        raise RuntimeError("Package yt-dlp belum terpasang. Jalankan install.sh terlebih dahulu.")

    output_dir = utils.resolve_path(output_dir)
    os.makedirs(output_dir, exist_ok=True)
    output_template = os.path.join(output_dir, "%(id)s.%(ext)s")
    last_reported = {"value": -1}

    def progress_hook(status):
        # Progress ringkas — cetak tiap kelipatan 10% agar terminal tidak banjir.
        if status.get("status") == "finished":
            print("Download selesai, merapikan/merge file...")
            return
        if status.get("status") != "downloading":
            return
        match = re.search(r"(\d+(?:\.\d+)?)%", status.get("_percent_str", "").strip())
        if not match:
            return
        percent = int(float(match.group(1)))
        if percent == 100 or percent - last_reported["value"] >= 10:
            last_reported["value"] = percent
            speed = status.get("_speed_str", "").strip()
            eta = status.get("_eta_str", "").strip()
            suffix = f" ({speed}, ETA {eta})" if speed or eta else ""
            print(f"Download progress: {percent}%{suffix}")

    ydl_opts = {
        "format": "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080]/best",
        "format_sort": ["res", "br"],
        "outtmpl": output_template,
        "merge_output_format": "mp4",
        "postprocessor_args": ["-threads", str(FFMPEG_THREADS)],
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "restrictfilenames": True,
        "progress_hooks": [progress_hook],
    }
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path:
        ydl_opts["ffmpeg_location"] = str(Path(ffmpeg_path).parent)
    if cookies:
        ydl_opts["cookiefile"] = utils.resolve_path(cookies)
    elif browser_cookies:
        # Berguna saat YouTube meminta sesi browser yang sudah login.
        ydl_opts["cookiesfrombrowser"] = (browser_cookies,)

    with YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(url, download=True)
        except Exception as exc:
            raise RuntimeError(build_download_error(str(exc)))

    video_id = info.get("id") or "video"
    title = (info.get("title") or "untitled").strip()
    duration = float(info.get("duration") or 0.0)

    # Temukan file hasil download (yt-dlp memakai restrictfilenames).
    mp4_path = os.path.join(output_dir, f"{video_id}.mp4")
    if not os.path.exists(mp4_path):
        for candidate in os.listdir(output_dir):
            if candidate.lower().endswith(".mp4") and candidate.startswith(video_id):
                mp4_path = os.path.join(output_dir, candidate)
                break
    if not os.path.exists(mp4_path):
        raise RuntimeError("Video tidak ditemukan setelah download. Periksa yt-dlp dan URL.")

    metadata = {
        "id": video_id,
        "title": title,
        "title_safe": utils.sanitize_filename(title, max_len=120),
        "duration": duration,
        "description": info.get("description", "") or "",
        "uploader": info.get("uploader", ""),
        "source_url": url,
        "filename": os.path.basename(mp4_path),
    }

    metadata_path = os.path.join(output_dir, "metadata.json")
    with open(metadata_path, "w", encoding="utf-8") as fh:
        json.dump(metadata, fh, indent=2, ensure_ascii=False)

    return mp4_path, metadata_path, metadata


def load_metadata(input_dir: str) -> Dict:
    """Baca metadata.json dari folder input; {} jika tidak ada/invalid."""
    metadata_path = os.path.join(utils.resolve_path(input_dir), "metadata.json")
    if not os.path.exists(metadata_path):
        return {}
    try:
        with open(metadata_path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def find_downloaded_video(input_dir: str) -> Optional[str]:
    """Cari video hasil download — utamakan yang tercatat di metadata."""
    input_dir = utils.resolve_path(input_dir)
    metadata = load_metadata(input_dir)
    if metadata.get("filename"):
        candidate = os.path.join(input_dir, metadata["filename"])
        if os.path.exists(candidate):
            return candidate
    return utils.find_video_in_dir(input_dir)
