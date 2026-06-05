"""Transisi antar klip menggunakan FFmpeg xfade filter.

Digunakan di mode compile saat flag --transition diberikan.
concat_with_transitions() menggantikan encoder.concat_segments() bila
user meminta transisi, sambil menjaga backward-compatibility penuh.
"""
import json
import os
import shutil
import subprocess
from typing import List, Tuple

from . import utils

_CFG = utils.load_config()
_FPS = _CFG["video"]["fps"]
_CRF = _CFG["video"]["crf"]
_PRESET = _CFG["video"]["preset"]
_PROFILE = _CFG["video"]["profile"]
_LEVEL = str(_CFG["video"]["level"])
_A_CODEC = _CFG["audio"]["codec"]
_A_BITRATE = _CFG["audio"]["bitrate"]
_A_RATE = _CFG["audio"]["sample_rate"]
_A_CHANNELS = _CFG["audio"]["channels"]
_THREADS = _CFG["encode"]["threads"]

VALID_TRANSITIONS = frozenset({
    "fade", "fadewhite", "slideleft", "slideright",
    "slideup", "slidedown", "wipeleft", "dissolve",
    "zoom", "pixelize", "squeezeh",
})


def get_clip_duration(path: str) -> float:
    """Baca durasi klip dengan ffprobe."""
    cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_entries", "format=duration", path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    data = json.loads(result.stdout)
    return float(data["format"]["duration"])


def _build_xfade_filtergraph(
    durations: List[float],
    transitions_list: List[str],
    td: float,
) -> Tuple[str, str, str]:
    """Bangun filtergraph xfade berantai (pure function, tanpa FFmpeg call).

    Mengembalikan (filtergraph_string, map_video_label, map_audio_label).
    """
    n = len(durations)
    vf_parts: List[str] = []
    af_parts: List[str] = []

    cumulative = 0.0
    for i in range(n - 1):
        transition = transitions_list[i % len(transitions_list)]
        cumulative += durations[i]
        offset = max(0.0, cumulative - (i + 1) * td)

        in_v = f"[v{i:03d}]" if i > 0 else "[0:v]"
        in_a = f"[a{i:03d}]" if i > 0 else "[0:a]"
        next_v = f"[{i + 1}:v]"
        next_a = f"[{i + 1}:a]"
        out_v = "[vout]" if i == n - 2 else f"[v{i + 1:03d}]"
        out_a = "[aout]" if i == n - 2 else f"[a{i + 1:03d}]"

        vf_parts.append(
            f"{in_v}{next_v}xfade=transition={transition}"
            f":duration={td:.3f}:offset={offset:.3f}{out_v}"
        )
        af_parts.append(
            f"{in_a}{next_a}acrossfade=d={td:.3f}{out_a}"
        )

    filtergraph = ";".join(vf_parts + af_parts)
    return filtergraph, "[vout]", "[aout]"


def concat_with_transitions(
    clips: List[str],
    out_path: str,
    transitions: List[str],
    td: float = 0.4,
) -> str:
    """Gabung clips dengan xfade berantai.

    - clips kosong → ValueError
    - 1 klip → copy langsung ke out_path
    - ≥ 2 klip → xfade filtergraph dengan transisi dipilih secara cycle
    """
    if not clips:
        raise ValueError("clips tidak boleh kosong")

    for t in transitions:
        if t not in VALID_TRANSITIONS:
            raise ValueError(
                f"Transisi tidak dikenal: {t!r}. Pilih dari: {sorted(VALID_TRANSITIONS)}"
            )

    if len(clips) == 1:
        utils.ensure_parent_dir(out_path)
        shutil.copy(clips[0], out_path)
        return out_path

    durations = [get_clip_duration(c) for c in clips]

    # Clamp td agar tidak melebihi durasi klip terpendek / 3.
    min_dur = min(durations)
    safe_td = min(td, min_dur / 3.0)
    if safe_td < td:
        print(
            f"[WARNING] --transition duration dikurangi {td}s → {safe_td:.2f}s "
            f"(klip terpendek {min_dur:.1f}s)."
        )
    td = safe_td

    filtergraph, map_v, map_a = _build_xfade_filtergraph(durations, transitions, td)

    input_args: List[str] = []
    for c in clips:
        input_args += ["-i", c]

    cmd = [
        "ffmpeg", "-hide_banner", "-y", "-loglevel", "error",
        *input_args,
        "-filter_complex", filtergraph,
        "-map", map_v, "-map", map_a,
        "-c:v", "libx264", "-crf", str(_CRF),
        "-preset", _PRESET, "-profile:v", _PROFILE, "-level:v", _LEVEL,
        "-r", str(_FPS), "-pix_fmt", "yuv420p",
        "-c:a", _A_CODEC, "-b:a", _A_BITRATE,
        "-ar", str(_A_RATE), "-ac", str(_A_CHANNELS),
        "-threads", str(_THREADS),
        out_path,
    ]

    utils.ensure_parent_dir(out_path)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg xfade gagal:\n{result.stderr[-2000:]}")

    return out_path
