# Design Spec: --no-burn + --multi-clip (mode single)

**Tanggal:** 2026-06-05  
**Status:** Approved

---

## Ringkasan

Dua fitur baru untuk VideoStudio Terpadu:

1. **`--no-burn`** — Flag global yang memisahkan transkripsi dari burning subtitle. Saat aktif bersama `--subtitle`, transkripsi tetap berjalan dan `.srt` disimpan, tapi teks tidak dibakar ke video output.

2. **`--multi-clip`** — Flag untuk mode `single` yang mengubah pipeline dari "1 video → 1 Short" menjadi "1 video lokal → banyak Short clips", dengan deteksi momen otomatis atau timestamp manual.

---

## 1. Fitur: `--no-burn`

### Motivasi

Pengguna yang menggunakan `--subtitle` mendapati tampilan teks di video kurang memuaskan secara visual. Mereka ingin tetap mendapat file `.srt` (untuk keperluan lain) tanpa teks terbakar ke video.

### Cara Kerja

`--no-burn` adalah flag boolean global (`action="store_true"`). Efeknya **hanya aktif saat `--subtitle` juga diberikan**.

```
--subtitle             → transkripsi + simpan .srt + bakar ke video  (perilaku lama)
--subtitle --no-burn   → transkripsi + simpan .srt + TIDAK dibakar ke video  (baru)
--no-burn (tanpa --subtitle) → tidak ada efek
```

### Implementasi per Mode

**Mode `single`:**

Di `run_single()`, setelah `subtitle_fragment` dibangun (semua cabang: AI-clean, eksternal, transkripsi):

```python
if getattr(args, "no_burn", False):
    subtitle_fragment = ""
```

**Mode `clipper`:**

Di `run_clipper()`, modifikasi `subtitle_provider` closure:

```python
if args.subtitle:
    def subtitle_provider(item, idx, start, end):
        if getattr(args, "no_burn", False):
            return ""   # transkripsi sudah terjadi, tapi tidak dibakar
        # ... logika existing ...
```

**Mode `compile`:**

Mode compile tidak melakukan transkripsi di dalam pipeline-nya — ia memproses klip yang sudah ada. `--no-burn` di mode compile tidak berefek (dan tidak perlu dihandle secara khusus).

### Argparse

```python
p.add_argument("--no-burn", action="store_true",
               help="Jangan bakar subtitle ke video (tetap simpan .srt jika --subtitle aktif)")
```

---

## 2. Fitur: `--multi-clip` di Mode `single`

### Motivasi

Mode `single` saat ini hanya menghasilkan 1 Short maksimal 60 detik. Pengguna ingin memproses video lokal panjang dan mendapatkan banyak klip pendek, sama seperti mode `clipper` tapi tanpa langkah download.

### Cara Kerja

Ketika `--multi-clip` aktif di mode `single`, pipeline berubah:

```
NORMAL single (tanpa --multi-clip):
  input lokal → [silence cut] → reframe 9:16 → color → subtitle → 1 output

MULTI-CLIP single (dengan --multi-clip):
  input lokal → [opsional transkripsi] → detect_moments/timestamps → cut_clips → output/clips/
```

Mode `--multi-clip` memanfaatkan ulang fungsi yang sudah ada di mode `clipper`:
- `moment_detector.detect_moments()` untuk deteksi otomatis
- `ai_director.select_moments()` jika `--ai-moments` aktif
- `encoder.cut_clips()` untuk potong dan encode

### Cara Pilih Momen

**1. Otomatis (default):** `moment_detector.detect_moments(video_path, segments, duration)`

- `segments` = hasil transkripsi Whisper jika `--subtitle` aktif, else `[]` (deteksi berbasis visual+audio saja)

**2. Manual via `--timestamps`:** Format `"start-end,start-end,..."` dalam detik.

```
--timestamps "10-45,90-130,180-220"
```

Parser mengkonversi ke list dict `[{"start_sec": 10, "end_sec": 45}, ...]` yang dioper langsung ke `encoder.cut_clips()`, melewati `detect_moments`.

**3. `--clips-per-minute FLOAT`:** Hitung `max_clips` dinamis dari durasi video.

```python
if args.clips_per_minute and args.max_clips is None:
    duration = utils.ffprobe_duration(work_input)
    computed_max = max(1, int(duration / 60.0 * args.clips_per_minute))
    max_clips = computed_max
```

Prioritas `max_clips`: `--max-clips` (hard cap user) > `--clips-per-minute` (kalkulasi) > None (semua momen).

### Output

Sama persis seperti mode `clipper`: disimpan ke `output/clips/clip_01_<basename>.mp4`, `clip_02_...`, dst.

### Argparse (flag baru)

```python
p.add_argument("--multi-clip", action="store_true",
               help="Mode single: hasilkan banyak Short clips (deteksi momen otomatis)")

p.add_argument("--timestamps", default=None, metavar="RANGES",
               help="Override timestamp manual: '10-45,90-130' (detik). Dipakai dengan --multi-clip")

p.add_argument("--clips-per-minute", type=float, default=None, metavar="N",
               dest="clips_per_minute",
               help="Target jumlah klip per menit video (dipakai dengan --multi-clip)")
```

### Parsing `--timestamps`

```python
def parse_timestamps(raw: str) -> List[Dict[str, float]]:
    """Konversi '10-45,90-130' ke list dict {start_sec, end_sec}."""
    result = []
    for part in raw.split(","):
        part = part.strip()
        if "-" not in part:
            continue
        s, e = part.split("-", 1)
        result.append({"start_sec": float(s.strip()), "end_sec": float(e.strip())})
    return result
```

Fungsi ini diletakkan di `videostudio.py` (helper lokal, tidak perlu modul baru).

### Integrasi di `run_single()`

```python
def run_single(args):
    ...
    if getattr(args, "multi_clip", False):
        _run_single_multi(args, work_input, basename)
        return

    # ... pipeline single normal ...
```

Sub-fungsi `_run_single_multi(args, video_path, basename)` di `videostudio.py` yang menjalankan:
1. Transkripsi (opsional, hanya jika `--subtitle`)
2. Pilih timestamps (manual / auto / AI)
3. Bangun `color_fragment`, `subtitle_provider` (sama seperti clipper — jika `--no-burn` aktif, `subtitle_provider` mengembalikan `""` persis seperti clipper)
4. Panggil `encoder.cut_clips()`
5. Opsional BGM per clip
6. Laporan singkat

---

## 3. File yang Diubah

| File | Perubahan |
|------|-----------|
| `videostudio.py` | Tambah `--no-burn`, `--multi-clip`, `--timestamps`, `--clips-per-minute`; helper `parse_timestamps()`; sub-fungsi `_run_single_multi()`; modifikasi `run_single()` dan `subtitle_provider` di `run_clipper()` |

**Tidak ada file modul baru.** Semua perubahan di `videostudio.py` saja.

---

## 4. Error Handling

| Kondisi | Penanganan |
|---------|-----------|
| `--no-burn` tanpa `--subtitle` | Abaikan diam-diam (tidak ada efek, tidak perlu warning) |
| `--multi-clip` tanpa video input | Error: "Tidak ada video di input/" |
| `--timestamps` format salah | Print warning per entry yang tidak bisa di-parse, lanjut dengan yang valid |
| `--timestamps` menghasilkan 0 entry valid | Error: "Tidak ada timestamp valid dari --timestamps" |
| `--clips-per-minute` bersama `--max-clips` | `--max-clips` menang, `--clips-per-minute` diabaikan (dengan info log) |
| `--multi-clip` + moment detection gagal total | Error: "Tidak ada momen terdeteksi" (sama seperti clipper) |

---

## 5. Tidak Termasuk dalam Scope Ini

- `--no-burn` tanpa `--subtitle` berefek (tidak masuk akal)
- `--multi-clip` di mode `clipper` atau `compile` (bukan permintaan)
- Format `--timestamps` selain detik (mis. `mm:ss`) — scope masa depan
- Perubahan pada modul `moment_detector`, `encoder`, atau `subtitle_burner`
