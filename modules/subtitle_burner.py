"""Burn subtitle ke video dengan 4 style siap pakai.

Berasal dari short/clip_shorts.sh (konversi SRT→ASS + style HYPE/KARAOKE/
PODCAST/CLEAN). Menyediakan builder fragmen filter agar bisa digabung dalam
satu pass encode bersama reframe & color grade.
"""
import math
import os
import re
from typing import Dict, List, Optional, Tuple

from . import utils

# Batas pemecahan segmen panjang agar subtitle terasa dinamis (gaya Shorts).
_MAX_WORDS_PER_LINE = 7
_MAX_SEC_PER_LINE = 2.5

# Parameter style ASS. Warna ASS format &HAABBGGRR.
STYLES: Dict[str, Dict] = {
    "HYPE": {  # teks BESAR kuning, shadow dramatis — gaya viral
        "fontsize": 84, "primary": "&H0000FFFF", "outline_col": "&H00000000",
        "back": "&H99000000", "bold": 1, "outline": 4, "shadow": 8, "margin_v": 160,
        "tag": r"{\fad(150,100)\blur1}", "upper": True,
    },
    "KARAOKE": {  # putih besar, outline emas
        "fontsize": 72, "primary": "&H00FFFFFF", "outline_col": "&H00FFD700",
        "back": "&H80000000", "bold": 1, "outline": 3, "shadow": 5, "margin_v": 180,
        "tag": r"{\fad(200,150)\blur0.5}", "upper": False,
    },
    "PODCAST": {  # modern, semi-transparan
        "fontsize": 58, "primary": "&H00FFFFFF", "outline_col": "&H00222222",
        "back": "&HAA000000", "bold": 0, "outline": 4, "shadow": 3, "margin_v": 200,
        "tag": r"{\fad(100,80)\blur1.5\be1}", "upper": False,
    },
    "CLEAN": {  # minimalis putih bersih
        "fontsize": 62, "primary": "&H00FFFFFF", "outline_col": "&H00333333",
        "back": "&H66000000", "bold": 0, "outline": 2, "shadow": 2, "margin_v": 200,
        "tag": r"{\fad(80,60)}", "upper": False,
    },
}

DEFAULT_STYLE = "CLEAN"
FONT_NAME = "DejaVu Sans"  # nama family; libass fallback via fontconfig bila tidak ada


def _ass_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int((seconds - int(seconds)) * 100)
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"


def _srt_time_to_sec(t: str) -> float:
    t = t.replace(",", ".").strip()
    h, m, rest = t.split(":")
    s, ms = (rest.split(".") + ["0"])[:2]
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms[:3].ljust(3, "0")) / 1000.0


def _ass_header(style_params: Dict) -> str:
    width, height = utils.load_config()["video"]["width"], utils.load_config()["video"]["height"]
    return (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {width}\nPlayResY: {height}\n"
        "ScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{FONT_NAME},{style_params['fontsize']},{style_params['primary']},"
        f"&H000000FF,{style_params['outline_col']},{style_params['back']},{style_params['bold']},"
        f"0,0,0,100,100,1,0,1,{style_params['outline']},{style_params['shadow']},2,80,80,"
        f"{style_params['margin_v']},1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )


def _resolve_style(style: Optional[str]) -> Dict:
    return STYLES.get((style or DEFAULT_STYLE).upper(), STYLES[DEFAULT_STYLE])


def _escape_ass_text(text: str) -> str:
    """Escape karakter yang bermakna khusus di libass agar teks user tidak
    merusak/menghilang. `{` `}` membuka-tutup override tag; `\\` adalah escape."""
    return (
        text.replace("\\", r"\\")
        .replace("{", r"\{")
        .replace("}", r"\}")
        .replace("\n", r"\N")
    )


def _dialogue(start: float, end: float, text: str, params: Dict) -> str:
    body = text.upper() if params["upper"] else text
    body = _escape_ass_text(body)
    return f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Default,,0,0,0,,{params['tag']}{body}\n"


def _split_segment(start: float, end: float, text: str) -> List[Tuple[float, float, str]]:
    """Pecah segmen panjang menjadi potongan ~_MAX_WORDS_PER_LINE kata /
    ~_MAX_SEC_PER_LINE detik. Waktu dibagi proporsional (linier) per potongan."""
    words = text.split()
    span = end - start
    if len(words) <= _MAX_WORDS_PER_LINE and span <= _MAX_SEC_PER_LINE:
        return [(start, end, text)]

    by_words = math.ceil(len(words) / _MAX_WORDS_PER_LINE) if words else 1
    by_time = math.ceil(span / _MAX_SEC_PER_LINE) if span > 0 else 1
    n = max(1, by_words, by_time)
    per = max(1, math.ceil(len(words) / n))
    step = span / n if n else span

    pieces: List[Tuple[float, float, str]] = []
    t = start
    for i in range(0, len(words), per):
        chunk = " ".join(words[i:i + per]).strip()
        ps, pe = t, min(end, t + step)
        if chunk and pe > ps:
            pieces.append((ps, pe, chunk))
        t = pe
    return pieces or [(start, end, text)]


def srt_to_ass(srt_path: str, ass_path: str, style: Optional[str] = None) -> Optional[str]:
    """Konversi seluruh file SRT menjadi ASS bergaya (untuk mode single)."""
    srt_path = utils.resolve_path(srt_path)
    if not os.path.exists(srt_path):
        return None
    params = _resolve_style(style)
    utils.ensure_parent_dir(ass_path)
    with open(srt_path, "r", encoding="utf-8", errors="replace") as fh:
        content = fh.read()

    events = []
    for block in re.split(r"\n\s*\n", content.strip()):
        lines = [ln for ln in block.strip().split("\n") if ln.strip()]
        time_line = next((ln for ln in lines if "-->" in ln), None)
        if not time_line:
            continue
        text_lines = [ln.strip() for ln in lines if "-->" not in ln and not ln.strip().isdigit()]
        if not text_lines:
            continue
        a, b = time_line.split("-->")
        events.append(_dialogue(_srt_time_to_sec(a), _srt_time_to_sec(b.split()[0]),
                                " ".join(text_lines), params))

    if not events:
        return None
    with open(ass_path, "w", encoding="utf-8") as fh:
        fh.write(_ass_header(params))
        fh.writelines(events)
    return ass_path


def make_clip_ass(transcript: str, clip_duration: float, ass_path: str, style: Optional[str] = None) -> Optional[str]:
    """Buat ASS satu dialog (transkrip klip tampil sepanjang klip) untuk mode clipper."""
    transcript = (transcript or "").strip()
    if not transcript:
        return None
    params = _resolve_style(style)
    utils.ensure_parent_dir(ass_path)
    with open(ass_path, "w", encoding="utf-8") as fh:
        fh.write(_ass_header(params))
        fh.write(_dialogue(0.0, max(0.1, clip_duration), transcript, params))
    return ass_path


def make_clip_ass_timed(
    segments_window,
    clip_start: float,
    clip_duration: float,
    ass_path: str,
    style: Optional[str] = None,
    split_long: bool = True,
) -> Optional[str]:
    """ASS dinamis untuk mode clipper: satu Dialogue per segmen Whisper.

    `segments_window` = objek dengan atribut .start/.end/.text (waktu absolut
    video). Waktu digeser relatif ke awal klip lalu di-clamp ke [0, durasi klip].
    Segmen kosong / di luar jendela diabaikan. Mengembalikan None bila tak ada
    event valid (pemanggil bisa fallback ke make_clip_ass).
    """
    params = _resolve_style(style)
    utils.ensure_parent_dir(ass_path)

    events: List[str] = []
    for seg in segments_window:
        text = (getattr(seg, "text", "") or "").strip()
        if not text:
            continue
        s = max(0.0, float(getattr(seg, "start", 0.0)) - clip_start)
        e = min(float(clip_duration), float(getattr(seg, "end", 0.0)) - clip_start)
        if e <= s:
            continue
        pieces = _split_segment(s, e, text) if split_long else [(s, e, text)]
        for ps, pe, ptext in pieces:
            events.append(_dialogue(ps, pe, ptext, params))

    if not events:
        return None
    with open(ass_path, "w", encoding="utf-8") as fh:
        fh.write(_ass_header(params))
        fh.writelines(events)
    return ass_path


def _escape_filter_path(path: str) -> str:
    # Escape untuk path di dalam filtergraph FFmpeg (ass=...).
    return path.replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


def build_filter(ass_path: str) -> str:
    """Fragmen filter untuk membakar ASS ke video."""
    if not ass_path or not os.path.exists(ass_path):
        return ""
    return f",ass='{_escape_filter_path(ass_path)}'"
