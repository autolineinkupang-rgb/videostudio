# Design Spec: Ken Burns + xfade Transitions

**Tanggal:** 2026-06-05  
**Status:** Approved

---

## Ringkasan

Tambahkan dua fitur efek video ke VideoStudio Terpadu:
1. **Ken Burns** — zoom lambat untuk mode `single` (flag `--kenburns`)
2. **xfade Transitions** — transisi antar klip untuk mode `compile` (flag `--transition`)

---

## 1. Ken Burns

### Lokasi
`modules/color_grader.py` — fungsi baru `build_kenburns_filter(duration, direction)`

### Mekanisme
- Menggunakan FFmpeg `zoompan` filter
- Zoom range: 1.0 → 1.08 (direction `in`) atau 1.08 → 1.0 (direction `out`)
- Default direction: `in`
- **Hard limit:** skip otomatis jika `duration > 45 detik` (zoompan CPU-intensive), tampilkan warning

### Interface
```python
def build_kenburns_filter(duration: float, direction: str = "in") -> str:
    """Kembalikan fragmen filter zoompan Ken Burns.
    Kembalikan string kosong jika duration > 45 detik.
    """
```

### Posisi dalam filter chain
```
reframe → kenburns (zoompan) → fade → format=yuv420p → color → overlay → subtitle
```
Ken Burns disisipkan sebagai parameter baru `kenburns_fragment` di `compose_video_filter()`, **bukan** bagian dari `color_fragment`. Ini agar tidak bentrok saat `color_fragment` (`eq`/LUT) juga aktif.

```python
# encoder.compose_video_filter() — signature yang diperbarui
def compose_video_filter(
    duration: float,
    blur_background: bool = False,
    crop_x: Optional[int] = None,
    color_fragment: str = "",
    overlay_fragment: str = "",
    subtitle_fragment: str = "",
    kenburns_fragment: str = "",   # BARU
) -> str:
    chain = build_reframe_filter(blur_background, crop_x=crop_x)
    if kenburns_fragment:          # setelah reframe, sebelum fade
        chain += kenburns_fragment
    chain += f",{build_fade_filter(duration)},format=yuv420p"
    ...
```

### Integrasi CLI (`videostudio.py`)
```
--kenburns          Aktifkan Ken Burns zoom effect (mode single)
```
- Hanya berlaku di mode `single`
- Jika `--kenburns` diberikan di mode lain → warning dan diabaikan

---

## 2. xfade Transitions

### Lokasi
`modules/transitions.py` — **file baru**

### Fungsi Publik
```python
VALID_TRANSITIONS = {
    "fade", "fadewhite", "slideleft", "slideright",
    "slideup", "slidedown", "wipeleft", "dissolve",
    "zoom", "pixelize", "squeezeh"
}

def get_clip_duration(path: str) -> float:
    """Gunakan ffprobe untuk mendapatkan durasi klip dalam detik."""

def concat_with_transitions(
    clips: list[str],
    out_path: str,
    transitions: list[str],
    td: float = 0.4,
) -> str:
    """Gabung clips dengan xfade berantai.
    
    - clips hanya 1 → passthrough (copy tanpa encode ulang)
    - clips ≥ 2 → bangun filtergraph xfade bertingkat
    - transitions dipilih secara cycle: transisi ke-i = transitions[i % len(transitions)]
    - td = transition duration dalam detik (default 0.4)
    - Kembalikan out_path
    """
```

### Algoritma xfade Chaining
Untuk N klip, dibutuhkan N-1 transisi. Offset tiap xfade dihitung dari akumulasi durasi klip sebelumnya dikurangi overlap transisi:

```
offset[0] = duration(clip[0]) - td
offset[1] = duration(clip[0]) + duration(clip[1]) - 2*td
offset[i] = sum(duration[0..i]) - (i+1)*td
```

Filtergraph pattern untuk 3 klip:
```
[0:v][1:v]xfade=transition=T0:duration=D:offset=O0[v01];
[v01][2:v]xfade=transition=T1:duration=D:offset=O1[vout];
[0:a][1:a]acrossfade=d=D[a01];
[a01][2:a]acrossfade=d=D[aout]
```

### Integrasi ke `run_compile()` (`videostudio.py`)
```python
# Sebelum (saat ini):
output = encoder.concat_segments(segments, out_path)

# Sesudah (dengan --transition):
if args.transition:
    from modules import transitions
    output = transitions.concat_with_transitions(
        segments, out_path,
        transitions=args.transition,
        td=CFG.get("effects", {}).get("transition_duration", 0.4)
    )
else:
    output = encoder.concat_segments(segments, out_path)
```

### Flag CLI (`videostudio.py`)
```
--transition JENIS [JENIS ...]
    Jenis transisi antar klip di mode compile.
    Pilih satu atau lebih dari:
    fade fadewhite slideleft slideright slideup slidedown
    wipeleft dissolve zoom pixelize squeezeh
    Contoh: --transition fade slideleft zoom
```

### Config `config.yaml` (opsional, bisa ditambah)
```yaml
effects:
  transition_duration: 0.4   # detik, default jika --transition digunakan
```

---

## 3. File yang Diubah / Dibuat

| File | Perubahan |
|------|-----------|
| `modules/color_grader.py` | Tambah `build_kenburns_filter()` |
| `modules/transitions.py` | **Buat baru** — `get_clip_duration()`, `concat_with_transitions()` |
| `modules/__init__.py` | Import `transitions` |
| `videostudio.py` | Tambah `--kenburns` dan `--transition` argparse; panggil di `run_single` dan `run_compile` |
| `config.yaml` | Tambah section `effects.transition_duration` |

---

## 4. Error Handling

| Kondisi | Penanganan |
|---------|-----------|
| `--kenburns` di luar mode `single` | Print warning, abaikan flag |
| Ken Burns pada durasi > 45 detik | Print warning, skip Ken Burns, lanjut encode normal |
| `--transition` dengan nilai tidak valid | Argparse `choices` validation, error dini |
| Klip dengan durasi < `td` | Kurangi `td` otomatis ke `duration/3`, print warning |
| `ffprobe` tidak tersedia | Fallback: baca durasi dari metadata klip bila ada, else raise error |

---

## 5. Tidak Termasuk dalam Scope Ini

- Ken Burns di mode `clipper` atau `compile`
- xfade di mode `clipper` atau `single`
- Animasi zoom punch, shake, progress bar (fitur terpisah)
- GPU acceleration (bukan scope project ini)
