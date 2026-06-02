"""Cari & download musik background royalty-free berdasarkan topik.

Berasal dari short/music_finder.sh. Memakai yt-dlp untuk mengunduh audio
dari YouTube Audio Library. Hasil di-cache ke folder music_lib/.
"""
import os
import shutil
from typing import Dict, List, Optional

from . import utils

# Database topik → daftar (url, nama_file, deskripsi). Sumber: YouTube Audio Library.
MUSIC_DB: Dict[str, List[Dict[str, str]]] = {
    "tech": [
        {"url": "https://www.youtube.com/watch?v=xNN7iTA57jM", "file": "tech_future_bass.mp3", "desc": "Future Bass - Electronic upbeat"},
        {"url": "https://www.youtube.com/watch?v=4xDzrJKXOOY", "file": "tech_synthetic.mp3", "desc": "Synthetic - Electronic minimal"},
    ],
    "motivation": [
        {"url": "https://www.youtube.com/watch?v=mPVBUPIBfZk", "file": "motivation_epic.mp3", "desc": "Epic Motivational - Cinematic"},
        {"url": "https://www.youtube.com/watch?v=y61zDg4IhEI", "file": "motivation_hype.mp3", "desc": "Hype Energy - Uplifting"},
    ],
    "gaming": [
        {"url": "https://www.youtube.com/watch?v=TlWYgGyNjJo", "file": "gaming_intense.mp3", "desc": "Intense Gaming - Electronic Rock"},
        {"url": "https://www.youtube.com/watch?v=Yr4N0M0S5xE", "file": "gaming_epic.mp3", "desc": "Epic Battle - Orchestral"},
    ],
    "vlog": [
        {"url": "https://www.youtube.com/watch?v=RqFZ-oG9bLU", "file": "vlog_chill.mp3", "desc": "Chill Lo-Fi - Relaxed"},
        {"url": "https://www.youtube.com/watch?v=5qap5aO4i9A", "file": "vlog_lofi.mp3", "desc": "Lo-Fi Hip Hop - Casual"},
    ],
    "educational": [
        {"url": "https://www.youtube.com/watch?v=jfKfPfyJRdk", "file": "edu_focus.mp3", "desc": "Focus Flow - Productive"},
        {"url": "https://www.youtube.com/watch?v=lTRiuFIWV54", "file": "edu_ambient.mp3", "desc": "Ambient Focus - Concentration"},
    ],
    "drama": [
        {"url": "https://www.youtube.com/watch?v=pkNTNnxuK6Q", "file": "drama_cinematic.mp3", "desc": "Cinematic Drama - Emotional"},
        {"url": "https://www.youtube.com/watch?v=UBpzR6q3CxI", "file": "drama_tension.mp3", "desc": "Building Tension - Suspense"},
    ],
    "funny": [
        {"url": "https://www.youtube.com/watch?v=EBkGHG1PDac", "file": "funny_quirky.mp3", "desc": "Quirky Fun - Comedy"},
        {"url": "https://www.youtube.com/watch?v=0pvWFuFdIe8", "file": "funny_upbeat.mp3", "desc": "Upbeat Happy - Cheerful"},
    ],
    "chill": [
        {"url": "https://www.youtube.com/watch?v=7NOSDKb0HlU", "file": "chill_lofi.mp3", "desc": "Dark Lo-Fi - Deep"},
        {"url": "https://www.youtube.com/watch?v=5yx6BWlEVcY", "file": "chill_ambient.mp3", "desc": "Ambient Chill - Relaxing"},
    ],
}

TOPICS = sorted(MUSIC_DB.keys())


def find_music_for_topic(topic: str, output_dir: str = "music_lib") -> Optional[str]:
    """Download (atau pakai cache) musik untuk topik. Kembalikan path file pertama."""
    topic_lower = (topic or "").strip().lower()
    if topic_lower not in MUSIC_DB:
        print(f"[ERROR] Topik '{topic}' tidak dikenali. Pilihan: {', '.join(TOPICS)}")
        return None

    if shutil.which("yt-dlp") is None:
        try:
            import yt_dlp  # noqa: F401
        except Exception:
            print("[ERROR] yt-dlp tidak terpasang. Install: pip install yt-dlp")
            print("[i] Alternatif manual: https://www.youtube.com/audiolibrary , https://pixabay.com/music/")
            return None

    output_dir = utils.ensure_dir(utils.resolve_path(output_dir))
    first_music: Optional[str] = None

    try:
        from yt_dlp import YoutubeDL
    except Exception:
        print("[ERROR] Modul yt-dlp tidak dapat diimpor.")
        return None

    for entry in MUSIC_DB[topic_lower]:
        target = os.path.join(output_dir, entry["file"])
        if os.path.exists(target):
            print(f"[✓] Sudah ada: {entry['file']} ({entry['desc']})")
            first_music = first_music or target
            continue

        print(f"[↓] Download: {entry['desc']}")
        out_tmpl = os.path.join(output_dir, "%(id)s.%(ext)s")
        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": out_tmpl,
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "postprocessors": [
                {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}
            ],
        }
        try:
            with YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(entry["url"], download=True)
            produced = os.path.join(output_dir, f"{info.get('id')}.mp3")
            if os.path.exists(produced):
                os.replace(produced, target)
            if os.path.exists(target):
                print("    ✓ Berhasil")
                first_music = first_music or target
        except Exception as exc:
            print(f"    ✗ Gagal download: {exc}")

    if first_music:
        print(f"[✓] Music library untuk '{topic_lower}' siap di: {output_dir}")
    return first_music
