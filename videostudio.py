#!/usr/bin/env python3
"""VideoStudio Terpadu — runner utama (3 mode dalam 1 file).

Mode:
  clipper  : URL YouTube → download → transkripsi → deteksi momen → Shorts
  single   : 1 video lokal → silence cut → reframe 9:16 → grade → BGM
  compile  : banyak klip → silence cut → segmen terkeras → gabung → BGM

Dioptimasi untuk hardware mid-range tanpa GPU (libx264, serial, RAM-safe).
"""
import argparse
import glob
import json
import os
import shutil
import sys
from datetime import datetime

# Pastikan paket modules/ bisa diimpor saat dijalankan dari mana pun.
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from modules import (  # noqa: E402
    utils, downloader, transcriber, moment_detector, encoder,
    subtitle_burner, color_grader, audio_mixer, music_finder, reporter,
    ai_client, ai_director,
)

CFG = utils.load_config()
ROOT = utils.ROOT_DIR
INPUT_DIR = os.path.join(ROOT, "input")
SOUND_DIR = os.path.join(ROOT, "sound")
MUSIC_LIB_DIR = os.path.join(ROOT, "music_lib")
EFEK_DIR = os.path.join(ROOT, "efek")
OUTPUT_DIR = os.path.join(ROOT, "output")
CLIPS_DIR = os.path.join(OUTPUT_DIR, "clips")
SUBTITLE_DIR = os.path.join(ROOT, "subtitle")
TEMP_DIR = os.path.join(ROOT, "temp")
LOG_PATH = os.path.join(OUTPUT_DIR, "pipeline.log")


def ensure_directories():
    for path in (INPUT_DIR, SOUND_DIR, MUSIC_LIB_DIR, EFEK_DIR, SUBTITLE_DIR, OUTPUT_DIR, CLIPS_DIR, TEMP_DIR):
        utils.ensure_dir(path)


def find_auto_editor():
    """Cari binary auto-editor di PATH atau lokasi umum pip --user."""
    found = shutil.which("auto-editor")
    if found:
        return found
    candidate = os.path.expanduser("~/.local/bin/auto-editor")
    return candidate if os.path.exists(candidate) else None


def cleanup_temp(keep_temp: bool):
    try:
        if not keep_temp and os.path.isdir(TEMP_DIR):
            shutil.rmtree(TEMP_DIR)
            utils.ensure_dir(TEMP_DIR)
            print("Temporary files dihapus dari folder temp/.")
        elif keep_temp:
            print("Temporary files dipertahankan (--keep-temp).")
    except Exception as exc:
        print("[WARNING] Gagal membersihkan temp.")
        utils.write_log(LOG_PATH, f"[WARNING] cleanup temp: {exc}")


# ── MODE CLIPPER ──────────────────────────────────────────────────────────────

def run_clipper(args):
    print("[1/6] Download video...")
    try:
        mp4_path, _meta_path, metadata = downloader.download_video(
            args.source, INPUT_DIR, cookies=args.cookies, browser_cookies=args.browser_cookies
        )
    except Exception as exc:
        print(f"[ERROR] {exc}")
        sys.exit(1)

    duration = float(metadata.get("duration") or 0.0)
    title = metadata.get("title", "clip")
    if duration:
        print(f"[INFO] Durasi video: {duration / 60:.1f} menit.")

    print("[2/6] Subtitle / transkripsi...")
    srt_path = os.path.join(TEMP_DIR, "subtitle.srt")
    segments = []
    # Subtitle eksternal dari folder subtitle/ → pakai sebagai sumber segmen
    # (deteksi momen + burning), lewati Whisper. Fallback transkripsi bila gagal/kosong.
    ext_srt = utils.find_subtitle_file(SUBTITLE_DIR, metadata.get("id", ""))
    if ext_srt:
        print(f"[INFO] Subtitle eksternal: {os.path.basename(ext_srt)} (transkripsi Whisper dilewati).")
        try:
            segments = transcriber.parse_srt(ext_srt)
        except Exception as exc:
            print(f"[WARNING] Gagal baca subtitle eksternal ({exc}); fallback transkripsi.")
            ext_srt = None
        else:
            if segments:
                print(f"[INFO] {len(segments)} segmen dibaca dari subtitle/.")
            else:
                print("[WARNING] Subtitle eksternal kosong; fallback transkripsi.")
                ext_srt = None
    if not ext_srt:
        try:
            segments, _text, srt_made = transcriber.transcribe(
                mp4_path, model=args.model, engine=args.engine, lang=args.lang, srt_out=srt_path
            )
            # Simpan salinan ke subtitle/ agar bisa dikoreksi & dipakai ulang.
            save_subtitle_copy(srt_made, metadata.get("id") or title)
        except Exception as exc:
            print(f"[WARNING] Transkripsi gagal: {exc}")

    print("[3/6] Pilih momen menarik...")
    timestamps_path = os.path.join(TEMP_DIR, "timestamps.json")
    timestamps = []

    # Opsi AI: LLM memilih cuplikan terbaik dari transkrip. Fallback ke heuristik.
    if args.ai_moments:
        provider = args.ai_provider or os.environ.get("AI_PROVIDER", "gemini")
        if not segments:
            print("[WARNING] Tidak ada transkrip untuk AI — fallback ke deteksi heuristik.")
        elif not ai_client.available(provider):
            print(f"[WARNING] Key AI '{provider}' tidak ada (set di .env) — fallback heuristik.")
        else:
            print(f"[INFO] Memilih momen via AI ({provider})...")
            timestamps = ai_director.select_moments(
                segments, duration, max_clips=args.max_clips, provider=provider
            )
            if timestamps:
                utils.ensure_parent_dir(timestamps_path)
                with open(timestamps_path, "w", encoding="utf-8") as fh:
                    json.dump(timestamps, fh, indent=2, ensure_ascii=False)
                print(f"[INFO] AI memilih {len(timestamps)} momen.")
            else:
                print("[WARNING] AI tidak mengembalikan momen valid — fallback heuristik.")

    if not timestamps:
        timestamps = moment_detector.detect_moments(
            mp4_path, segments, duration=duration, timestamps_out=timestamps_path
        )
    if not timestamps:
        print("[ERROR] Tidak ada momen terdeteksi. Pipeline dihentikan.")
        sys.exit(1)
    print(f"[INFO] {len(timestamps)} momen siap dipotong.")

    # Fragmen filter warna untuk dilebur dalam satu pass encode.
    # Prioritas: LUT (--lut atau auto efek/) → grade + efek opsional;
    # tanpa LUT → perilaku lama (hanya --effects, selain itu polos).
    lut = utils.resolve_path(args.lut) if args.lut else color_grader.find_lut(EFEK_DIR)
    if lut:
        print(f"[INFO] LUT: {os.path.basename(lut)}")
        color_fragment = color_grader.build_color_filter(lut=lut, effects=args.effects)
    else:
        color_fragment = color_grader.build_effects_filter() if args.effects else ""

    subtitle_provider = None
    if args.subtitle:
        def subtitle_provider(item, idx, start, end):
            ass_path = os.path.join(TEMP_DIR, f"clip_{idx:02d}.ass")
            # Subtitle dinamis: segmen Whisper yang overlap jendela klip [start,end].
            window = [s for s in segments if s.end > start and s.start < end]
            ass = None
            if window:
                ass = subtitle_burner.make_clip_ass_timed(
                    window, start, end - start, ass_path, style=args.style,
                )
            if not ass:
                # Fallback: blok statis (klip fallback tanpa segmen / transkripsi gagal).
                transcript = item.get("transcript", "")
                if transcript:
                    ass = subtitle_burner.make_clip_ass(
                        transcript, end - start, ass_path, style=args.style,
                    )
            return subtitle_burner.build_filter(ass) if ass else ""

    print("[4/6] Potong & encode klip (serial, 1 per 1)...")
    infos = encoder.cut_clips(
        mp4_path, timestamps, CLIPS_DIR, title,
        max_clips=args.max_clips, blur_background=args.blur_background,
        color_fragment=color_fragment, audio_punchy=args.effects,
        subtitle_provider=subtitle_provider, smart_crop=args.smart_crop,
    )

    print("[5/6] Background music (opsional)...")
    music = resolve_music(args)
    if music and infos:
        for info in infos:
            try:
                tmp_out = info["path"] + ".bgm.mp4"
                audio_mixer.mix_music(info["path"], music, tmp_out, volume=args.music_vol)
                os.replace(tmp_out, info["path"])
                info["size_bytes"] = os.path.getsize(info["path"])
            except Exception as exc:
                print(f"[WARNING] Gagal mix BGM untuk {info['filename']}: {exc}")
    elif not music:
        print("[INFO] Tidak ada musik — klip tanpa background music.")

    print("[6/6] Laporan akhir...")
    reporter.generate_report(
        infos, os.path.join(OUTPUT_DIR, "report.txt"),
        source=args.source, mode="clipper", timestamps=timestamps,
    )
    print_summary(infos, CLIPS_DIR)


# ── MODE SINGLE ───────────────────────────────────────────────────────────────

def run_single(args):
    source = args.source
    if not source:
        source = utils.find_video_in_dir(INPUT_DIR)
        if not source:
            print(f"[ERROR] Tidak ada video di {INPUT_DIR}. Taruh file atau beri path.")
            sys.exit(1)
        print(f"[INFO] Auto video: {os.path.basename(source)}")
    source = utils.resolve_path(source)
    if not os.path.exists(source):
        print(f"[ERROR] File tidak ditemukan: {source}")
        sys.exit(1)

    basename = utils.sanitize_filename(os.path.splitext(os.path.basename(source))[0])
    work_input = source

    # --- AI clean (opsional): buang filler/jeda/ngelantur lebih dulu ---
    # Menghasilkan video bersih (jadi work_input) + segmen ter-remap utk subtitle.
    ai_clean_segments = None
    did_ai_clean = False
    if args.ai_clean:
        work_input, ai_clean_segments, did_ai_clean = run_ai_clean(args, source, basename)

    # Subtitle eksternal dari folder subtitle/ (timestamp relatif ke video ASLI).
    # Diabaikan bila AI-clean dipakai (perlu transkrip mentah; subtitle dari hasil clean).
    ext_srt = (utils.find_subtitle_file(SUBTITLE_DIR, basename)
               if (args.subtitle and not did_ai_clean) else None)
    # Subtitle bertimestamp ke video kerja, jadi silence-cut dinonaktifkan saat
    # --subtitle (timing) — juga sudah tak perlu bila AI-clean aktif.
    skip_auto = args.no_auto or did_ai_clean
    if args.subtitle and not skip_auto:
        sumber = "eksternal" if ext_srt else "hasil transkripsi"
        print(f"[INFO] --subtitle aktif (subtitle {sumber}) → silence-cut dinonaktifkan "
              "agar timing subtitle tetap pas.")
        skip_auto = True

    # [1] Silence cut dengan auto-editor (opsional).
    if not skip_auto:
        ae = find_auto_editor()
        if ae:
            cut_out = os.path.join(TEMP_DIR, f"{basename}_cut.mp4")
            print("[1/4] Silence cut (auto-editor)...")
            ok = utils.run_step([
                ae, source, "--edit", "audio:threshold=0.04", "--margin", "0.2sec",
                "--video-codec", "libx264", "-o", cut_out,
            ], "auto-editor", LOG_PATH, allow_fail=True)
            if ok and os.path.exists(cut_out):
                work_input = cut_out
            else:
                print("[WARNING] auto-editor gagal — lanjut tanpa silence cut.")
        else:
            print("[WARNING] auto-editor tidak ditemukan — lewati (pakai --no-auto untuk diam).")
    else:
        if did_ai_clean:
            alasan = "AI-clean"
        elif args.subtitle and not args.no_auto:
            alasan = "--subtitle"
        else:
            alasan = "--no-auto"
        print(f"[1/4] Silence cut dilewati ({alasan}).")

    # [2-3] Reframe 9:16 + color grade + overlay + subtitle (satu pass).
    subtitle_fragment = ""
    if args.subtitle:
        ass_path = os.path.join(TEMP_DIR, f"{basename}.ass")
        if did_ai_clean and ai_clean_segments is not None:
            print("[2/4] Subtitle dari hasil AI-clean (sinkron video bersih).")
            try:
                clean_dur = utils.ffprobe_duration(work_input)
                ass = subtitle_burner.make_clip_ass_timed(
                    ai_clean_segments, 0.0, clean_dur, ass_path, style=args.style
                )
                subtitle_fragment = subtitle_burner.build_filter(ass) if ass else ""
            except Exception as exc:
                print(f"[WARNING] Subtitle (AI-clean) dilewati: {exc}")
        elif ext_srt:
            print(f"[2/4] Subtitle dari folder: {os.path.basename(ext_srt)} (transkripsi dilewati).")
            try:
                ass = subtitle_burner.srt_to_ass(ext_srt, ass_path, style=args.style)
                subtitle_fragment = subtitle_burner.build_filter(ass) if ass else ""
            except Exception as exc:
                print(f"[WARNING] Subtitle eksternal dilewati: {exc}")
        else:
            print("[2/4] Transkripsi untuk subtitle...")
            srt_path = os.path.join(TEMP_DIR, f"{basename}.srt")
            try:
                segs, _t, srt = transcriber.transcribe(
                    work_input, model=args.model, engine=args.engine, lang=args.lang, srt_out=srt_path
                )
                if srt:
                    # Simpan salinan ke subtitle/ agar bisa dikoreksi & render ulang.
                    save_subtitle_copy(srt, basename)
                    ass = subtitle_burner.srt_to_ass(srt, ass_path, style=args.style)
                    subtitle_fragment = subtitle_burner.build_filter(ass) if ass else ""
            except Exception as exc:
                print(f"[WARNING] Subtitle dilewati: {exc}")
    else:
        print("[2/4] Subtitle dilewati (tambah --subtitle untuk mengaktifkan).")

    lut = utils.resolve_path(args.lut) if args.lut else color_grader.find_lut(EFEK_DIR)
    if lut:
        print(f"[INFO] LUT: {os.path.basename(lut)}")
    color_fragment = color_grader.build_color_filter(lut=lut, effects=False)
    overlay_fragment = color_grader.build_overlay_filter(text=args.text, channel=args.channel)

    kenburns_fragment = ""
    if getattr(args, "kenburns", False):
        _dur = utils.ffprobe_duration(work_input)
        kenburns_fragment = color_grader.build_kenburns_filter(_dur, direction=getattr(args, "kenburns_direction", "in"))
        if kenburns_fragment:
            print("[INFO] Ken Burns aktif.")

    print("[3/4] Reframe 9:16 + color grade + overlay...")
    reframed = os.path.join(TEMP_DIR, f"{basename}_reframe.mp4")
    try:
        encoder.reframe_single(
            work_input, reframed, max_duration=60.0,
            blur_background=args.blur_background, color_fragment=color_fragment,
            overlay_fragment=overlay_fragment, subtitle_fragment=subtitle_fragment,
            smart_crop=args.smart_crop,
            kenburns_fragment=kenburns_fragment,
        )
    except Exception as exc:
        print(f"[ERROR] Reframe gagal: {exc}")
        sys.exit(1)

    # [4] BGM + output final.
    final_out = os.path.join(OUTPUT_DIR, f"{basename}_SHORT.mp4")
    music = None if args.no_music else resolve_music(args)
    if music:
        print("[4/4] Mix background music...")
        try:
            audio_mixer.mix_music(reframed, music, final_out, volume=args.music_vol)
        except Exception as exc:
            print(f"[WARNING] Mix BGM gagal ({exc}) — output tanpa musik.")
            shutil.copy(reframed, final_out)
    else:
        print("[4/4] Tanpa background music.")
        shutil.copy(reframed, final_out)

    size = os.path.getsize(final_out) if os.path.exists(final_out) else 0
    info = [{
        "filename": os.path.basename(final_out), "path": final_out,
        "duration": utils.ffprobe_duration(final_out), "size_bytes": size,
        "start": "", "end": "", "score": "", "reason": "", "transcript": "",
    }]
    reporter.generate_report(info, os.path.join(OUTPUT_DIR, "report.txt"), source=source, mode="single")
    print_summary(info, OUTPUT_DIR)


# ── MODE COMPILE ──────────────────────────────────────────────────────────────

def run_compile(args):
    clips = sorted(glob.glob(os.path.join(INPUT_DIR, "*.mp4")))
    if not clips:
        print(f"[ERROR] Tidak ada file .mp4 di {INPUT_DIR}")
        sys.exit(1)
    print(f"[INFO] Ditemukan {len(clips)} klip.")
    target = float(args.duration)

    # [1] Silence cut tiap klip.
    ae = find_auto_editor()
    ae_out = []
    for i, clip in enumerate(clips):
        out = os.path.join(TEMP_DIR, f"ae_{i:02d}.mp4")
        if ae:
            print(f"[1] auto-editor [{i+1}/{len(clips)}]: {os.path.basename(clip)}")
            ok = utils.run_step([
                ae, clip, "--edit", "audio:threshold=0.04", "--margin", "0.2sec",
                "--video-codec", "libx264", "-o", out,
            ], "auto-editor", LOG_PATH, allow_fail=True)
            ae_out.append(out if (ok and os.path.exists(out)) else clip)
        else:
            ae_out.append(clip)
    if not ae:
        print("[WARNING] auto-editor tidak ditemukan — pakai klip apa adanya.")

    # [2] Hitung jatah & potong segmen terkeras tiap klip.
    alloc = target / len(ae_out)
    print(f"[2] Jatah per klip: {alloc:.1f}s")
    processed = []
    for i, clip in enumerate(ae_out):
        out = os.path.join(TEMP_DIR, f"proc_{i:02d}.mp4")
        print(f"[2] Potong bagian terbaik [{i+1}/{len(ae_out)}]")
        start = encoder.find_loudest_start(clip, alloc)
        try:
            encoder.cut_simple(clip, start, alloc, out)
            processed.append(out)
        except Exception as exc:
            print(f"[WARNING] Gagal memotong klip {i}: {exc}")
    if not processed:
        print("[ERROR] Tidak ada segmen berhasil dipotong.")
        sys.exit(1)

    # [3] Gabung.
    print("[3] Menggabungkan semua segmen...")
    merged = os.path.join(TEMP_DIR, "merged.mp4")
    try:
        transition_list = getattr(args, "transition", None)
        if transition_list:
            from modules import transitions as _trans
            td = float(CFG.get("effects", {}).get("transition_duration", 0.4))
            print(f"[INFO] Transisi: {', '.join(transition_list)} (td={td}s)")
            _trans.concat_with_transitions(processed, merged, transitions=transition_list, td=td)
        else:
            encoder.concat_segments(processed, merged, TEMP_DIR)
    except Exception as exc:
        print(f"[ERROR] Gagal menggabungkan: {exc}")
        sys.exit(1)

    # [4] BGM + output.
    final_out = os.path.join(OUTPUT_DIR, "output_final.mp4")
    music = resolve_music(args)
    if music:
        print("[4] Mix background music...")
        try:
            audio_mixer.mix_music(merged, music, final_out, volume=args.music_vol)
        except Exception as exc:
            print(f"[WARNING] Mix BGM gagal ({exc}) — output tanpa musik.")
            shutil.copy(merged, final_out)
    else:
        print("[4] Tanpa background music.")
        shutil.copy(merged, final_out)

    final_dur = utils.ffprobe_duration(final_out)
    info = [{
        "filename": os.path.basename(final_out), "path": final_out,
        "duration": final_dur, "size_bytes": os.path.getsize(final_out) if os.path.exists(final_out) else 0,
        "start": "", "end": "", "score": "", "reason": "", "transcript": "",
    }]
    reporter.generate_report(info, os.path.join(OUTPUT_DIR, "report.txt"), source=INPUT_DIR, mode="compile")
    print(f"\n✅ Selesai! Output: {final_out} ({final_dur:.1f}s)")


# ── Helper umum ───────────────────────────────────────────────────────────────

def save_subtitle_copy(srt_src, key):
    """Simpan salinan SRT hasil transkripsi ke folder subtitle/ agar bisa
    dikoreksi lalu dipakai ulang (skip Whisper di run berikutnya).

    Tidak menimpa file yang sudah ada (lindungi koreksi user). `key` = nama
    video/id; dipakai sebagai nama file agar cocok saat pencarian ulang.
    """
    if not srt_src or not os.path.exists(srt_src):
        return
    safe = utils.sanitize_filename(key) or "subtitle"
    dest = os.path.join(SUBTITLE_DIR, f"{safe}.srt")
    if os.path.exists(dest):
        return  # jangan timpa — mungkin sudah dikoreksi user
    try:
        utils.ensure_dir(SUBTITLE_DIR)
        shutil.copy(srt_src, dest)
        print(f"[INFO] Subtitle disimpan ke subtitle/{safe}.srt "
              "— koreksi lalu jalankan ulang untuk memakai versi perbaikan.")
    except Exception as exc:
        print(f"[WARNING] Gagal menyimpan salinan subtitle: {exc}")


def run_ai_clean(args, source, basename):
    """Bersihkan video sumber dengan AI (buang filler/jeda/ngelantur).

    Mengembalikan (work_input, remapped_segments, did_clean). Bila gagal/tak ada
    key → kembalikan (source, None, False) agar pipeline lanjut tanpa pembersihan.
    """
    provider = args.ai_provider or os.environ.get("AI_PROVIDER", "gemini")
    if not ai_client.available(provider):
        print(f"[WARNING] --ai-clean: key AI '{provider}' tidak ada (set di .env) — pembersihan dilewati.")
        return source, None, False

    print(f"[1/4] AI clean: transkripsi + analisis ({provider})...")
    try:
        segs, _t, _srt = transcriber.transcribe(
            source, model=args.model, engine=args.engine, lang=args.lang
        )
    except Exception as exc:
        print(f"[WARNING] --ai-clean: transkripsi gagal ({exc}) — pembersihan dilewati.")
        return source, None, False
    if not segs:
        print("[WARNING] --ai-clean: transkrip kosong — pembersihan dilewati.")
        return source, None, False

    remove_idx = ai_director.select_cuts(segs, provider=provider)
    if not remove_idx:
        print("[INFO] --ai-clean: tidak ada bagian yang dibuang (atau respons tak valid).")
        return source, None, False

    ranges, remapped = ai_director.plan_clean(segs, remove_idx)
    if not ranges:
        print("[WARNING] --ai-clean: tidak ada bagian tersisa — pembersihan dilewati.")
        return source, None, False

    cleaned = os.path.join(TEMP_DIR, f"{basename}_clean.mp4")
    try:
        encoder.assemble_ranges(source, ranges, cleaned, TEMP_DIR)
    except Exception as exc:
        print(f"[WARNING] --ai-clean: gagal merangkai ({exc}) — pakai video asli.")
        return source, None, False

    print(f"[INFO] AI clean: {len(remove_idx)} segmen dibuang, "
          f"{len(ranges)} potongan dirangkai → video bersih.")
    return cleaned, remapped, True


def resolve_music(args):
    """Tentukan file musik: --music > --music-topic (download) > auto sound/ > None."""
    if getattr(args, "music", None):
        path = utils.resolve_path(args.music)
        if os.path.exists(path):
            return path
        print(f"[WARNING] Musik tidak ditemukan: {path}")
        return None
    topic = getattr(args, "music_topic", None)
    if topic:
        found = music_finder.find_music_for_topic(topic, MUSIC_LIB_DIR)
        if found:
            return found
        print("[WARNING] Gagal menyiapkan musik dari topik — fallback ke folder sound/.")
    return audio_mixer.find_music(SOUND_DIR)


def print_summary(infos, location):
    total_size = sum(c.get("size_bytes", 0) for c in infos)
    total_dur = sum(float(c.get("duration") or 0) for c in infos)
    print(f"\nKlip selesai : {len(infos)} file")
    print(f"Durasi total : {total_dur:.1f} detik")
    print(f"Ukuran total : {total_size / (1024 * 1024):.2f} MB")
    print(f"Lokasi output: {location}")


def build_parser():
    p = argparse.ArgumentParser(
        description="VideoStudio Terpadu — pipeline video pendek otomatis (3 mode).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("source", nargs="?", default=None, help="URL YouTube (clipper) atau path file (single)")
    p.add_argument("--mode", choices=["clipper", "single", "compile"], default="clipper", help="Pilih mode pipeline")
    p.add_argument("--model", choices=["tiny", "base", "small", "medium"], default=CFG["transcription"]["model"], help="Model Whisper (medium = lebih akurat tapi berat di 8GB)")
    p.add_argument("--engine", choices=["whisper", "faster"], default=CFG["transcription"]["engine"], help="Engine transkripsi")
    p.add_argument("--lang", default=CFG["transcription"]["lang"], help="Bahasa transkripsi (id/en/auto)")
    p.add_argument("--cookies", help="File cookies untuk video yang butuh login")
    p.add_argument("--browser-cookies",
                   choices=["chrome", "firefox", "edge", "chromium", "brave", "vivaldi", "opera"],
                   help="Ambil cookies dari browser")
    p.add_argument("--subtitle", action="store_true", help="Bakar subtitle ke klip")
    p.add_argument("--style", choices=["HYPE", "KARAOKE", "PODCAST", "CLEAN"], default="CLEAN", help="Style subtitle")
    p.add_argument("--lut", help="File LUT .cube (mode single & clipper; auto dari efek/ bila kosong)")
    p.add_argument("--music", help="File background music")
    p.add_argument("--music-topic", choices=music_finder.TOPICS,
                   help="Download BGM royalty-free per topik ke music_lib/ (alternatif --music)")
    p.add_argument("--music-vol", type=float, default=CFG["music"]["volume"], help="Volume musik 0.0-1.0")
    p.add_argument("--no-music", action="store_true", help="Tanpa background music (single)")
    p.add_argument("--no-auto", action="store_true", help="Lewati auto-editor (single)")
    p.add_argument("--text", help="Teks overlay tengah bawah (single)")
    p.add_argument("--channel", default="@YourChannel", help="Nama channel kiri atas (single)")
    p.add_argument("--blur-background", "-b", action="store_true", help="Background blur untuk video landscape")
    p.add_argument("--smart-crop", dest="smart_crop", action="store_true", default=True,
                   help="Crop fokus ke wajah/subjek (default aktif; perlu OpenCV)")
    p.add_argument("--no-smart-crop", dest="smart_crop", action="store_false",
                   help="Matikan smart-crop (pakai center-crop / blur)")
    p.add_argument("--effects", action="store_true", help="Efek warna + audio punchy (clipper)")
    p.add_argument("--kenburns", action="store_true",
                   help="Ken Burns zoom effect (mode single; dilewati jika durasi >45 detik)")
    p.add_argument("--kenburns-direction", choices=["in", "out"], default="in",
                   dest="kenburns_direction",
                   help="Arah Ken Burns: 'in' (zoom masuk, default) atau 'out' (zoom mundur)")
    p.add_argument("--transition", nargs="+", metavar="JENIS",
                   choices=[
                       "fade", "fadewhite", "slideleft", "slideright",
                       "slideup", "slidedown", "wipeleft", "dissolve",
                       "zoom", "pixelize", "squeezeh",
                   ],
                   help=(
                       "Transisi antar klip (mode compile). Satu atau lebih: "
                       "fade fadewhite slideleft slideright slideup slidedown "
                       "wipeleft dissolve zoom pixelize squeezeh. "
                       "Contoh: --transition fade slideleft"
                   ))
    p.add_argument("--ai-moments", action="store_true",
                   help="Pilih cuplikan terbaik via AI/LLM (clipper; perlu API key di .env)")
    p.add_argument("--ai-clean", action="store_true",
                   help="Buang filler/jeda/ngelantur via AI/LLM (single; perlu API key di .env)")
    p.add_argument("--ai-provider", choices=["gemini", "groq"], default=None,
                   help="Provider AI (default: env AI_PROVIDER atau gemini)")
    p.add_argument("--max-clips", type=int, default=None, help="Batasi jumlah klip (clipper)")
    p.add_argument("--duration", type=int, default=CFG["compile"]["target_duration"], help="Durasi target (compile)")
    p.add_argument("--keep-temp", action="store_true", help="Jangan hapus folder temp/")
    return p


def main():
    utils.load_dotenv()  # muat .env (API key fitur AI) bila ada
    args = build_parser().parse_args()

    missing = utils.check_dependencies(("ffmpeg", "ffprobe"))
    if missing:
        print(f"[ERROR] Dependency hilang: {', '.join(missing)}. Jalankan install.sh.")
        sys.exit(1)

    # RAM guard sebelum memuat model Whisper.
    args.model = utils.guard_model_for_ram(args.model, CFG["transcription"]["ram_guard_gb"])

    if args.mode == "clipper" and not args.source:
        print("[ERROR] Mode clipper memerlukan URL. Contoh: --mode clipper 'https://...'")
        sys.exit(1)

    ensure_directories()
    utils.write_log(LOG_PATH, "\n" + "=" * 64)
    utils.write_log(LOG_PATH, f"Pipeline ({args.mode}) dimulai: {datetime.now().isoformat(timespec='seconds')}")

    try:
        if args.mode == "clipper":
            run_clipper(args)
        elif args.mode == "single":
            run_single(args)
        else:
            run_compile(args)
    finally:
        cleanup_temp(args.keep_temp)

    utils.write_log(LOG_PATH, f"Pipeline selesai: {datetime.now().isoformat(timespec='seconds')}")
    print("Pipeline selesai.")


if __name__ == "__main__":
    main()
