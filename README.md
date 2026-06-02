# VideoStudio Terpadu

Pipeline pengolahan video berbasis Python untuk membuat **YouTube Shorts / Reels (9:16)** secara otomatis dari satu file `videostudio.py` dengan 3 mode kerja. Dioptimasi untuk hardware mid-range **tanpa GPU** (Intel i5-8350U / 8GB RAM), memakai encoder software `libx264` secara serial dan hemat RAM.

## ✨ Fitur

- **3 mode dalam 1 runner** — `clipper`, `single`, `compile`.
- **Download otomatis** dari YouTube via `yt-dlp` (dukung cookies untuk video login).
- **Transkripsi** dengan `openai-whisper` atau `faster-whisper` (Indonesia/English/auto).
- **Deteksi momen menarik** untuk memotong klip secara otomatis.
- **Subtitle burning dinamis** — muncul sinkron per-segmen/frasa (bukan satu blok statis), 4 style siap pakai: `HYPE`, `KARAOKE`, `PODCAST`, `CLEAN`.
- **Subtitle siap-pakai dari folder `subtitle/`** — taruh file `.srt` di sana → dipakai langsung (transkripsi Whisper dilewati), bisa Anda koreksi manual.
- **Loop koreksi subtitle** — subtitle hasil transkripsi otomatis disalin ke `subtitle/`; koreksi file-nya lalu jalankan ulang → video dirender dengan subtitle yang sudah diperbaiki (tanpa transkripsi ulang).
- **Color grading** (LUT `.cube`, vignette, teks overlay) & **silence cut** via `auto-editor`.
- **Background music** royalty-free + audio mixing (file sendiri, auto-scan `sound/`, atau download per topik via `--music-topic`).
- **Reframe 9:16** dengan **smart-crop** (deteksi wajah, fokus ke subjek) + fallback otomatis ke background blur / center-crop.
- **Laporan** ringkasan hasil di `output/report.txt`.

## 📦 Kebutuhan Sistem

- Linux (diuji di Linux Mint / Ubuntu)
- `ffmpeg` & `ffprobe`
- Python 3.10+ dengan `python3-venv`
- Font DejaVu (`fonts-dejavu`)

Dependensi Python ada di [`requirements.txt`](requirements.txt): `yt-dlp`, `openai-whisper`, `faster-whisper`, `auto-editor`, `psutil`, `numpy`, `PyYAML`, dan `opencv-python-headless` (opsional, untuk smart-crop).

## 🚀 Instalasi

Jalankan installer (memasang dependensi sistem + virtualenv + paket Python, lalu memvalidasi):

```bash
./install.sh
```

Installer akan membuat folder kerja (`input/`, `sound/`, `music_lib/`, `efek/`, `output/clips/`, `temp/`) dan virtualenv `.venv/`.

Verifikasi:

```bash
.venv/bin/python videostudio.py --help
```

## 🎬 Cara Pakai

### Mode `clipper` — URL YouTube → beberapa Shorts

Download → transkripsi → deteksi momen → potong jadi beberapa Shorts.

```bash
.venv/bin/python videostudio.py --mode clipper \
  "https://www.youtube.com/watch?v=XXXX" \
  --subtitle --style HYPE --max-clips 5
```

### Mode `single` — 1 video lokal → 1 Short

Silence cut → reframe 9:16 → color grade → background music.

```bash
.venv/bin/python videostudio.py --mode single input/video.mp4 \
  --blur-background --text "Tonton sampai habis!" --channel "@ChannelAnda"
```

### Mode `compile` — banyak klip → 1 video gabungan

Silence cut → ambil segmen terkeras → gabung → background music. Klip sumber boleh beda resolusi/aspek — segmen otomatis dinormalkan saat penggabungan.

```bash
.venv/bin/python videostudio.py --mode compile --duration 60
```

## ⚙️ Opsi CLI Utama

| Flag | Keterangan |
|------|-----------|
| `--mode {clipper,single,compile}` | Pilih mode pipeline (default: `clipper`) |
| `--model {tiny,base,small}` | Model Whisper untuk transkripsi |
| `--engine {whisper,faster}` | Engine transkripsi |
| `--lang id\|en\|auto` | Bahasa transkripsi |
| `--subtitle` | Bakar subtitle ke klip |
| `--style {HYPE,KARAOKE,PODCAST,CLEAN}` | Style subtitle |
| `--blur-background`, `-b` | Paksa background blur untuk sumber landscape |
| `--smart-crop` / `--no-smart-crop` | Crop fokus ke wajah/subjek (default aktif; perlu OpenCV). Tanpa wajah → fallback blur/center |
| `--lut FILE.cube` | Terapkan LUT warna (mode single & clipper; otomatis dari `efek/` bila kosong) |
| `--music FILE` / `--music-vol 0.2` / `--no-music` | Kontrol background music |
| `--music-topic {tech,motivation,gaming,vlog,educational,drama,funny,chill}` | Download BGM royalty-free per topik ke `music_lib/` |
| `--max-clips N` | Batasi jumlah klip (clipper) |
| `--duration N` | Durasi target (compile) |
| `--cookies FILE` / `--browser-cookies` | Cookies untuk video yang butuh login |
| `--keep-temp` | Jangan hapus folder `temp/` |

Selengkapnya: `videostudio.py --help`.

## 🗂️ Struktur Proyek

```
videostudio/
├── videostudio.py        # Runner utama (clipper / single / compile)
├── config.yaml           # Konfigurasi global (override-able via CLI)
├── install.sh            # Installer dependensi + virtualenv
├── test_pipeline.sh      # Smoke test pipeline
├── requirements.txt      # Dependensi Python
└── modules/              # Modul per-tahap pipeline
    ├── downloader.py        # Download video + metadata (yt-dlp)
    ├── transcriber.py       # Transkripsi (whisper / faster-whisper) + parse SRT folder subtitle/
    ├── moment_detector.py   # Deteksi momen menarik
    ├── encoder.py           # Potong & re-encode (libx264)
    ├── subtitle_burner.py   # Burn subtitle dinamis (4 style)
    ├── smart_crop.py        # Smart-crop deteksi wajah (OpenCV) untuk reframe
    ├── color_grader.py      # LUT, vignette, teks overlay
    ├── audio_mixer.py       # Mixing background music
    ├── music_finder.py      # Cari musik royalty-free per topik
    ├── reporter.py          # Generate report.txt
    └── utils.py             # Utilitas bersama + loader config
```

Folder kerja (`input/`, `sound/`, `efek/`, `subtitle/`, `output/`, `temp/`, dll.) di-*ignore* oleh git kecuali penanda `.gitkeep`.

> **Subtitle siap-pakai & loop koreksi:** taruh file `.srt` di folder `subtitle/`. Bila ada,
> pipeline memakainya (transkripsi Whisper dilewati). Nama file dicocokkan dengan nama video
> sumber, jika tak cocok dipakai `.srt` pertama.
>
> Jika belum ada, subtitle hasil transkripsi **otomatis disalin ke `subtitle/`** (tidak menimpa
> file yang sudah ada). Koreksi file itu lalu jalankan ulang → video dirender dengan subtitle
> yang sudah diperbaiki. Di mode single, **`--subtitle` menonaktifkan silence-cut** agar timing
> subtitle (relatif ke video asli) tetap pas.

## 🔧 Konfigurasi

Semua default ada di [`config.yaml`](config.yaml) dan bisa di-*override* lewat flag CLI: resolusi/fps/CRF video, codec/bitrate audio, thread FFmpeg, model & guard RAM transkripsi, batas durasi klip, dan path font.

## 📄 Lisensi

Belum ditentukan. Tambahkan file `LICENSE` bila diperlukan.
