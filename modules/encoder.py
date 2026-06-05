"""Potong & re-encode video dengan libx264 (software, tanpa GPU).

Menggabungkan logika dari clipper/cut_clips.py (cut presisi + cap 50MB),
compile/shortmaker.sh (reframe 9:16), dan compile/compile.py (segmen terkeras).

Encoder hanya mengurus encode video. Fragmen filter warna/subtitle/overlay
disusun oleh modul color_grader & subtitle_burner lalu di-passing ke sini,
sehingga reframe + grade + subtitle + fade cukup dalam SATU pass encode video.
"""
import os
import subprocess
from typing import Any, Dict, List, Optional, Tuple

from . import utils
from .smart_crop import compute_crop_x

_CFG = utils.load_config()
THREADS = _CFG["encode"]["threads"]
SEEK_PREROLL = _CFG["encode"]["seek_preroll"]
WIDTH = _CFG["video"]["width"]
HEIGHT = _CFG["video"]["height"]
FPS = _CFG["video"]["fps"]
CRF = _CFG["video"]["crf"]
PRESET = _CFG["video"]["preset"]
PROFILE = _CFG["video"]["profile"]
LEVEL = str(_CFG["video"]["level"])
MAX_CLIP_BYTES = int(_CFG["video"]["max_clip_mb"]) * 1024 * 1024
A_CODEC = _CFG["audio"]["codec"]
A_BITRATE = _CFG["audio"]["bitrate"]
A_RATE = _CFG["audio"]["sample_rate"]
A_CHANNELS = _CFG["audio"]["channels"]


def build_reframe_filter(blur_background: bool = False, crop_x: Optional[int] = None) -> str:
    """Filter reframe ke 9:16.

    - blur_background: fit penuh + background blur (tak memotong subjek).
    - crop_x (px, ruang frame ter-scale): crop dengan offset horizontal ke
      subjek (smart-crop). Offset di-clamp via ekspresi agar tak keluar batas.
    - default: center crop.
    """
    if blur_background:
        return (
            f"split[bg_src][fg_src];"
            f"[bg_src]scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
            f"crop={WIDTH}:{HEIGHT},boxblur=20:10[bg];"
            f"[fg_src]scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2"
        )
    if crop_x is not None:
        # Koma di dalam ekspresi crop di-escape (\\,) agar tidak dianggap pemisah filter.
        x_expr = f"min(max({int(crop_x)}\\,0)\\,in_w-{WIDTH})"
        return (
            f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
            f"crop={WIDTH}:{HEIGHT}:{x_expr}:(in_h-{HEIGHT})/2"
        )
    return f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,crop={WIDTH}:{HEIGHT}"


def build_fade_filter(duration: float) -> str:
    """Fade in/out 0.3 detik di awal dan akhir."""
    fade_out = max(duration - 0.3, 0.0)
    return f"fade=t=in:st=0:d=0.3,fade=t=out:st={fade_out:.3f}:d=0.3"


def build_audio_fade(duration: float) -> str:
    fade_out = max(duration - 0.3, 0.0)
    return f"afade=t=in:st=0:d=0.3,afade=t=out:st={fade_out:.3f}:d=0.3"


def build_punchy_audio() -> str:
    """Audio lebih punchy untuk Shorts/Reels (highpass + kompresor + loudnorm)."""
    return ",highpass=f=80,acompressor=threshold=-18dB:ratio=2.5:attack=8:release=120,loudnorm=I=-14:TP=-1.5:LRA=11"


def compose_video_filter(
    duration: float,
    blur_background: bool = False,
    crop_x: Optional[int] = None,
    color_fragment: str = "",
    overlay_fragment: str = "",
    subtitle_fragment: str = "",
    kenburns_fragment: str = "",
) -> str:
    """Susun rantai filter video lengkap dalam satu pass.

    Urutan: reframe → kenburns → fade → format → color → overlay → subtitle.
    Fragmen kosong diabaikan; setiap fragmen non-kosong harus diawali koma.
    """
    chain = build_reframe_filter(blur_background, crop_x=crop_x)
    if kenburns_fragment:
        chain += kenburns_fragment if kenburns_fragment.startswith(",") else f",{kenburns_fragment}"
    chain += f",{build_fade_filter(duration)},format=yuv420p"
    for frag in (color_fragment, overlay_fragment, subtitle_fragment):
        if frag:
            chain += frag if frag.startswith(",") else f",{frag}"
    return chain


def build_precise_trim_args(input_video: str, start: float, dur: float) -> List[str]:
    """Seek dua tahap: cepat ke dekat timestamp, lalu presisi sebelum encode."""
    coarse_start = max(0.0, start - SEEK_PREROLL)
    inner_seek = max(0.0, start - coarse_start)
    args = ["-ss", f"{coarse_start:.3f}", "-accurate_seek", "-i", input_video]
    if inner_seek > 0.001:
        args += ["-ss", f"{inner_seek:.3f}"]
    args += ["-t", f"{dur:.3f}", "-avoid_negative_ts", "make_zero"]
    return args


def _audio_args() -> List[str]:
    return ["-c:a", A_CODEC, "-b:a", str(A_BITRATE), "-ar", str(A_RATE), "-ac", str(A_CHANNELS)]


def encode_segment(
    input_video: str,
    start: float,
    dur: float,
    output: str,
    video_filter: str,
    audio_filter: str = "",
    target_kbps: Optional[int] = None,
) -> None:
    """Encode satu segmen. Jika target_kbps diberi → mode bitrate (cap ukuran)."""
    has_audio = utils.has_audio_stream(input_video)
    cmd = ["ffmpeg", "-hide_banner", "-y", "-loglevel", "error"]
    cmd += build_precise_trim_args(input_video, start, dur)
    cmd += ["-vf", video_filter]
    if audio_filter and has_audio:
        cmd += ["-af", audio_filter]
    cmd += ["-c:v", "libx264"]
    if target_kbps is not None:
        cmd += [
            "-b:v", f"{target_kbps}k",
            "-maxrate", f"{target_kbps}k",
            "-bufsize", f"{target_kbps * 2}k",
        ]
    else:
        cmd += ["-crf", str(CRF)]
    cmd += [
        "-preset", PRESET, "-profile:v", PROFILE, "-level:v", LEVEL,
        "-r", str(FPS), "-pix_fmt", "yuv420p",
    ]
    # Sumber tanpa audio → jangan paksa encode/-af audio (FFmpeg akan error).
    cmd += _audio_args() if has_audio else ["-an"]
    cmd += ["-threads", str(THREADS), "-movflags", "+faststart", output]
    ok, msg = utils.run_cmd(cmd)
    if not ok:
        raise RuntimeError(msg)


def cut_clips(
    input_video: str,
    timestamps: List[Dict[str, Any]],
    output_dir: str,
    title: str,
    max_clips: Optional[int] = None,
    blur_background: bool = False,
    color_fragment: str = "",
    audio_punchy: bool = False,
    subtitle_provider=None,
    smart_crop: bool = False,
) -> List[Dict[str, Any]]:
    """Potong banyak klip dari timestamps (mode clipper). Cap ukuran < max_clip_mb.

    subtitle_provider(item, idx, start, end) -> fragmen filter subtitle (atau "").
    Disuntik dari runner agar encoder tidak bergantung pada subtitle_burner.

    smart_crop: deteksi wajah per klip → crop berpusat subjek. Bila tak ada
    wajah (atau OpenCV absen), fallback ke blur-background untuk sumber
    landscape, atau center-crop untuk sumber lain.
    """
    input_video = utils.resolve_path(input_video)
    output_dir = utils.ensure_dir(utils.resolve_path(output_dir))
    if not os.path.exists(input_video):
        raise RuntimeError("File sumber tidak ditemukan")

    base = utils.sanitize_filename(title, max_len=60)
    selected = timestamps[:max_clips] if max_clips is not None else timestamps
    total = len(selected)
    infos: List[Dict[str, Any]] = []

    src_w, src_h = utils.ffprobe_resolution(input_video) if smart_crop else (0, 0)
    src_aspect = (src_w / src_h) if src_h else 0.0

    for idx, item in enumerate(selected, start=1):
        start = _read_ts(item, "start_sec", "start", 0.0)
        end = _read_ts(item, "end_sec", "end", start + 30.0)
        dur = end - start
        if dur <= 0:
            print(f"[WARNING] Durasi tidak valid untuk klip {idx}, dilewati.")
            continue

        name = f"clip_{idx:02d}_{base}.mp4"
        out_tmp = os.path.join(output_dir, f"tmp_{name}")
        out_final = os.path.join(output_dir, name)

        subtitle_fragment = ""
        if subtitle_provider is not None:
            subtitle_fragment = subtitle_provider(item, idx, start, end) or ""

        # Hybrid smart-crop: wajah → crop ber-offset; tanpa wajah & landscape → blur.
        crop_x = None
        effective_blur = blur_background
        if smart_crop and not blur_background:
            crop_x = compute_crop_x(input_video, start, dur, src_w, src_h, WIDTH, HEIGHT)
            if crop_x is None and src_aspect >= 1.3:
                effective_blur = True

        vf = compose_video_filter(
            dur, blur_background=effective_blur, crop_x=crop_x,
            color_fragment=color_fragment, subtitle_fragment=subtitle_fragment,
        )
        af = build_audio_fade(dur) + (build_punchy_audio() if audio_punchy else "")

        try:
            print(f"[{idx}/{total}] Encode klip: {name} ({dur:.1f}s)")
            encode_segment(input_video, start, dur, out_tmp, vf, af)
            size = os.path.getsize(out_tmp)
            if size <= MAX_CLIP_BYTES:
                os.replace(out_tmp, out_final)
            else:
                target_kbps = max(int((MAX_CLIP_BYTES / 1024 * 8 * 0.92 / dur) - 128), 500)
                print(f"[{idx}/{total}] Ukuran > {MAX_CLIP_BYTES // (1024*1024)}MB, re-encode bitrate {target_kbps} kbps")
                encode_segment(input_video, start, dur, out_final, vf, af, target_kbps=target_kbps)
                _safe_remove(out_tmp)

            final_size = os.path.getsize(out_final)
            print(f"[{idx}/{total}] Selesai: {os.path.basename(out_final)} ({final_size / (1024*1024):.2f} MB)")
            infos.append({
                "filename": os.path.basename(out_final),
                "path": out_final,
                "start": item.get("start"),
                "end": item.get("end"),
                "duration": dur,
                "score": item.get("score", 0),
                "reason": item.get("reason", ""),
                "transcript": item.get("transcript", ""),
                "size_bytes": final_size,
            })
        except Exception as exc:
            print(f"[ERROR] Gagal membuat klip {name}: {exc}")
            _safe_remove(out_tmp)

    return infos


def reframe_single(
    input_video: str,
    output: str,
    max_duration: Optional[float] = None,
    blur_background: bool = False,
    color_fragment: str = "",
    overlay_fragment: str = "",
    subtitle_fragment: str = "",
    smart_crop: bool = False,
    kenburns_fragment: str = "",
) -> str:
    """Reframe 1 video lokal ke 9:16 + grade + overlay (mode single, satu pass)."""
    input_video = utils.resolve_path(input_video)
    output = utils.resolve_path(output)
    utils.ensure_parent_dir(output)
    dur = utils.ffprobe_duration(input_video)
    if max_duration is not None and dur > max_duration:
        dur = max_duration

    # Hybrid smart-crop: wajah → crop ber-offset; else blur/center.
    crop_x = None
    effective_blur = blur_background
    if smart_crop and not blur_background:
        sw, sh = utils.ffprobe_resolution(input_video)
        crop_x = compute_crop_x(input_video, 0.0, dur, sw, sh, WIDTH, HEIGHT)
        if crop_x is None and sh and (sw / sh) >= 1.3:
            effective_blur = True

    vf = compose_video_filter(
        dur, blur_background=effective_blur, crop_x=crop_x,
        color_fragment=color_fragment, overlay_fragment=overlay_fragment,
        subtitle_fragment=subtitle_fragment,
        kenburns_fragment=kenburns_fragment,
    )
    af = build_audio_fade(dur)
    has_audio = utils.has_audio_stream(input_video)

    cmd = ["ffmpeg", "-hide_banner", "-y", "-loglevel", "error", "-i", input_video]
    if max_duration is not None:
        cmd += ["-t", f"{max_duration:.3f}"]
    cmd += ["-vf", vf, "-c:v", "libx264", "-crf", str(CRF),
            "-preset", PRESET, "-profile:v", PROFILE, "-level:v", LEVEL,
            "-r", str(FPS), "-pix_fmt", "yuv420p"]
    if has_audio:
        cmd += ["-af", af, *_audio_args()]
    else:
        cmd += ["-an"]
    cmd += ["-threads", str(THREADS), "-movflags", "+faststart", output]
    ok, msg = utils.run_cmd(cmd)
    if not ok:
        raise RuntimeError(msg)
    return output


# ── Helper mode compile ──────────────────────────────────────────────────────

def find_loudest_start(path: str, take_dur: float) -> float:
    """Cari offset awal dengan RMS audio tertinggi untuk durasi take_dur."""
    total = utils.ffprobe_duration(path)
    if total <= take_dur:
        return 0.0
    best_t, best_v, t = 0.0, -999.0, 0.0
    while t + take_dur <= total:
        proc = subprocess.run(
            ["ffmpeg", "-y", "-ss", str(t), "-t", str(min(take_dur, 3.0)), "-i", path,
             "-af", "astats=metadata=1:reset=1,ametadata=print:key=lavfi.astats.Overall.RMS_level",
             "-f", "null", "-"],
            capture_output=True, text=True,
        )
        for line in proc.stderr.splitlines():
            if "RMS_level" in line and "=" in line:
                try:
                    val = float(line.split("=")[-1].strip())
                    if val > best_v:
                        best_v, best_t = val, t
                except ValueError:
                    pass
        t += 1.0
    print(f"   → Start terbaik: {best_t:.1f}s (RMS {best_v:.1f} dB)")
    return best_t


def cut_simple(input_video: str, start: float, dur: float, output: str) -> str:
    """Potong sederhana + re-encode libx264 (untuk segmen compile)."""
    has_audio = utils.has_audio_stream(input_video)
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-ss", str(start), "-t", str(dur), "-i", input_video,
        "-c:v", "libx264", "-preset", PRESET, "-crf", str(CRF),
        "-r", str(FPS), "-pix_fmt", "yuv420p",
    ]
    cmd += _audio_args() if has_audio else ["-an"]
    cmd += ["-avoid_negative_ts", "make_zero", "-threads", str(THREADS), output]
    ok, msg = utils.run_cmd(cmd)
    if not ok:
        raise RuntimeError(msg)
    return output


def _concat_target_resolution(segment_paths: List[str]) -> Tuple[int, int]:
    """Resolusi target = segmen pertama yang bisa di-probe; fallback ke config."""
    for p in segment_paths:
        w, h = utils.ffprobe_resolution(p)
        if w and h:
            return w, h
    return WIDTH, HEIGHT


def _concat_via_filter(segment_paths: List[str], output: str) -> str:
    """Gabung dengan concat filter: normalkan resolusi/SAR/fps tiap segmen.

    Tahan input beda resolusi/aspek (yang membuat concat demuxer rusak/gagal).
    Audio ikut digabung hanya bila SEMUA segmen punya stream audio; jika tidak,
    output dibuat tanpa audio agar concat tetap berhasil.
    """
    tw, th = _concat_target_resolution(segment_paths)
    all_audio = all(utils.has_audio_stream(p) for p in segment_paths)
    n = len(segment_paths)

    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    for p in segment_paths:
        cmd += ["-i", p]

    parts: List[str] = []
    for i in range(n):
        parts.append(
            f"[{i}:v]scale={tw}:{th}:force_original_aspect_ratio=decrease,"
            f"pad={tw}:{th}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={FPS},format=yuv420p[v{i}]"
        )
        if all_audio:
            parts.append(
                f"[{i}:a]aresample={A_RATE},"
                f"aformat=sample_fmts=fltp:channel_layouts=stereo[a{i}]"
            )
    if all_audio:
        concat_in = "".join(f"[v{i}][a{i}]" for i in range(n))
        parts.append(f"{concat_in}concat=n={n}:v=1:a=1[outv][outa]")
        maps = ["-map", "[outv]", "-map", "[outa]"]
    else:
        concat_in = "".join(f"[v{i}]" for i in range(n))
        parts.append(f"{concat_in}concat=n={n}:v=1:a=0[outv]")
        maps = ["-map", "[outv]"]

    cmd += ["-filter_complex", ";".join(parts), *maps,
            "-c:v", "libx264", "-preset", PRESET, "-crf", str(CRF), "-pix_fmt", "yuv420p"]
    if all_audio:
        cmd += _audio_args()
    cmd += ["-threads", str(THREADS), "-movflags", "+faststart", output]
    ok, msg = utils.run_cmd(cmd)
    if not ok:
        raise RuntimeError(msg)
    return output


def assemble_ranges(input_video: str, ranges: List[Tuple[float, float]], output: str, temp_dir: str) -> str:
    """Potong beberapa range [(start,end), ...] dari satu video lalu gabung jadi satu.

    Dipakai mode --ai-clean: menyisakan hanya bagian bagus (membuang filler/jeda).
    Semua potongan berasal dari sumber yang sama → resolusi seragam.
    """
    input_video = utils.resolve_path(input_video)
    output = utils.resolve_path(output)
    temp_dir = utils.ensure_dir(utils.resolve_path(temp_dir))
    if not ranges:
        raise RuntimeError("Tidak ada range untuk dirangkai")

    parts: List[str] = []
    for i, (start, end) in enumerate(ranges):
        dur = float(end) - float(start)
        if dur <= 0:
            continue
        part = os.path.join(temp_dir, f"clean_{i:03d}.mp4")
        cut_simple(input_video, float(start), dur, part)
        parts.append(part)

    if not parts:
        raise RuntimeError("Tidak ada segmen valid untuk dirangkai")
    if len(parts) == 1:
        os.replace(parts[0], output)
        return output
    return concat_segments(parts, output, temp_dir)


def concat_segments(segment_paths: List[str], output: str, temp_dir: str) -> str:
    """Gabung beberapa segmen. Coba stream copy dulu (cepat), lalu fallback
    concat filter yang menormalkan resolusi/SAR/fps (tahan input heterogen)."""
    filelist = os.path.join(utils.resolve_path(temp_dir), "filelist.txt")
    with open(filelist, "w", encoding="utf-8") as fh:
        for p in segment_paths:
            fh.write(f"file '{os.path.abspath(p)}'\n")
    ok, msg = utils.run_cmd([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "concat", "-safe", "0", "-i", filelist, "-c", "copy", output,
    ])
    if ok:
        return output
    # Stream copy gagal (resolusi/codec/timestamp tidak seragam) → normalisasi.
    print("[WARNING] Concat stream-copy gagal — normalisasi resolusi & re-encode...")
    return _concat_via_filter(segment_paths, output)


# ── Util internal ────────────────────────────────────────────────────────────

def _read_ts(item: Dict[str, Any], sec_key: str, text_key: str, default: float) -> float:
    value = item.get(sec_key)
    if value is None:
        value = item.get(text_key, default)
    if isinstance(value, str):
        return utils.hhmmss_to_sec(value)
    return float(value)


def _safe_remove(path: str) -> None:
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except Exception:
        pass
