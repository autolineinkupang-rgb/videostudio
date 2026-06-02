"""Pemilihan momen terbaik berbasis LLM untuk mode clipper.

Mengirim transkrip bertimestamp ke LLM dan meminta daftar cuplikan paling
menarik/viral dalam format JSON, lalu mengonversinya ke struktur timestamps
yang dipakai encoder.cut_clips. Mengembalikan [] bila gagal/tak ada key —
pemanggil fallback ke deteksi momen heuristik (moment_detector).
"""
import json
import re
from typing import Any, Dict, List

from . import ai_client, utils

_SYSTEM = (
    "Kamu editor video Shorts/Reels berpengalaman. Kamu memilih cuplikan paling "
    "menarik, padat, dan berpotensi viral dari transkrip bertimestamp. Pilih bagian "
    "yang punya hook kuat, insight, emosi, atau klimaks. Jawab HANYA dengan JSON valid."
)


def _build_prompt(segments, duration, max_clips, min_sec, target_sec, max_sec) -> str:
    lines = [f"[{float(s.start):.1f}-{float(s.end):.1f}] {s.text}" for s in segments]
    transcript = "\n".join(lines)
    n = max_clips or 6
    return (
        f"Durasi video: {duration:.0f} detik.\n"
        f"Pilih maksimal {n} cuplikan terbaik untuk dijadikan Shorts/Reels vertikal.\n"
        f"Aturan durasi tiap cuplikan: antara {min_sec:.0f}-{max_sec:.0f} detik "
        f"(idealnya sekitar {target_sec:.0f} detik). Gunakan batas waktu dari transkrip.\n\n"
        "Balas HANYA JSON array (tanpa teks lain), tiap elemen:\n"
        '{"start": <detik angka>, "end": <detik angka>, "reason": "<alasan singkat>", '
        '"score": <1-10>}\n\n'
        f"Transkrip (format [mulai-akhir] teks):\n{transcript}"
    )


def _extract_json(text: str) -> List[Dict[str, Any]]:
    """Ambil array JSON dari balasan LLM (kadang dibungkus ```json ... ```)."""
    if not text:
        return []
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if not match:
        return []
    try:
        data = json.loads(match.group(0))
    except Exception:
        return []
    return data if isinstance(data, list) else []


def select_moments(segments, duration, max_clips=None, provider="gemini") -> List[Dict[str, Any]]:
    """Pilih momen via LLM. Kembalikan list dict timestamps (kompatibel cut_clips),
    atau [] bila gagal/tak ada key (pemanggil fallback ke heuristik)."""
    if not segments:
        return []
    duration = float(duration or 0.0)

    cfg = utils.load_config()["clip"]
    min_sec, target_sec, max_sec = float(cfg["min_sec"]), float(cfg["target_sec"]), float(cfg["max_sec"])

    prompt = _build_prompt(segments, duration, max_clips, min_sec, target_sec, max_sec)
    raw = ai_client.complete(prompt, provider=provider, system=_SYSTEM, temperature=0.4)
    items = _extract_json(raw or "")
    if not items:
        return []

    moments: List[Dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            start = max(0.0, float(item["start"]))
            end = float(item["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if duration:
            end = min(end, duration)
        if end <= start:
            continue
        # Perpanjang klip terlalu pendek hingga ~target (dibatasi durasi video).
        if end - start < min_sec:
            end = min(start + target_sec, duration or (start + target_sec))
        # Batasi klip terlalu panjang.
        if end - start > max_sec:
            end = start + max_sec
        if end <= start:
            continue

        text = " ".join(
            s.text for s in segments if float(s.end) > start and float(s.start) < end
        ).strip()
        reason = str(item.get("reason", "")).strip()
        try:
            score = float(item.get("score", 5))
        except (TypeError, ValueError):
            score = 5.0

        moments.append({
            "start": utils.format_hhmmss(start),
            "end": utils.format_hhmmss(end),
            "start_sec": round(start, 3),
            "end_sec": round(end, 3),
            "score": round(score, 2),
            "reason": ("AI: " + reason) if reason else "AI",
            "transcript": text,
        })

    moments.sort(key=lambda m: m["score"], reverse=True)
    if max_clips:
        moments = moments[:max_clips]
    return moments
