"""Mixing background music ke video.

Berasal dari compile/compile.py & shortmaker.sh. Menggunakan -c:v copy agar
pencampuran BGM murah (tidak re-encode video). Musik di-loop & di-fade.
"""
import os
from typing import Optional

from . import utils

_CFG = utils.load_config()
A_CODEC = _CFG["audio"]["codec"]
A_BITRATE = _CFG["audio"]["bitrate"]
A_RATE = _CFG["audio"]["sample_rate"]
A_CHANNELS = _CFG["audio"]["channels"]
THREADS = _CFG["encode"]["threads"]

AUDIO_EXTS = (".mp3", ".wav", ".m4a", ".aac", ".ogg")


def find_music(sound_dir: str = "sound") -> Optional[str]:
    """Ambil file audio pertama dari folder sound/ bila ada."""
    sound_dir = utils.resolve_path(sound_dir)
    if not os.path.isdir(sound_dir):
        return None
    files = sorted(f for f in os.listdir(sound_dir) if f.lower().endswith(AUDIO_EXTS))
    return os.path.join(sound_dir, files[0]) if files else None


def mix_music(
    video_path: str,
    music_path: str,
    output: str,
    volume: float = 0.20,
    copy_video: bool = True,
) -> str:
    """Mix BGM ke video. Musik di-loop tak terbatas, durasi ikut video (duration=first).

    copy_video=True → stream video disalin (cepat, hemat, tanpa kehilangan kualitas).
    """
    video_path = utils.resolve_path(video_path)
    music_path = utils.resolve_path(music_path)
    output = utils.resolve_path(output)
    utils.ensure_parent_dir(output)

    if not os.path.exists(video_path):
        raise RuntimeError(f"Video tidak ditemukan: {video_path}")
    if not os.path.exists(music_path):
        raise RuntimeError(f"Musik tidak ditemukan: {music_path}")

    volume = max(0.0, min(1.0, float(volume)))
    # [0:a] audio asli ; [1:a] musik loop + volume rendah ; amix duration=first.
    filter_complex = (
        f"[1:a]aloop=loop=-1:size=2147483647,volume={volume}[bgm];"
        f"[0:a][bgm]amix=inputs=2:duration=first:dropout_transition=2[aout]"
    )
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", video_path, "-i", music_path,
        "-filter_complex", filter_complex,
        "-map", "0:v", "-map", "[aout]",
    ]
    cmd += ["-c:v", "copy"] if copy_video else [
        "-c:v", "libx264", "-crf", str(_CFG["video"]["crf"]), "-preset", _CFG["video"]["preset"],
    ]
    cmd += ["-c:a", A_CODEC, "-b:a", str(A_BITRATE), "-ar", str(A_RATE), "-ac", str(A_CHANNELS),
            "-shortest", "-threads", str(THREADS), "-movflags", "+faststart", output]

    ok, msg = utils.run_cmd(cmd)
    if not ok and copy_video:
        # Beberapa kontainer/codec gagal saat copy — coba ulang dengan re-encode video.
        print("[WARNING] Mix dengan -c:v copy gagal, mencoba ulang dengan re-encode video...")
        return mix_music(video_path, music_path, output, volume, copy_video=False)
    if not ok:
        raise RuntimeError(msg)
    return output
