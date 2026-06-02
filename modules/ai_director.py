"""Pemilihan momen terbaik berbasis LLM untuk mode clipper.

Mengirim transkrip bertimestamp ke LLM dan meminta daftar cuplikan paling
menarik/viral dalam format JSON, lalu mengonversinya ke struktur timestamps
yang dipakai encoder.cut_clips. Mengembalikan [] bila gagal/tak ada key —
pemanggil fallback ke deteksi momen heuristik (moment_detector).
"""
import json
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from . import ai_client, utils
from .transcriber import Segment

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


# ── AI clean: buang filler/jeda/ngelantur (mode single) ───────────────────────

_CLEAN_SYSTEM = (
    "Kamu editor yang merapikan rekaman bicara. Dari transkrip bertimestamp bernomor, "
    "tentukan segmen mana yang sebaiknya DIBUANG: kata/kalimat pengisi ('emm','anu','eee'), "
    "pengulangan, basa-basi, bagian ngelantur/melenceng. Pertahankan semua isi substantif. "
    "Jawab HANYA JSON valid."
)


def _build_clean_prompt(segments) -> str:
    lines = [f"[{i}] ({float(s.start):.1f}-{float(s.end):.1f}) {s.text}" for i, s in enumerate(segments)]
    return (
        "Berikut transkrip bernomor. Kembalikan HANYA JSON (tanpa teks lain) berisi indeks "
        "segmen yang harus DIBUANG (filler/pengulangan/ngelantur). Jangan buang isi penting.\n"
        'Format: {"remove": [<indeks angka>, ...]}\n\n'
        f"Transkrip:\n" + "\n".join(lines)
    )


def _extract_remove_indices(text: str, n: int) -> Optional[Set[int]]:
    """Ambil indeks-buang dari balasan LLM: objek {\"remove\":[...]} atau array [...]."""
    if not text:
        return None
    idxs = None
    obj_match = re.search(r"\{.*\}", text, re.DOTALL)
    if obj_match:
        try:
            obj = json.loads(obj_match.group(0))
            if isinstance(obj, dict) and isinstance(obj.get("remove"), list):
                idxs = obj["remove"]
        except Exception:
            idxs = None
    if idxs is None:
        arr_match = re.search(r"\[.*\]", text, re.DOTALL)
        if arr_match:
            try:
                arr = json.loads(arr_match.group(0))
                if isinstance(arr, list):
                    idxs = arr
            except Exception:
                idxs = None
    if idxs is None:
        return None
    result: Set[int] = set()
    for x in idxs:
        try:
            i = int(x)
        except (TypeError, ValueError):
            continue
        if 0 <= i < n:
            result.add(i)
    return result


def select_cuts(segments, provider: str = "gemini", max_remove_ratio: float = 0.7) -> Optional[Set[int]]:
    """LLM menandai indeks segmen yang dibuang (filler/jeda/ngelantur).

    None bila tak ada key / gagal / parse gagal / pembuangan berlebihan
    (>max_remove_ratio) — pemanggil melewati pembersihan.
    """
    if not segments:
        return None
    raw = ai_client.complete(
        _build_clean_prompt(segments), provider=provider, system=_CLEAN_SYSTEM, temperature=0.2
    )
    if not raw:
        return None
    remove = _extract_remove_indices(raw, len(segments))
    if not remove:
        return None
    if len(remove) > max_remove_ratio * len(segments):
        print(f"[WARNING] AI clean ingin membuang {len(remove)}/{len(segments)} segmen "
              "(terlalu banyak) — pembersihan dibatalkan.")
        return None
    return remove


def plan_clean(segments, remove_idx: Optional[Set[int]], max_gap: float = 0.6
               ) -> Tuple[List[Tuple[float, float]], List[Segment]]:
    """Bangun keep-ranges (waktu sumber) + segmen ter-remap ke timeline bersih.

    Segmen tersisa yang berurutan digabung jadi satu range; dipecah bila ada
    segmen dibuang ATAU jeda antar-segmen > max_gap (dead-air ikut terbuang).
    Fungsi murni (tanpa API) agar mudah diuji.
    """
    remove_idx = remove_idx or set()
    kept = [(i, s) for i, s in enumerate(segments) if i not in remove_idx]
    if not kept:
        return [], []

    ranges: List[Tuple[float, float]] = []
    members: List[List[Segment]] = []
    cur_start = cur_end = None
    cur_members: List[Segment] = []
    prev_i = None
    for i, s in kept:
        st, en = float(s.start), float(s.end)
        if cur_start is None:
            cur_start, cur_end, cur_members = st, en, [s]
        elif prev_i is not None and i == prev_i + 1 and (st - cur_end) <= max_gap:
            cur_end = en
            cur_members.append(s)
        else:
            ranges.append((cur_start, cur_end))
            members.append(cur_members)
            cur_start, cur_end, cur_members = st, en, [s]
        prev_i = i
    ranges.append((cur_start, cur_end))
    members.append(cur_members)

    remapped: List[Segment] = []
    offset = 0.0
    for (rs, re_), group in zip(ranges, members):
        for s in group:
            remapped.append(Segment(start=offset + (float(s.start) - rs),
                                     end=offset + (float(s.end) - rs), text=s.text))
        offset += (re_ - rs)
    return ranges, remapped
