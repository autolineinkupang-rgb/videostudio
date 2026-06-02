"""Transkripsi audio video dengan openai-whisper atau faster-whisper.

Berasal dari clipper/detect_moments.py (fungsi transcribe_whisper) + logika
penulisan SRT dari short/auto_subtitle.sh. Model di-unload dari RAM setelah selesai.
"""
import gc
import os
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

from . import utils


@dataclass
class Segment:
    start: float
    end: float
    text: str


def _format_srt_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds - int(seconds)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _srt_time_to_sec(t: str) -> float:
    """Konversi 'HH:MM:SS,mmm' (atau '.mmm') ke detik."""
    t = t.replace(",", ".").strip()
    h, m, rest = t.split(":")
    s, _, ms = rest.partition(".")
    ms = (ms + "000")[:3] if ms else "0"
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def parse_srt(srt_path: str) -> List[Segment]:
    """Parse file SRT (timestamp absolut) menjadi daftar Segment.

    Dipakai untuk subtitle yang disediakan user di folder subtitle/ — sebagai
    pengganti transkripsi Whisper (lebih cepat + teks bisa dikoreksi manual).
    """
    srt_path = utils.resolve_path(srt_path)
    if not os.path.exists(srt_path):
        raise RuntimeError(f"File subtitle tidak ditemukan: {srt_path}")
    with open(srt_path, "r", encoding="utf-8", errors="replace") as fh:
        content = fh.read()

    segments: List[Segment] = []
    for block in re.split(r"\n\s*\n", content.strip()):
        lines = [ln for ln in block.strip().splitlines() if ln.strip()]
        time_line = next((ln for ln in lines if "-->" in ln), None)
        if not time_line:
            continue
        text_lines = [ln.strip() for ln in lines if "-->" not in ln and not ln.strip().isdigit()]
        text = " ".join(text_lines).strip()
        if not text:
            continue
        a, b = time_line.split("-->")
        try:
            start = _srt_time_to_sec(a)
            end = _srt_time_to_sec(b.split()[0])
        except Exception:
            continue
        if end < start:
            end = start
        segments.append(Segment(start=start, end=end, text=text))
    return segments


def write_srt(segments: List[Segment], srt_path: str) -> str:
    """Tulis segmen ke file SRT (waktu absolut terhadap video sumber)."""
    utils.ensure_parent_dir(srt_path)
    with open(srt_path, "w", encoding="utf-8") as fh:
        for i, seg in enumerate(segments, start=1):
            fh.write(f"{i}\n")
            fh.write(f"{_format_srt_time(seg.start)} --> {_format_srt_time(seg.end)}\n")
            fh.write(seg.text.strip() + "\n\n")
    return srt_path


def transcribe(
    video_path: str,
    model: str = "base",
    engine: str = "whisper",
    lang: str = "id",
    srt_out: Optional[str] = None,
) -> Tuple[List[Segment], str, Optional[str]]:
    """Transkripsi video → (segments, transcript_text, srt_path).

    engine: "whisper" (openai-whisper) atau "faster" (faster-whisper).
    Otomatis fallback ke openai-whisper jika faster-whisper gagal.
    """
    video_path = utils.resolve_path(video_path)
    if not os.path.exists(video_path):
        raise RuntimeError(f"File video tidak ditemukan: {video_path}")

    segments_raw = []
    transcript_text = ""
    model_obj = None
    language = None if lang == "auto" else lang

    if engine == "faster":
        try:
            from faster_whisper import WhisperModel

            print(f"[INFO] Transkripsi dengan faster-whisper (model={model}) di CPU...")
            model_obj = WhisperModel(model, device="cpu", compute_type="int8")
            segments_gen, _info = model_obj.transcribe(video_path, language=language, task="transcribe")
            segments_raw = [{"start": s.start, "end": s.end, "text": s.text} for s in segments_gen]
            transcript_text = " ".join(s["text"] for s in segments_raw).strip()
        except Exception as exc:
            print(f"[WARNING] faster-whisper gagal ({exc}); fallback ke openai-whisper.")
            engine = "whisper"
            if model_obj is not None:
                del model_obj
                gc.collect()
                model_obj = None

    if engine == "whisper":
        try:
            import whisper

            print(f"[INFO] Transkripsi dengan openai-whisper (model={model}) di CPU...")
            model_obj = whisper.load_model(model)
            res = model_obj.transcribe(video_path, language=language, fp16=False)
            transcript_text = (res.get("text") or "").strip()
            segments_raw = res.get("segments", [])
        except Exception as exc:
            raise RuntimeError(f"Gagal menjalankan openai-whisper: {exc}")

    # Bebaskan memori model Whisper secara eksplisit (penting untuk RAM 8GB).
    if model_obj is not None:
        try:
            del model_obj
            gc.collect()
        except Exception:
            pass

    # Normalisasi ke struktur Segment sederhana.
    segments: List[Segment] = []
    for s in segments_raw:
        if not s:
            continue
        start = float(s.get("start", 0.0))
        end = float(s.get("end", start + 1.0))
        text = (s.get("text") or "").strip()
        if text:
            segments.append(Segment(start=start, end=end, text=text))

    srt_path = None
    if srt_out and segments:
        srt_path = write_srt(segments, utils.resolve_path(srt_out))
        print(f"[INFO] Subtitle SRT disimpan: {srt_path}")

    return segments, transcript_text, srt_path
