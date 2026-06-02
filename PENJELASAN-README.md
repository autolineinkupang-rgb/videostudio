# Penjelasan Lengkap — VideoStudio Terpadu

> Dokumen ini adalah catatan lokal yang menjelaskan isi `README.md` dan cara kerja
> proyek secara mendalam. **Tidak ikut di-commit** (terdaftar di `.gitignore`).
> Tujuannya: jadi rujukan pribadi untuk memahami setiap bagian proyek.

---

## 1. Apa itu VideoStudio Terpadu?

Sebuah **pipeline pengolahan video berbasis Python** yang mengubah video sumber
menjadi konten vertikal **9:16 (1080×1920)** siap unggah ke YouTube Shorts / Reels /
TikTok. Semua dikendalikan dari satu file runner `videostudio.py` dengan **3 mode**.

Dirancang khusus untuk **hardware mid-range tanpa GPU** (acuan: Intel i5-8350U /
8GB RAM). Maka semua encoding memakai **libx264 (software)**, dijalankan **serial**
(satu per satu, bukan paralel) agar hemat RAM, dengan **RAM guard** yang otomatis
menurunkan model Whisper ke `tiny` bila RAM menipis.

---

## 2. Tiga Mode (inti README bagian "Cara Pakai")

### Mode `clipper` — URL YouTube → banyak Shorts
Alur 6 langkah (`run_clipper` di `videostudio.py`):
1. **Download** video + metadata via `yt-dlp` (`modules/downloader.py`).
2. **Transkripsi** audio → segmen bertimestamp (`modules/transcriber.py`).
3. **Deteksi momen menarik** (`modules/moment_detector.py`) — gabungan sinyal:
   kata-trigger, spike audio (RMS), efek suara, gerak/cut visual, scene change.
4. **Potong & encode** tiap klip (`modules/encoder.py: cut_clips`), satu pass:
   reframe 9:16 → fade → grade → subtitle, dengan cap ukuran 50MB.
5. **Background music** opsional (`modules/audio_mixer.py`).
6. **Laporan** ke `output/report.txt` (`modules/reporter.py`).

Cocok untuk: mengubah satu video panjang (podcast, ceramah, wawancara) menjadi
beberapa potongan Shorts otomatis.

### Mode `single` — 1 video lokal → 1 Short
Alur (`run_single`):
1. **Silence cut** via `auto-editor` (buang jeda hening) — opsional (`--no-auto`).
2. **Transkripsi** (HANYA bila `--subtitle` diberikan).
3. **Reframe 9:16 + color grade + overlay + subtitle** dalam satu pass
   (`encoder.reframe_single`). Dibatasi `max_duration=60` detik.
4. **Background music** opsional.

Cocok untuk: memoles satu video jadi satu Short rapi dengan teks/branding sendiri.

> ⚠️ **Catatan penting** (yang sempat membingungkan): di mode single, subtitle
> hanya muncul kalau Anda menambahkan flag `--subtitle`. Tanpa flag itu, akan
> tampil pesan `[2/4] Subtitle dilewati (tambah --subtitle untuk mengaktifkan).`
> Flag `--text` dan `--channel` adalah **overlay drawtext**, BUKAN subtitle ucapan.

### Mode `compile` — banyak klip → 1 video gabungan
Alur (`run_compile`):
1. **Silence cut** tiap klip di `input/`.
2. **Ambil segmen terkeras** (RMS audio tertinggi) tiap klip
   (`encoder.find_loudest_start` + `cut_simple`).
3. **Gabungkan** semua segmen (`encoder.concat_segments`). Sejak perbaikan
   terbaru, **tahan input beda resolusi** — fallback ke concat filter yang
   menormalkan resolusi/SAR/fps.
4. **Background music** opsional.

Cocok untuk: kompilasi montase dari banyak klip pendek.

---

## 3. Penjelasan Setiap Flag CLI

| Flag | Penjelasan rinci |
|------|------------------|
| `source` (posisi) | URL YouTube (clipper) atau path file video (single). Untuk single boleh kosong → auto ambil video pertama di `input/`. |
| `--mode {clipper,single,compile}` | Memilih pipeline. Default `clipper`. |
| `--model {tiny,base,small}` | Ukuran model Whisper. Makin besar = makin akurat tapi lambat & boros RAM. RAM guard bisa memaksa `tiny`. |
| `--engine {whisper,faster}` | `whisper` = openai-whisper; `faster` = faster-whisper (int8, lebih hemat/cepat di CPU). Ada fallback otomatis `faster→whisper`. |
| `--lang id\|en\|auto` | Bahasa transkripsi. `auto` = deteksi otomatis. |
| `--subtitle` | **Mengaktifkan** burning subtitle. Opt-in (lihat catatan di atas). |
| `--style {HYPE,KARAOKE,PODCAST,CLEAN}` | Gaya tampilan subtitle. Default `CLEAN`. |
| `--blur-background`, `-b` | Memaksa background blur (fit penuh, subjek tak terpotong) untuk sumber landscape. |
| `--smart-crop` / `--no-smart-crop` | Crop otomatis fokus ke wajah/subjek (default AKTIF; perlu OpenCV). Tanpa wajah → fallback blur/center. |
| `--lut FILE.cube` | Terapkan LUT warna (mode single). Bila kosong, auto cari `.cube` di `efek/`. |
| `--music FILE` | Pakai file musik tertentu sebagai BGM. |
| `--music-topic {tech,...}` | Download BGM royalty-free per topik ke `music_lib/` (alternatif `--music`). |
| `--music-vol 0.0-1.0` | Volume BGM (default 0.20). |
| `--no-music` | Tanpa BGM (mode single). |
| `--no-auto` | Lewati auto-editor (silence cut). |
| `--text "..."` | Teks overlay tengah-bawah (drawtext), mode single. |
| `--channel "@nama"` | Nama channel kiri-atas (drawtext), mode single. |
| `--effects` | Efek warna lebih hidup + audio punchy (mode clipper). |
| `--max-clips N` | Batasi jumlah klip yang dihasilkan (clipper). |
| `--duration N` | Durasi target video gabungan (compile). |
| `--cookies FILE` / `--browser-cookies` | Cookies untuk video YouTube yang butuh login/verifikasi. |
| `--keep-temp` | Jangan hapus folder `temp/` setelah selesai (untuk debugging). |

### Contoh lengkap (yang BENAR untuk dapat subtitle di single):
```bash
.venv/bin/python videostudio.py --mode single input/video1.mp4 \
  --subtitle --style HYPE \
  --blur-background \
  --text "Tonton sampai habis!" --channel "@KevinClipperKupang"
```

### Contoh & penjelasan mode `clipper`
```bash
# Dasar: 1 URL → otomatis dipotong jadi beberapa Shorts bersubtitle
.venv/bin/python videostudio.py --mode clipper \
  "https://www.youtube.com/watch?v=XXXX" \
  --subtitle --style HYPE --max-clips 5

# Lengkap: + efek warna/audio punchy + BGM per topik + bahasa Indonesia
.venv/bin/python videostudio.py --mode clipper \
  "https://www.youtube.com/watch?v=XXXX" \
  --subtitle --style KARAOKE --effects \
  --music-topic motivation --music-vol 0.18 \
  --lang id --model base --max-clips 8

# Video butuh login → pakai cookies dari browser
.venv/bin/python videostudio.py --mode clipper "URL" \
  --subtitle --browser-cookies brave
```

**Yang terjadi di balik layar (urut):**
1. `yt-dlp` mengunduh video (≤1080p) ke `input/<id>.mp4` + `metadata.json`. Jika
   YouTube menolak (403 / minta verifikasi), pesan errornya menyuruh pakai
   `--cookies` atau `--browser-cookies`.
2. Whisper mentranskripsi → daftar segmen bertimestamp (subtitle dinamis nanti
   diambil dari sini). Bila transkripsi gagal, pipeline tetap lanjut tanpa subtitle.
3. `moment_detector` memberi skor tiap segmen dari banyak sinyal (kata-trigger
   seperti "tapi/ternyata/rahasia", spike audio, efek suara, gerak/cut visual,
   scene change), lalu meng-ekspansi & menggabung jadi klip berdurasi 15–100s.
   Bila tak ada momen → fallback klip merata.
4. Tiap klip di-encode satu pass: reframe 9:16 (smart-crop fokus wajah aktif
   default) → fade → grade (`--effects`) → subtitle dinamis. Klip > 50MB
   di-encode ulang dengan bitrate dibatasi.
5. BGM dicampur bila ada (`--music`/`--music-topic`/auto `sound/`).
6. Hasil di `output/clips/clip_XX_*.mp4` + ringkasan `output/report.txt`.

```bash
# Clipper memakai musik dari sound/ + LUT dari efek/ (keduanya otomatis):
#   • taruh 1 musik di sound/   (mis. sound/bgm.mp3)   → JANGAN pakai --music/--music-topic
#   • taruh 1 LUT  di efek/     (mis. efek/cinematic.cube) → JANGAN pakai --lut
.venv/bin/python videostudio.py --mode clipper "URL" \
  --subtitle --style HYPE --effects \
  --music-vol 0.18 --lang id --max-clips 5

# Atau LUT eksplisit (menimpa auto efek/):
.venv/bin/python videostudio.py --mode clipper "URL" \
  --subtitle --effects --lut efek/cinematic_teal.cube --max-clips 5
```

**Tips clipper:**
- `--max-clips` penting agar tidak menghasilkan terlalu banyak klip pada video panjang.
- `--effects` memberi tampilan lebih "viral" tapi menambah waktu encode; boleh
  digabung dengan LUT (LUT untuk warna, `--effects` untuk unsharp+vignette+audio).
- **LUT `efek/` kini berlaku di clipper** (otomatis bila ada `.cube`, atau `--lut`).
- Musik `sound/` dipakai otomatis bila tidak ada `--music`/`--music-topic`.
- Subtitle clipper kini **per-segmen** (sinkron), bukan satu blok statis.

### Contoh & penjelasan mode `compile`
```bash
# Taruh dulu beberapa .mp4 di folder input/, lalu:
.venv/bin/python videostudio.py --mode compile --duration 60

# Dengan musik sendiri & tanpa silence cut
.venv/bin/python videostudio.py --mode compile --duration 45 \
  --music sound/beat.mp3 --music-vol 0.25 --no-auto
```

**Yang terjadi di balik layar (urut):**
1. Ambil semua `*.mp4` di `input/` (urut alfabetis).
2. Tiap klip di-`auto-editor` untuk membuang jeda hening (kecuali `--no-auto`).
3. Jatah durasi dibagi rata: `--duration / jumlah_klip`. Untuk tiap klip dicari
   **segmen paling "keras"** (RMS audio tertinggi) sepanjang jatah itu, lalu dipotong.
4. Semua segmen digabung. Bila resolusi/codec klip berbeda-beda, penggabungan
   otomatis menormalkan resolusi/SAR/fps (concat filter) supaya tidak rusak.
5. BGM opsional dicampur → `output/output_final.mp4`.

**Tips compile:**
- Mode ini **tidak** me-reframe ke 9:16 dan **tidak** membuat subtitle — fokusnya
  menggabung "bagian terbaik" tiap klip jadi satu video sesuai `--duration`.
- Beri nama file `input/01_*.mp4`, `02_*.mp4`, … untuk mengatur urutan gabungan.
- Klip boleh beda resolusi — sudah ditangani sejak perbaikan concat.

---

## 4. Penjelasan Modul (folder `modules/`)

| File | Tugas |
|------|-------|
| `utils.py` | Pondasi bersama: loader `config.yaml` (+ default & cache), runner subprocess dengan logging (`run_cmd`/`run_step`), helper ffprobe (durasi, resolusi, **cek ada-tidaknya audio**), sanitasi nama file, konversi waktu, cek RAM & dependensi. |
| `downloader.py` | Download video via `yt-dlp`, simpan `metadata.json`, dan ubah error mentah jadi pesan yang menjelaskan langkah perbaikan (403, verifikasi bot, file kosong). |
| `transcriber.py` | Transkripsi audio → daftar `Segment(start,end,text)` + tulis SRT. Unload model dari RAM setelah selesai (penting untuk 8GB). |
| `moment_detector.py` | "Otak" mode clipper — skoring segmen dari banyak sinyal, lalu ekspansi/merge jadi klip berdurasi pas (kalibrasi 15–100s). |
| `encoder.py` | Semua urusan FFmpeg encode: reframe 9:16, fade, cap 50MB, potong presisi (two-stage seek), segmen terkeras, dan penggabungan. Hanya merangkai string filter; fragmen warna/subtitle disuntik dari luar. |
| `subtitle_burner.py` | Konversi transkrip → ASS bergaya (4 style). **Subtitle dinamis**: `make_clip_ass_timed` membuat satu baris per segmen (sinkron), bukan satu blok statis. |
| `smart_crop.py` | **(Baru)** Deteksi wajah (OpenCV Haar) dari sampel frame → hitung offset crop ke subjek. Aman bila OpenCV tak ada (return None → fallback). |
| `color_grader.py` | LUT `.cube`, boost warna, vignette, dan overlay teks (channel & teks custom) via drawtext. |
| `audio_mixer.py` | Mixing BGM ke video (loop + volume rendah), dengan fallback re-encode bila stream-copy gagal & penanganan video tanpa audio. |
| `music_finder.py` | Database topik→musik royalty-free; download via `yt-dlp` ke `music_lib/`. Diakses lewat `--music-topic`. |
| `reporter.py` | Tulis `output/report.txt` (ringkasan jumlah klip, durasi, ukuran, detail per klip). |
| `ai_client.py` | Klien LLM free-tier (Gemini/Groq) via REST/`urllib` — tanpa dependensi. Key dari env; gagal → `None`. Lihat seksi 7. |
| `ai_director.py` | Logika AI: `select_moments` (pilih cuplikan, `--ai-moments`) + `select_cuts`/`plan_clean` (pembersihan, `--ai-clean`). |

---

## 5. Konfigurasi (`config.yaml`)

Semua default ada di sini dan **bisa di-override** lewat flag CLI:
- **video**: `width/height` (1080×1920), `fps` (30), `crf` (18 = kualitas tinggi),
  `preset` (medium), `max_clip_mb` (50), `profile/level` H.264.
- **audio**: `codec` (aac), `bitrate` (192k), `sample_rate` (48000), `channels` (2).
- **encode**: `threads` (4, sesuai i5-8350U), `seek_preroll` (2.0s untuk seek presisi).
- **transcription**: `model` (base), `engine` (whisper), `lang` (id),
  `ram_guard_gb` (3.0 — di bawah ini paksa `tiny`).
- **music**: `volume` (0.20).
- **clip**: `min_sec` (15), `target_sec` (25), `max_sec` (100) — batas durasi klip.
- **compile**: `target_duration` (60).
- **paths**: lokasi font bold & regular (DejaVu).

> 💡 Tips performa: di hardware lambat, `crf 18` + `preset medium` cukup berat.
> Untuk batch lebih cepat, naikkan `crf` ke 20–23 dan ganti `preset` ke
> `veryfast`/`faster` — selisih kualitas kecil, kecepatan jauh meningkat.

---

## 6. Struktur Folder Kerja

```
input/      → video sumber (single/compile) & hasil download (clipper)
sound/      → file musik untuk auto-BGM
music_lib/  → cache musik hasil --music-topic
efek/        → file LUT .cube
output/      → hasil akhir
output/clips/→ klip-klip mode clipper
temp/        → file sementara (dihapus otomatis, kecuali --keep-temp)
```

Semua folder ini **di-ignore git** (isinya), hanya penanda `.gitkeep` yang dilacak.
Itu sebabnya `temp/.gitkeep` kadang perlu dipulihkan setelah pipeline jalan
(cleanup menghapus seluruh `temp/` lalu membuatnya ulang tanpa `.gitkeep`).

### 6.1 Detail folder `sound/` — Musik (BGM)

Folder `sound/` adalah **sumber musik latar otomatis**. Cara kerjanya
(`modules/audio_mixer.py: find_music`):

- Cukup **taruh satu file audio** di `sound/`. Pipeline akan otomatis memakainya
  sebagai BGM jika Anda **tidak** memberi `--music` atau `--music-topic`.
- Format yang dikenali: **`.mp3`, `.wav`, `.m4a`, `.aac`, `.ogg`**.
- Jika ada lebih dari satu file, yang dipakai adalah **file pertama secara
  alfabetis** (mis. `01_beat.mp3` dikalahkan namanya dulu). Beri prefix angka bila
  ingin mengatur mana yang dipilih.

**Urutan prioritas sumber musik** (`videostudio.py: resolve_music`):
```
--music FILE   (file spesifik)         ← tertinggi
   ↓ (kalau tidak ada)
--music-topic  (download ke music_lib/)
   ↓ (kalau tidak ada)
auto-scan sound/  (file pertama)        ← fallback
   ↓ (kalau kosong)
tanpa BGM
```

**Bagaimana musik diproses** (`audio_mixer.mix_music`):
- Musik **di-loop tak terbatas** lalu dipotong mengikuti durasi video
  (`amix duration=first`), jadi musik pendek pun menutup seluruh video.
- Volume diatur `--music-vol` (default **0.20** = 20%, agar tidak menutupi suara asli).
- Video **tidak di-encode ulang** saat mixing (`-c:v copy`) → cepat & tanpa
  penurunan kualitas. Bila copy gagal, otomatis fallback re-encode.
- Jika **video tak punya audio asli**, musik menjadi satu-satunya track (volume penuh).

> Catatan: `--music-topic` mengunduh musik royalty-free ke folder **`music_lib/`**
> (bukan `sound/`). `sound/` murni untuk musik yang Anda taruh sendiri secara manual.

### 6.2 Detail folder `efek/` — LUT / Efek Warna

Folder `efek/` adalah **sumber LUT (Look-Up Table) warna `.cube`** untuk color
grading. Cara kerjanya (`modules/color_grader.py: find_lut`):

- Taruh satu file **`.cube`** di `efek/`. Akan otomatis diterapkan jika Anda
  **tidak** memberi `--lut`.
- Bila ada beberapa, dipakai **`.cube` pertama secara alfabetis**.
- LUT diterapkan via filter FFmpeg `lut3d=...` lalu sedikit boost kontras &
  saturasi. Bila **tidak ada LUT sama sekali**, dipakai boost warna default
  (`eq=contrast=1.1:brightness=0.02:saturation=1.15:gamma=1.05`).

**PENTING — di mode mana `efek/` berlaku:**
- ✅ **Mode `single`** memakai LUT dari `efek/` (lewat `find_lut`) — lihat
  `run_single`. Bisa juga ditimpa flag `--lut path/ke/film.cube`.
- ✅ **Mode `clipper`** kini JUGA memakai LUT dari `efek/` (atau `--lut`). Bila ada
  LUT, dipakai `build_color_filter` (lut3d + grade), digabung efek tambahan bila
  `--effects` aktif. Tanpa LUT, perilaku lama: hanya `--effects` (filter tetap
  `build_effects_filter`) atau polos.
- ❌ **Mode `compile`** tetap tidak menerapkan LUT (fokusnya menggabung, bukan grade).

**Ringkas perbedaan dua jenis "efek":**

| Sumber | Apa | Dipakai di | Cara mengaktifkan |
|--------|-----|-----------|-------------------|
| Folder `efek/` (`*.cube`) | LUT warna sinematik | mode **single & clipper** | otomatis bila ada file, atau `--lut FILE` |
| Flag `--effects` | Filter tetap: warna hidup + unsharp + vignette + audio punchy | mode **clipper** | tambahkan `--effects` (boleh digabung dengan LUT) |

**Contoh memakai LUT di mode single:**
```bash
# Otomatis: taruh teal_orange.cube di efek/, lalu:
.venv/bin/python videostudio.py --mode single input/video1.mp4 --subtitle

# Eksplisit: pilih LUT tertentu
.venv/bin/python videostudio.py --mode single input/video1.mp4 \
  --lut efek/cinematic_teal.cube --subtitle --style CLEAN
```

> Di mana cari LUT `.cube`? Banyak tersedia gratis (cari "free .cube LUT").
> Pastikan formatnya `.cube` standar agar dikenali `lut3d`.

### 6.3 Detail folder `subtitle/` — Subtitle siap-pakai (SRT)

Folder `subtitle/` adalah **sumber subtitle buatan/koreksi sendiri** dalam format
**`.srt`** (timestamp absolut terhadap video sumber). Bila ada file di sini,
pipeline memakainya dan **melewati transkripsi Whisper** — lebih cepat dan teksnya
bisa Anda perbaiki manual.

**Pemilihan file** (`utils.find_subtitle_file`): cocokkan stem dengan nama video
sumber (mis. `video1.srt` untuk `video1.mp4`); bila tak ada yang cocok → pakai
`.srt` **pertama** alfabetis.

**Perilaku per mode:**
- **Clipper:** bila ada `.srt`, di-parse jadi `segments` (`transcriber.parse_srt`)
  lalu dipakai untuk **deteksi momen** DAN **subtitle dinamis** per klip. Whisper
  dilewati. Berlaku kapan pun file ada (karena segmen memang dibutuhkan untuk
  deteksi momen). Burning tetap hanya bila `--subtitle`.
- **Single:** bila `--subtitle` aktif & ada `.srt`, subtitle dibakar langsung dari
  file (`srt_to_ass`).
- **Compile:** tidak memakai subtitle.

**Loop koreksi subtitle (auto-save):**
- Bila TIDAK ada file di `subtitle/`, pipeline transkripsi seperti biasa lalu
  **menyalin SRT hasilnya ke `subtitle/`** (`save_subtitle_copy`). Nama file
  mengikuti video: `subtitle/<id>.srt` (clipper) atau `subtitle/<basename>.srt`
  (single). Salinan **tidak menimpa** file yang sudah ada (lindungi koreksi user).
- Alur: jalankan sekali → SRT muncul di `subtitle/` → koreksi teks/timing →
  jalankan ulang → Whisper dilewati, subtitle perbaikan dipakai, video dirender ulang.

**Single & silence-cut:** karena subtitle (eksternal maupun hasil transkripsi)
bertimestamp ke video ASLI, di mode single **`--subtitle` otomatis menonaktifkan
silence-cut (auto-editor)**. Ini menjamin timing pas DAN membuat SRT yang disimpan
selalu cocok untuk dikoreksi & dipakai ulang. (Mau silence-cut? Jalankan tanpa
`--subtitle`.)

**Catatan timing:** SRT harus selaras dengan video sumber. Untuk single, jangan
gabungkan dengan silence-cut (sudah otomatis dimatikan). Bila file rusak/kosong,
pipeline fallback ke transkripsi Whisper.

**Git:** isi `subtitle/` di-ignore (subtitle Anda tidak ikut commit), hanya
`.gitkeep` yang dilacak.

**Contoh:**
```bash
# Taruh subtitle/video1.srt, lalu (single):
.venv/bin/python videostudio.py --mode single input/video1.mp4 \
  --subtitle --style HYPE --blur-background

# Clipper otomatis pakai subtitle/ bila ada (Whisper dilewati):
.venv/bin/python videostudio.py --mode clipper "URL" --subtitle --max-clips 5
```

---

## 7. Fitur AI (opsional)

Dua fitur berbasis LLM **free-tier**, semuanya **opt-in** (default mati). Tanpa key
/ offline / respons rusak → **otomatis fallback** ke jalur non-AI (pipeline tak gagal).
**Tanpa dependensi baru** — panggilan REST via `urllib` (stdlib).

### 7.1 Setup key (sekali)

```bash
cp .env.example .env     # lalu isi salah satu key
```
Variabel (dibaca dari `.env` atau environment; `.env` di-`.gitignore`):

| Var | Fungsi |
|-----|--------|
| `AI_PROVIDER` | Provider default: `gemini` atau `groq` (bisa ditimpa flag `--ai-provider`) |
| `GEMINI_API_KEY` | Key Google Gemini — gratis: https://aistudio.google.com/apikey |
| `GROQ_API_KEY` | Key Groq — gratis: https://console.groq.com/keys |
| `GEMINI_MODEL` | (opsional) default `gemini-2.0-flash` |
| `GROQ_MODEL` | (opsional) default `llama-3.3-70b-versatile` |

`utils.load_dotenv()` memuat `.env` ke environment saat start (tanpa dependensi).
`modules/ai_client.py` = klien minimal: `complete(prompt, provider, system, ...)` →
teks, atau `None` bila tak ada key / HTTP error / timeout. `available(provider)`
mengecek apakah key tersedia.

### 7.2 `--ai-moments` (mode clipper) — pilih cuplikan terbaik via AI

Menggantikan deteksi momen heuristik: LLM membaca **seluruh transkrip bertimestamp**
lalu memilih cuplikan paling menarik/viral.

Alur (`modules/ai_director.py: select_moments`):
1. Bangun prompt berisi tiap segmen `[mulai-akhir] teks` + batas durasi klip dari `config.yaml`.
2. LLM membalas **JSON array** `[{start,end,reason,score}, ...]`.
3. Parse (toleran terhadap pembungkus ```json), validasi & clamp ke durasi video,
   perpanjang klip terlalu pendek (~target), batasi yang terlalu panjang (`max_sec`).
4. Konversi ke format `timestamps` yang sama persis dengan `moment_detector` → masuk `cut_clips`.
5. **Fallback**: tak ada key / `[]` / parse gagal → otomatis pakai `moment_detector` heuristik.

```bash
.venv/bin/python videostudio.py --mode clipper "URL" \
  --ai-moments --ai-provider gemini --subtitle --max-clips 5
```

### 7.3 `--ai-clean` (mode single) — buang filler/jeda/ngelantur

"Auto-edit cerdas": rangkai ulang video hanya dari bagian bagus (level kalimat).

Alur (`run_ai_clean` + `modules/ai_director.py`):
1. **Transkripsi video sumber** (selalu — butuh transkrip mentah yang masih ada filler).
2. `select_cuts()`: LLM menandai **indeks segmen yang DIBUANG** (filler/pengulangan/
   ngelantur). Balasan `{"remove":[...]}` di-parse; indeks di luar rentang dibuang.
   **Guard**: bila ingin membuang >70% segmen atau respons rusak → `None` (batal bersih).
3. `plan_clean()` (fungsi murni): bentuk **keep-ranges** — segmen tersisa yang berurutan
   digabung; **dipecah** bila ada segmen dibuang ATAU jeda antar-segmen > **0.6 detik**
   (dead-air ikut terbuang). Hasilkan juga **segmen ter-remap** ke timeline video bersih.
4. `encoder.assemble_ranges()`: potong tiap range (`cut_simple`) + gabung (`concat_segments`).
5. Video bersih jadi `work_input` → lanjut reframe/grade/overlay seperti biasa.
6. Bila `--subtitle`: subtitle dibuat dari **segmen ter-remap** (sinkron dengan video
   bersih, **tanpa transkripsi ulang** — hemat waktu di CPU).

Aturan interaksi:
- `--ai-clean` **menonaktifkan silence-cut `auto-editor`** (redundan) dan **mengabaikan
  folder `subtitle/`** (perlu transkrip mentah).
- Tanpa key / gagal di tahap mana pun → **lewati pembersihan**, pakai video asli.

```bash
.venv/bin/python videostudio.py --mode single input/video1.mp4 \
  --ai-clean --subtitle --style HYPE
```

### 7.4 Biaya, privasi, batasan

- **Gratis** memakai free-tier Gemini/Groq (ada batas kuota/rate harian masing-masing
  provider). Pilih provider via `--ai-provider` / `AI_PROVIDER`.
- **Privasi**: transkrip (teks ucapan) DIKIRIM ke API provider. Untuk konten sensitif,
  pertimbangkan tidak memakai fitur AI (jalur non-AI tetap lengkap).
- **Belum diuji live** di repo ini (perlu key + internet): logika klien, parsing,
  konversi, remap, dan fallback sudah diuji dengan mock. Bila respons LLM gagal di-parse
  saat dipakai nyata, prompt/parser tinggal disetel.
- Granularitas `--ai-clean` masih **level kalimat** (v1). Presisi per-kata (word-level)
  bisa jadi peningkatan berikutnya.

---

## 8. Instalasi (`install.sh`)

Script `install.sh` melakukan:
1. Pasang dependensi sistem: `ffmpeg`, `python3-pip`, `python3-venv`, `fonts-dejavu`.
2. Buat virtualenv `.venv/`.
3. Pasang PyTorch CPU-only + `requirements.txt`.
4. Validasi semua dependensi (ffmpeg, ffprobe, yt-dlp, auto-editor, whisper, dll).
5. **Cek OpenCV opsional** (untuk `--smart-crop`) — bila tak ada hanya warning,
   bukan gagal; smart-crop akan fallback ke center/blur.

---

## 9. Riwayat Perbaikan Penting (konteks)

Beberapa peningkatan yang sudah masuk repo:
1. **3 prioritas review**: wire-up `--music-topic`, compile concat tahan beda
   resolusi, penanganan video tanpa stream audio.
2. **Subtitle dinamis + smart-crop hybrid**: subtitle clipper kini sinkron
   per-segmen; reframe fokus ke wajah dengan fallback berlapis.
3. **Info subtitle single**: peringatan saat `--subtitle` tidak dipakai.

---

## 10. Batasan & Catatan Jujur

- Verifikasi sejauh ini sebatas **sintaks, unit logika, dan parsing CLI**.
  Uji visual end-to-end butuh OpenCV terpasang + FFmpeg + video nyata.
- Smart-crop pakai Haar cascade (built-in, tanpa file model) — cukup baik untuk
  wajah frontal, kurang akurat untuk wajah miring ekstrem/kecil. Bisa di-upgrade
  ke detektor DNN (YuNet) bila perlu akurasi lebih tinggi.
- Pembagian waktu pada pemecahan subtitle bersifat **linier per jumlah kata**
  (bukan per kata aktual). Sinkronisasi sempurna butuh word-level timestamps.
- Legal: pastikan musik dari `--music-topic` benar-benar royalty-free sebelum
  dipublikasikan.

---

*Dokumen lokal — bukan bagian dari repositori.*
