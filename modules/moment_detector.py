"""Deteksi momen menarik dari video.

Berasal dari clipper/detect_moments.py. Menggabungkan sinyal:
trigger words, spike audio (RMS), efek suara heuristik, gerak/cut visual,
dan scene change. Transkripsi disuplai dari modul transcriber (segments).

Output: list dict timestamps (start/end HH:MM:SS + detik, score, reason, transcript).
"""
import json
import math
import re
import subprocess
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from . import utils
from .transcriber import Segment

_CFG = utils.load_config()
FFMPEG_THREADS = _CFG["encode"]["threads"]

# Batas durasi klip — dikalibrasi dari contoh Shorts nyata (lihat config.yaml: clip).
MIN_CLIP = float(_CFG["clip"]["min_sec"])
TARGET_CLIP = float(_CFG["clip"]["target_sec"])
MAX_CLIP = float(_CFG["clip"]["max_sec"])

TRIGGER_WORDS = [
    "tapi", "jadi", "bayangkan", "faktanya", "ternyata", "rahasia", "penting",
]


@dataclass
class Clip:
    start: float
    end: float
    score: float
    reason: str
    transcript: str


@dataclass
class SignalEvent:
    time: float
    score: float
    label: str


# ── Deteksi sinyal mentah dari video ─────────────────────────────────────────

def detect_scene_changes(video_path: str) -> List[float]:
    """Titik scene change via filter select=gt(scene,0.4)."""
    cmd = [
        "ffmpeg", "-hide_banner", "-threads", str(FFMPEG_THREADS),
        "-i", video_path, "-filter:v", "select=gt(scene\\,0.4),metadata=print",
        "-f", "null", "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    times: List[float] = []
    for line in ((proc.stdout or "") + "\n" + (proc.stderr or "")).splitlines():
        m = re.search(r"pts_time:(\d+\.?\d*)", line)
        if m:
            times.append(float(m.group(1)))
    return sorted(set(times))


def detect_audio_spikes(video_path: str, window_s: float = 0.5) -> List[float]:
    """Titik di mana RMS audio melonjak di atas threshold (mean + 0.8*std)."""
    import numpy as np

    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-threads", str(FFMPEG_THREADS),
        "-i", video_path, "-vn", "-ac", "1", "-ar", "16000", "-f", "f32le", "pipe:1",
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    if proc.stdout is None:
        return []

    sample_rate = 16000
    window_size = int(window_s * sample_rate)
    rms_list: List[float] = []
    timestamps: List[float] = []
    idx = 0
    try:
        while True:
            data = proc.stdout.read(window_size * 4)
            if not data:
                break
            if len(data) < window_size * 4:
                data += b"\x00" * (window_size * 4 - len(data))
            arr = np.frombuffer(data, dtype=np.float32)
            rms = float(math.sqrt(float((arr * arr).mean()))) if arr.size else 0.0
            rms_list.append(rms)
            timestamps.append(idx * window_s)
            idx += 1
    finally:
        proc.wait()

    if not rms_list:
        return []

    mean = sum(rms_list) / len(rms_list)
    std = math.sqrt(sum((x - mean) ** 2 for x in rms_list) / len(rms_list))
    threshold = mean + max(0.8 * std, 0.05)
    spikes = [timestamps[i] for i, v in enumerate(rms_list) if v >= threshold]

    merged: List[float] = []
    for t in spikes:
        if not merged or t - merged[-1] > 2.5:
            merged.append(t)
    return merged


def merge_signal_events(events: List[SignalEvent], gap_s: float = 1.0, max_events: int = 120) -> List[SignalEvent]:
    """Gabungkan event berdekatan agar satu efek tidak dihitung berulang."""
    merged: List[SignalEvent] = []
    for event in sorted(events, key=lambda x: x.time):
        if not merged or event.time - merged[-1].time > gap_s:
            merged.append(event)
            continue
        current = merged[-1]
        labels = []
        for label in (current.label, event.label):
            if label and label not in labels:
                labels.append(label)
        merged[-1] = SignalEvent(
            time=current.time if current.score >= event.score else event.time,
            score=max(current.score, event.score),
            label="/".join(labels[:2]),
        )
    if len(merged) <= max_events:
        return merged
    top = sorted(merged, key=lambda x: x.score, reverse=True)[:max_events]
    return sorted(top, key=lambda x: x.time)


def detect_sound_effect_events(video_path: str, window_s: float = 0.25) -> List[SignalEvent]:
    """Deteksi efek suara ringan (beat/drop/whoosh/impact) dari energi+ZCR+centroid."""
    import numpy as np

    sample_rate = 16000
    window_size = int(window_s * sample_rate)
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-threads", str(FFMPEG_THREADS),
        "-i", video_path, "-vn", "-ac", "1", "-ar", str(sample_rate), "-f", "f32le", "pipe:1",
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    if proc.stdout is None:
        return []

    rms_values: List[float] = []
    zcr_values: List[float] = []
    centroid_values: List[float] = []
    timestamps: List[float] = []
    idx = 0
    try:
        while True:
            data = proc.stdout.read(window_size * 4)
            if not data:
                break
            if len(data) < window_size * 4:
                data += b"\x00" * (window_size * 4 - len(data))
            arr = np.frombuffer(data, dtype=np.float32)
            if arr.size == 0:
                rms = zcr = centroid = 0.0
            else:
                arr = np.nan_to_num(arr)
                rms = float(np.sqrt(np.mean(arr * arr)))
                signs = np.signbit(arr)
                zcr = float(np.mean(signs[1:] != signs[:-1])) if arr.size > 1 else 0.0
                spectrum = np.abs(np.fft.rfft(arr))
                total = float(np.sum(spectrum))
                if total > 0:
                    freqs = np.fft.rfftfreq(arr.size, d=1.0 / sample_rate)
                    centroid = float(np.sum(freqs * spectrum) / total) / (sample_rate / 2.0)
                else:
                    centroid = 0.0
            rms_values.append(rms)
            zcr_values.append(zcr)
            centroid_values.append(centroid)
            timestamps.append(idx * window_s)
            idx += 1
    finally:
        proc.wait()

    if len(rms_values) < 4:
        return []

    rms_arr = np.array(rms_values)
    zcr_arr = np.array(zcr_values)
    rms_med = float(np.median(rms_arr))
    rms_mad = float(np.median(np.abs(rms_arr - rms_med)))
    zcr_med = float(np.median(zcr_arr))
    zcr_mad = float(np.median(np.abs(zcr_arr - zcr_med)))

    loud_threshold = rms_med + max(3.5 * rms_mad, 0.045)
    sharp_threshold = zcr_med + max(2.5 * zcr_mad, 0.04)
    events: List[SignalEvent] = []

    for i, rms in enumerate(rms_values):
        prev_rms = rms_values[i - 1] if i > 0 else 0.0
        next_rms = rms_values[i + 1] if i + 1 < len(rms_values) else 0.0
        is_local_peak = rms >= prev_rms and rms >= next_rms
        if rms < loud_threshold or not is_local_peak:
            continue
        score = 1.8
        label = "efek suara keras"
        if zcr_values[i] >= sharp_threshold and centroid_values[i] >= 0.25:
            score, label = 2.5, "efek suara tajam"
        elif centroid_values[i] >= 0.35:
            score, label = 2.2, "whoosh/transisi audio"
        elif i >= 1 and i + 1 < len(rms_values) and min(rms_values[i - 1], rms_values[i + 1]) >= loud_threshold * 0.72:
            score, label = 2.4, "drop/beat audio"
        if rms >= 0.035:
            events.append(SignalEvent(time=timestamps[i], score=score, label=label))

    return merge_signal_events(events, gap_s=0.9)


def detect_video_motion_events(video_path: str, fps: float = 2.0) -> List[SignalEvent]:
    """Beda frame grayscale kecil: beda tinggi = gerak/cut visual kuat."""
    import numpy as np

    width, height = 96, 54
    frame_size = width * height
    vf = (
        f"fps={fps},scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,format=gray"
    )
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-threads", str(FFMPEG_THREADS),
        "-i", video_path, "-vf", vf, "-f", "rawvideo", "pipe:1",
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    if proc.stdout is None:
        return []

    diffs: List[float] = []
    timestamps: List[float] = []
    prev = None
    frame_idx = 0
    try:
        while True:
            data = proc.stdout.read(frame_size)
            if not data or len(data) < frame_size:
                break
            frame = np.frombuffer(data, dtype=np.uint8).astype(np.float32)
            if prev is not None:
                diffs.append(float(np.mean(np.abs(frame - prev))))
                timestamps.append(frame_idx / fps)
            prev = frame
            frame_idx += 1
    finally:
        proc.wait()

    if len(diffs) < 4:
        return []

    diff_arr = np.array(diffs)
    med = float(np.median(diff_arr))
    mad = float(np.median(np.abs(diff_arr - med)))
    motion_threshold = med + max(3.0 * mad, 8.0)
    cut_threshold = med + max(5.0 * mad, 16.0)
    events: List[SignalEvent] = []
    for i, diff in enumerate(diffs):
        prev_diff = diffs[i - 1] if i > 0 else 0.0
        next_diff = diffs[i + 1] if i + 1 < len(diffs) else 0.0
        if diff < motion_threshold or diff < prev_diff or diff < next_diff:
            continue
        if diff >= cut_threshold:
            events.append(SignalEvent(time=timestamps[i], score=2.2, label="cut visual kuat"))
        else:
            events.append(SignalEvent(time=timestamps[i], score=1.4, label="gerak visual tinggi"))
    return merge_signal_events(events, gap_s=1.5)


# ── Scoring & penggabungan klip ──────────────────────────────────────────────

def score_segments(
    segments: List[Segment],
    scene_times: List[float],
    spike_times: List[float],
    sound_events: Optional[List[SignalEvent]] = None,
    video_events: Optional[List[SignalEvent]] = None,
) -> List[Clip]:
    sound_events = sound_events or []
    video_events = video_events or []
    clips: List[Clip] = []
    for seg in segments:
        text_norm = seg.text.lower()
        score = 0.0
        reasons: List[str] = []

        hits = [w for w in TRIGGER_WORDS if w in text_norm]
        if hits:
            score += min(2.0 * len(set(hits)), 4.0)
            reasons.append("kata trigger: " + ",".join(list(set(hits))[:3]))

        if seg.text.strip().endswith("?"):
            score += 1.5
            reasons.append("pertanyaan retoris")

        if any(seg.start <= st <= seg.end for st in spike_times):
            score += 2.0
            reasons.append("spike audio")

        spikes_in = [st for st in spike_times if seg.start <= st <= seg.end]
        if len(spikes_in) >= 2:
            score += 2.0
            reasons.append("dugaan tawa/tepuk")

        sound_hits = [ev for ev in sound_events if seg.start <= ev.time <= seg.end]
        if sound_hits:
            score += min(sum(ev.score for ev in sound_hits), 4.0)
            labels: List[str] = []
            for ev in sound_hits:
                if ev.label not in labels:
                    labels.append(ev.label)
            reasons.append("efek suara: " + ",".join(labels[:2]))

        video_hits = [ev for ev in video_events if seg.start <= ev.time <= seg.end]
        if video_hits:
            score += min(sum(ev.score for ev in video_hits), 3.0)
            labels = []
            for ev in video_hits:
                if ev.label not in labels:
                    labels.append(ev.label)
            reasons.append("sinyal video: " + ",".join(labels[:2]))

        if any(abs(st - seg.start) <= 2.0 for st in scene_times):
            score += 1.0
            reasons.append("scene change dekat awal")

        if score > 0:
            clips.append(Clip(seg.start, seg.end, score, " + ".join(reasons), seg.text))
    return clips


def expand_and_merge(clips: List[Clip], segments: List[Segment], scene_times: List[float], duration: float) -> List[Clip]:
    """Pilih anchor by score, expand ke target durasi pakai batas segmen Whisper, lalu merge.

    Batas durasi (MIN_CLIP/TARGET_CLIP/MAX_CLIP) dikalibrasi dari contoh Shorts nyata.
    """
    anchors = sorted(clips, key=lambda x: x.score, reverse=True)
    result: List[Clip] = []

    for anc in anchors:
        if any(not (anc.end <= r.start or anc.start >= r.end) for r in result):
            continue

        clip_start, clip_end = anc.start, anc.end
        if segments:
            idx = min(range(len(segments)), key=lambda i: abs(segments[i].start - anc.start))
            left_idx = right_idx = idx
            clip_start = segments[left_idx].start
            clip_end = segments[right_idx].end

            while (clip_end - clip_start < TARGET_CLIP) and (left_idx > 0 or right_idx < len(segments) - 1):
                can_left = left_idx > 0
                can_right = right_idx < len(segments) - 1
                if can_left and (clip_end - segments[left_idx - 1].start > MAX_CLIP):
                    can_left = False
                if can_right and (segments[right_idx + 1].end - clip_start > MAX_CLIP):
                    can_right = False
                if not can_left and not can_right:
                    break
                if can_left and can_right:
                    dist_left = anc.start - segments[left_idx - 1].start
                    dist_right = segments[right_idx + 1].end - anc.end
                    if dist_left <= dist_right:
                        left_idx -= 1
                        clip_start = segments[left_idx].start
                    else:
                        right_idx += 1
                        clip_end = segments[right_idx].end
                elif can_left:
                    left_idx -= 1
                    clip_start = segments[left_idx].start
                else:
                    right_idx += 1
                    clip_end = segments[right_idx].end

            clip_segments = segments[left_idx: right_idx + 1]
            transcript = " ".join(s.text for s in clip_segments).strip()

            sub_reasons: List[str] = []
            sub_scores: List[float] = []
            for s in clip_segments:
                orig = next((c for c in clips if abs(c.start - s.start) < 0.1), None)
                if orig:
                    sub_scores.append(orig.score)
                    if orig.reason:
                        sub_reasons.extend(orig.reason.split(" + "))
            final_score = sum(sub_scores) if sub_scores else anc.score
            unique_reasons: List[str] = []
            for r in sub_reasons:
                rc = r.strip()
                if rc and rc not in unique_reasons:
                    unique_reasons.append(rc)
            final_reason = " + ".join(unique_reasons) if unique_reasons else anc.reason
        else:
            transcript, final_score, final_reason = anc.transcript, anc.score, anc.reason

        if clip_end - clip_start < TARGET_CLIP:
            needed = TARGET_CLIP - (clip_end - clip_start)
            clip_start = max(0.0, clip_start - needed / 2.0)
            clip_end = min(duration, clip_end + needed / 2.0)
            if clip_end - clip_start < TARGET_CLIP:
                if clip_start == 0.0:
                    clip_end = min(duration, clip_start + TARGET_CLIP)
                elif clip_end == duration:
                    clip_start = max(0.0, clip_end - TARGET_CLIP)

        if scene_times:
            min_diff = 2.0
            best_start = clip_start
            for sc in scene_times:
                diff = abs(sc - clip_start)
                if diff < min_diff and sc >= 0.0 and MIN_CLIP <= clip_end - sc <= MAX_CLIP:
                    min_diff = diff
                    best_start = sc
            clip_start = best_start
            min_diff = 2.0
            best_end = clip_end
            for sc in scene_times:
                diff = abs(sc - clip_end)
                if diff < min_diff and sc <= duration and MIN_CLIP <= sc - clip_start <= MAX_CLIP:
                    min_diff = diff
                    best_end = sc
            clip_end = best_end

        result.append(Clip(clip_start, clip_end, final_score, final_reason, transcript))

    # Gabungkan klip yang overlap atau berdekatan (gap < 2s).
    merged: List[Clip] = []
    for c in sorted(result, key=lambda x: x.start):
        if not merged:
            merged.append(c)
            continue
        last = merged[-1]
        if c.start <= last.end + 2.0:
            new_start = min(last.start, c.start)
            new_end = max(last.end, c.end)
            if new_end - new_start > MAX_CLIP:
                new_end = new_start + MAX_CLIP
            reasons: List[str] = []
            for r in last.reason.split(" + ") + c.reason.split(" + "):
                rc = r.strip()
                if rc and rc not in reasons:
                    reasons.append(rc)
            merged[-1] = Clip(
                new_start, new_end, last.score + c.score,
                " + ".join(reasons), (last.transcript + " \n " + c.transcript).strip(),
            )
        else:
            merged.append(c)

    filtered = [m for m in merged if (m.end - m.start) >= MIN_CLIP]
    if filtered:
        max_score = max(m.score for m in filtered)
        if max_score > 0:
            for m in filtered:
                m.score = round((m.score / max_score) * 10.0, 2)
    return sorted(filtered, key=lambda x: x.score, reverse=True)


def generate_fallback(duration: float, count: int = 6) -> List[Clip]:
    """Klip merata sebagai jaring pengaman jika tidak ada momen terdeteksi."""
    clips: List[Clip] = []
    if duration <= 0:
        return clips
    step = max(30.0, duration / count)
    pos = 0.0
    idx = 0
    while pos < duration and idx < count:
        clips.append(Clip(pos, min(duration, pos + 60.0), 1.0, "fallback - tidak ada trigger", ""))
        pos += step
        idx += 1
    return clips


def clips_to_dicts(clips: List[Clip]) -> List[Dict[str, Any]]:
    return [
        {
            "start": utils.format_hhmmss(c.start),
            "end": utils.format_hhmmss(c.end),
            "start_sec": round(c.start, 3),
            "end_sec": round(c.end, 3),
            "score": c.score,
            "reason": c.reason,
            "transcript": c.transcript,
        }
        for c in clips
    ]


def detect_moments(
    video_path: str,
    segments: List[Segment],
    duration: Optional[float] = None,
    timestamps_out: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Pipeline deteksi momen lengkap. Mengembalikan list dict timestamps."""
    video_path = utils.resolve_path(video_path)
    if duration is None:
        duration = utils.ffprobe_duration(video_path)

    try:
        print("[INFO] Deteksi scene change...")
        scene_times = detect_scene_changes(video_path)
        print(f"[INFO] Scene change: {len(scene_times)} titik")
    except Exception as exc:
        print(f"[WARNING] Deteksi scene gagal: {exc}")
        scene_times = []
    try:
        print("[INFO] Deteksi spike audio...")
        spike_times = detect_audio_spikes(video_path)
        print(f"[INFO] Spike audio: {len(spike_times)} titik")
    except Exception as exc:
        print(f"[WARNING] Deteksi spike audio gagal: {exc}")
        spike_times = []
    try:
        print("[INFO] Deteksi efek suara heuristik...")
        sound_events = detect_sound_effect_events(video_path)
        print(f"[INFO] Efek suara: {len(sound_events)} event")
    except Exception as exc:
        print(f"[WARNING] Deteksi efek suara gagal: {exc}")
        sound_events = []
    try:
        print("[INFO] Deteksi gerak/cut visual heuristik...")
        video_events = detect_video_motion_events(video_path)
        print(f"[INFO] Sinyal video: {len(video_events)} event")
    except Exception as exc:
        print(f"[WARNING] Deteksi sinyal video gagal: {exc}")
        video_events = []

    scored: List[Clip] = []
    if segments:
        scored = score_segments(segments, scene_times, spike_times, sound_events, video_events)

    if not scored:
        print("[INFO] Tidak ada momen dari transkripsi; pakai scene/audio/video untuk fallback.")
        for t in scene_times:
            scored.append(Clip(t, min(duration, t + 45.0), 2.0, "scene change", ""))
        for t in spike_times:
            scored.append(Clip(t, min(duration, t + 30.0), 1.5, "spike audio", ""))
        for ev in sound_events:
            scored.append(Clip(ev.time, min(duration, ev.time + 30.0), ev.score + 1.0, ev.label, ""))
        for ev in video_events:
            scored.append(Clip(ev.time, min(duration, ev.time + 30.0), ev.score, ev.label, ""))

    final_clips = expand_and_merge(scored, segments, scene_times, duration)
    if not final_clips:
        final_clips = generate_fallback(duration, count=6)

    result = clips_to_dicts(final_clips)
    if timestamps_out:
        timestamps_out = utils.resolve_path(timestamps_out)
        utils.ensure_parent_dir(timestamps_out)
        with open(timestamps_out, "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=2, ensure_ascii=False)
        print(f"[INFO] Timestamps disimpan: {timestamps_out}")
    return result
