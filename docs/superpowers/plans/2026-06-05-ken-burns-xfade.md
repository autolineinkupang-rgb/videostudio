# Ken Burns + xfade Transitions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tambahkan Ken Burns zoom effect (mode `single`, flag `--kenburns`) dan xfade transitions antar klip (mode `compile`, flag `--transition`) ke VideoStudio Terpadu.

**Architecture:** Ken Burns ditambah sebagai fragmen filter baru `kenburns_fragment` di `compose_video_filter()` dan `reframe_single()` agar bisa dirangkai dalam satu FFmpeg pass. xfade masuk ke modul baru `modules/transitions.py` yang membangun filtergraph `xfade` berantai dan dipanggil dari `run_compile()` sebagai pengganti `encoder.concat_segments()` bila flag `--transition` diberikan.

**Tech Stack:** Python 3.10+, FFmpeg (libx264, xfade, zoompan, acrossfade), pytest

---

## File Map

| File | Aksi | Tanggung jawab |
|------|------|----------------|
| `tests/__init__.py` | Buat | Package marker |
| `tests/test_color_grader.py` | Buat | Test `build_kenburns_filter` |
| `tests/test_encoder.py` | Buat | Test `compose_video_filter` dengan kenburns |
| `tests/test_transitions.py` | Buat | Test `_build_xfade_filtergraph`, `concat_with_transitions` (1 klip) |
| `modules/color_grader.py` | Modifikasi | Tambah `build_kenburns_filter()` |
| `modules/encoder.py` | Modifikasi | Tambah `kenburns_fragment` ke `compose_video_filter()` dan `reframe_single()` |
| `modules/transitions.py` | Buat | `get_clip_duration()`, `_build_xfade_filtergraph()`, `concat_with_transitions()` |
| `modules/__init__.py` | Modifikasi | Tambah `"transitions"` ke `__all__` |
| `config.yaml` | Modifikasi | Tambah section `effects` |
| `videostudio.py` | Modifikasi | Tambah `--kenburns`, `--transition`; wire di `run_single` dan `run_compile` |

---

## Task 1: Setup test infrastructure

**Files:**
- Create: `tests/__init__.py`
- Create: `tests/test_color_grader.py`

- [ ] **Step 1: Buat direktori dan file awal**

```bash
touch tests/__init__.py
```

- [ ] **Step 2: Verifikasi pytest tersedia**

```bash
cd /home/kevinman/Video/clip/videostudio && python -m pytest --version
```

Jika belum ada: `pip install pytest`

- [ ] **Step 3: Buat test stub untuk color_grader**

Isi `tests/test_color_grader.py`:

```python
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules import color_grader


def test_placeholder():
    assert True
```

- [ ] **Step 4: Jalankan — pastikan bisa collect**

```bash
cd /home/kevinman/Video/clip/videostudio && python -m pytest tests/ -v
```

Expected output:
```
tests/test_color_grader.py::test_placeholder PASSED
1 passed in 0.XXs
```

---

## Task 2: `build_kenburns_filter()` di `color_grader.py`

**Files:**
- Modify: `modules/color_grader.py`
- Test: `tests/test_color_grader.py`

- [ ] **Step 1: Tulis failing tests**

Ganti isi `tests/test_color_grader.py` dengan:

```python
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules import color_grader


def test_kenburns_direction_in_contains_zoompan():
    frag = color_grader.build_kenburns_filter(10.0, "in")
    assert "zoompan" in frag

def test_kenburns_direction_in_zoom_expression():
    frag = color_grader.build_kenburns_filter(10.0, "in")
    assert "min(zoom+0.0002,1.08)" in frag

def test_kenburns_direction_out_zoom_expression():
    frag = color_grader.build_kenburns_filter(10.0, "out")
    assert "max(1.0,zoom-0.0002)" in frag

def test_kenburns_starts_with_comma():
    frag = color_grader.build_kenburns_filter(10.0)
    assert frag.startswith(",")

def test_kenburns_skip_when_duration_over_45():
    frag = color_grader.build_kenburns_filter(46.0)
    assert frag == ""

def test_kenburns_exactly_45_is_allowed():
    frag = color_grader.build_kenburns_filter(45.0)
    assert frag != ""

def test_kenburns_contains_resolution():
    frag = color_grader.build_kenburns_filter(10.0)
    assert "1080x1920" in frag

def test_kenburns_frame_count_matches_duration():
    # 10 detik × 30 fps = 300 frame
    frag = color_grader.build_kenburns_filter(10.0)
    assert "d=300" in frag
```

- [ ] **Step 2: Jalankan — pastikan semua FAIL**

```bash
cd /home/kevinman/Video/clip/videostudio && python -m pytest tests/test_color_grader.py -v
```

Expected: 8 FAILED (`AttributeError: module 'color_grader' has no attribute 'build_kenburns_filter'`)

- [ ] **Step 3: Implementasikan `build_kenburns_filter` di `modules/color_grader.py`**

Tambahkan fungsi ini di **bagian bawah** `modules/color_grader.py`, setelah `build_overlay_filter`:

```python
def build_kenburns_filter(duration: float, direction: str = "in") -> str:
    """Zoompan Ken Burns lambat untuk mode single.

    Mengembalikan string kosong jika duration > 45 detik karena zoompan
    sangat CPU-intensive pada video panjang (i5-8350U tanpa GPU).
    """
    if duration > 45.0:
        print(f"[WARNING] Ken Burns dilewati: durasi {duration:.1f}s > 45s (terlalu berat untuk CPU).")
        return ""
    fps = _CFG["video"]["fps"]
    total_frames = int(duration * fps)
    w = _CFG["video"]["width"]
    h = _CFG["video"]["height"]
    if direction == "out":
        z_expr = "if(eq(on,1),1.08,max(1.0,zoom-0.0002))"
    else:
        z_expr = "min(zoom+0.0002,1.08)"
    return (
        f",zoompan=z='{z_expr}'"
        f":x='iw/2-(iw/zoom/2)'"
        f":y='ih/2-(ih/zoom/2)'"
        f":d={total_frames}:s={w}x{h}:fps={fps}"
    )
```

- [ ] **Step 4: Jalankan — pastikan semua PASS**

```bash
cd /home/kevinman/Video/clip/videostudio && python -m pytest tests/test_color_grader.py -v
```

Expected: `8 passed`

- [ ] **Step 5: Commit**

```bash
git add modules/color_grader.py tests/__init__.py tests/test_color_grader.py
git commit -m "feat: tambah build_kenburns_filter di color_grader + tests"
```

---

## Task 3: Tambah `kenburns_fragment` ke `compose_video_filter()` dan `reframe_single()`

**Files:**
- Modify: `modules/encoder.py:76-96` (compose_video_filter), `modules/encoder.py:246-290` (reframe_single)
- Test: `tests/test_encoder.py`

- [ ] **Step 1: Tulis failing tests**

Buat `tests/test_encoder.py`:

```python
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules import encoder

_KB_FRAG = ",zoompan=z='min(zoom+0.0002,1.08)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=300:s=1080x1920:fps=30"


def test_compose_includes_kenburns():
    vf = encoder.compose_video_filter(duration=10.0, kenburns_fragment=_KB_FRAG)
    assert "zoompan" in vf


def test_compose_kenburns_before_fade():
    vf = encoder.compose_video_filter(duration=10.0, kenburns_fragment=_KB_FRAG)
    kb_pos = vf.index("zoompan")
    fade_pos = vf.index("fade=t=in")
    assert kb_pos < fade_pos


def test_compose_kenburns_after_reframe():
    vf = encoder.compose_video_filter(duration=10.0, kenburns_fragment=_KB_FRAG)
    scale_pos = vf.index("scale=")
    kb_pos = vf.index("zoompan")
    assert scale_pos < kb_pos


def test_compose_without_kenburns_no_zoompan():
    vf = encoder.compose_video_filter(duration=10.0)
    assert "zoompan" not in vf


def test_compose_kenburns_with_color_fragment():
    vf = encoder.compose_video_filter(
        duration=10.0,
        kenburns_fragment=_KB_FRAG,
        color_fragment=",eq=contrast=1.1",
    )
    assert "zoompan" in vf
    assert "eq=contrast" in vf
```

- [ ] **Step 2: Jalankan — pastikan FAIL**

```bash
cd /home/kevinman/Video/clip/videostudio && python -m pytest tests/test_encoder.py -v
```

Expected: `test_compose_includes_kenburns FAILED` (TypeError: unexpected keyword argument)

- [ ] **Step 3: Update `compose_video_filter()` di `modules/encoder.py:76`**

Ganti seluruh fungsi `compose_video_filter` (baris 76–96):

```python
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
```

- [ ] **Step 4: Update `reframe_single()` di `modules/encoder.py:246`**

Ganti **seluruh** fungsi `reframe_single` (dari `def reframe_single(` sampai `return output` pertamanya) dengan versi baru yang menambahkan `kenburns_fragment`:

```python
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
```

- [ ] **Step 5: Jalankan semua tests**

```bash
cd /home/kevinman/Video/clip/videostudio && python -m pytest tests/ -v
```

Expected: `13 passed`

- [ ] **Step 6: Commit**

```bash
git add modules/encoder.py tests/test_encoder.py
git commit -m "feat: tambah kenburns_fragment ke compose_video_filter dan reframe_single"
```

---

## Task 4: Buat `modules/transitions.py`

**Files:**
- Create: `modules/transitions.py`
- Test: `tests/test_transitions.py`

- [ ] **Step 1: Tulis failing tests**

Buat `tests/test_transitions.py`:

```python
import sys, os, shutil, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules import transitions


# ── _build_xfade_filtergraph ───────────────────────────────────────────────

def test_filtergraph_two_clips_contains_xfade():
    fg, map_v, map_a = transitions._build_xfade_filtergraph(
        durations=[5.0, 5.0], transitions_list=["fade"], td=0.4
    )
    assert "xfade" in fg
    assert "acrossfade" in fg


def test_filtergraph_two_clips_final_labels():
    fg, map_v, map_a = transitions._build_xfade_filtergraph(
        durations=[5.0, 5.0], transitions_list=["fade"], td=0.4
    )
    assert map_v == "[vout]"
    assert map_a == "[aout]"


def test_filtergraph_two_clips_offset():
    # offset = dur[0] - td = 5.0 - 0.4 = 4.6
    fg, _, _ = transitions._build_xfade_filtergraph(
        durations=[5.0, 5.0], transitions_list=["fade"], td=0.4
    )
    assert "offset=4.600" in fg


def test_filtergraph_three_clips_chain():
    fg, map_v, map_a = transitions._build_xfade_filtergraph(
        durations=[4.0, 4.0, 4.0], transitions_list=["fade"], td=0.4
    )
    # Harus ada dua xfade
    assert fg.count("xfade") == 2
    assert fg.count("acrossfade") == 2


def test_filtergraph_cycle_transitions():
    fg, _, _ = transitions._build_xfade_filtergraph(
        durations=[4.0, 4.0, 4.0],
        transitions_list=["fade", "slideleft"],
        td=0.4
    )
    assert "transition=fade" in fg
    assert "transition=slideleft" in fg


def test_filtergraph_single_transition_repeated():
    fg, _, _ = transitions._build_xfade_filtergraph(
        durations=[4.0, 4.0, 4.0],
        transitions_list=["zoom"],
        td=0.4
    )
    assert fg.count("transition=zoom") == 2


# ── concat_with_transitions (1 klip → passthrough) ────────────────────────

def test_single_clip_passthrough(tmp_path):
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"fake-video-data")
    out = str(tmp_path / "out.mp4")
    result = transitions.concat_with_transitions(
        clips=[str(src)], out_path=out, transitions=["fade"]
    )
    assert result == out
    assert open(out, "rb").read() == b"fake-video-data"


# ── validate_transitions ──────────────────────────────────────────────────

def test_invalid_transition_raises():
    try:
        transitions.concat_with_transitions(
            clips=["a.mp4", "b.mp4"], out_path="out.mp4", transitions=["nonexistent"]
        )
        assert False, "Harus raise ValueError"
    except ValueError as e:
        assert "nonexistent" in str(e)


def test_empty_clips_raises():
    try:
        transitions.concat_with_transitions(clips=[], out_path="out.mp4", transitions=["fade"])
        assert False, "Harus raise ValueError"
    except ValueError:
        pass
```

- [ ] **Step 2: Jalankan — pastikan FAIL**

```bash
cd /home/kevinman/Video/clip/videostudio && python -m pytest tests/test_transitions.py -v
```

Expected: semua FAIL (`ModuleNotFoundError: No module named 'modules.transitions'`)

- [ ] **Step 3: Buat `modules/transitions.py`**

```python
"""Transisi antar klip menggunakan FFmpeg xfade filter.

Digunakan di mode compile saat flag --transition diberikan.
concat_with_transitions() menggantikan encoder.concat_segments() bila
user meminta transisi, sambil menjaga backward-compatibility penuh.
"""
import json
import os
import shutil
import subprocess
from typing import List, Tuple

from . import utils

_CFG = utils.load_config()
_FPS = _CFG["video"]["fps"]
_CRF = _CFG["video"]["crf"]
_PRESET = _CFG["video"]["preset"]
_PROFILE = _CFG["video"]["profile"]
_LEVEL = str(_CFG["video"]["level"])
_A_CODEC = _CFG["audio"]["codec"]
_A_BITRATE = _CFG["audio"]["bitrate"]
_A_RATE = _CFG["audio"]["sample_rate"]
_A_CHANNELS = _CFG["audio"]["channels"]
_THREADS = _CFG["encode"]["threads"]

VALID_TRANSITIONS = frozenset({
    "fade", "fadewhite", "slideleft", "slideright",
    "slideup", "slidedown", "wipeleft", "dissolve",
    "zoom", "pixelize", "squeezeh",
})


def get_clip_duration(path: str) -> float:
    """Baca durasi klip dengan ffprobe."""
    cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_entries", "format=duration", path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    data = json.loads(result.stdout)
    return float(data["format"]["duration"])


def _build_xfade_filtergraph(
    durations: List[float],
    transitions_list: List[str],
    td: float,
) -> Tuple[str, str, str]:
    """Bangun filtergraph xfade berantai (pure function, tanpa FFmpeg call).

    Mengembalikan (filtergraph_string, map_video_label, map_audio_label).
    """
    n = len(durations)
    vf_parts: List[str] = []
    af_parts: List[str] = []

    cumulative = 0.0
    for i in range(n - 1):
        transition = transitions_list[i % len(transitions_list)]
        cumulative += durations[i]
        offset = max(0.0, cumulative - (i + 1) * td)

        in_v = f"[v{i:03d}]" if i > 0 else "[0:v]"
        in_a = f"[a{i:03d}]" if i > 0 else "[0:a]"
        next_v = f"[{i + 1}:v]"
        next_a = f"[{i + 1}:a]"
        out_v = "[vout]" if i == n - 2 else f"[v{i + 1:03d}]"
        out_a = "[aout]" if i == n - 2 else f"[a{i + 1:03d}]"

        vf_parts.append(
            f"{in_v}{next_v}xfade=transition={transition}"
            f":duration={td:.3f}:offset={offset:.3f}{out_v}"
        )
        af_parts.append(
            f"{in_a}{next_a}acrossfade=d={td:.3f}{out_a}"
        )

    filtergraph = ";".join(vf_parts + af_parts)
    return filtergraph, "[vout]", "[aout]"


def concat_with_transitions(
    clips: List[str],
    out_path: str,
    transitions: List[str],
    td: float = 0.4,
) -> str:
    """Gabung clips dengan xfade berantai.

    - clips kosong → ValueError
    - 1 klip → copy langsung ke out_path
    - ≥ 2 klip → xfade filtergraph dengan transisi dipilih secara cycle
    """
    if not clips:
        raise ValueError("clips tidak boleh kosong")

    for t in transitions:
        if t not in VALID_TRANSITIONS:
            raise ValueError(
                f"Transisi tidak dikenal: {t!r}. Pilih dari: {sorted(VALID_TRANSITIONS)}"
            )

    if len(clips) == 1:
        utils.ensure_parent_dir(out_path)
        shutil.copy(clips[0], out_path)
        return out_path

    durations = [get_clip_duration(c) for c in clips]

    # Clamp td agar tidak melebihi durasi klip terpendek / 3.
    min_dur = min(durations)
    safe_td = min(td, min_dur / 3.0)
    if safe_td < td:
        print(
            f"[WARNING] --transition duration dikurangi {td}s → {safe_td:.2f}s "
            f"(klip terpendek {min_dur:.1f}s)."
        )
    td = safe_td

    filtergraph, map_v, map_a = _build_xfade_filtergraph(durations, transitions, td)

    input_args: List[str] = []
    for c in clips:
        input_args += ["-i", c]

    cmd = [
        "ffmpeg", "-hide_banner", "-y", "-loglevel", "error",
        *input_args,
        "-filter_complex", filtergraph,
        "-map", map_v, "-map", map_a,
        "-c:v", "libx264", "-crf", str(_CRF),
        "-preset", _PRESET, "-profile:v", _PROFILE, "-level:v", _LEVEL,
        "-r", str(_FPS), "-pix_fmt", "yuv420p",
        "-c:a", _A_CODEC, "-b:a", _A_BITRATE,
        "-ar", str(_A_RATE), "-ac", str(_A_CHANNELS),
        "-threads", str(_THREADS),
        out_path,
    ]

    utils.ensure_parent_dir(out_path)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg xfade gagal:\n{result.stderr[-2000:]}")

    return out_path
```

- [ ] **Step 4: Jalankan — pastikan semua PASS**

```bash
cd /home/kevinman/Video/clip/videostudio && python -m pytest tests/test_transitions.py -v
```

Expected: `9 passed`

- [ ] **Step 5: Jalankan full test suite**

```bash
cd /home/kevinman/Video/clip/videostudio && python -m pytest tests/ -v
```

Expected: `22 passed`

- [ ] **Step 6: Commit**

```bash
git add modules/transitions.py tests/test_transitions.py
git commit -m "feat: tambah modules/transitions.py dengan xfade berantai + tests"
```

---

## Task 5: Update `modules/__init__.py`

**Files:**
- Modify: `modules/__init__.py`

- [ ] **Step 1: Tambahkan `"transitions"` ke `__all__`**

Buka `modules/__init__.py`, tambahkan `"transitions"` ke list `__all__`:

```python
__all__ = [
    "utils",
    "downloader",
    "transcriber",
    "moment_detector",
    "encoder",
    "subtitle_burner",
    "color_grader",
    "audio_mixer",
    "music_finder",
    "reporter",
    "smart_crop",
    "ai_client",
    "ai_director",
    "transitions",
]
```

- [ ] **Step 2: Verifikasi import berfungsi**

```bash
cd /home/kevinman/Video/clip/videostudio && python -c "from modules import transitions; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add modules/__init__.py
git commit -m "chore: register transitions module di __init__.py"
```

---

## Task 6: Update `config.yaml`

**Files:**
- Modify: `config.yaml`

- [ ] **Step 1: Tambahkan section `effects` di `config.yaml`**

Tambahkan di bagian bawah `config.yaml` (setelah block `paths:`):

```yaml
effects:
  transition_duration: 0.4   # detik overlap xfade antar klip (mode compile --transition)
```

- [ ] **Step 2: Verifikasi config terbaca**

```bash
cd /home/kevinman/Video/clip/videostudio && python -c "
from modules import utils
cfg = utils.load_config()
print(cfg.get('effects', {}).get('transition_duration', 'NOT FOUND'))
"
```

Expected: `0.4`

- [ ] **Step 3: Commit**

```bash
git add config.yaml
git commit -m "config: tambah effects.transition_duration default 0.4 detik"
```

---

## Task 7: Wire `--kenburns` ke `videostudio.py` (mode single)

**Files:**
- Modify: `videostudio.py`

- [ ] **Step 1: Tambahkan argparse flag `--kenburns`**

Di `videostudio.py`, setelah baris:
```python
p.add_argument("--effects", action="store_true", help="Efek warna + audio punchy (clipper)")
```

Tambahkan:
```python
p.add_argument("--kenburns", action="store_true",
               help="Ken Burns zoom effect (mode single; dilewati jika durasi >45 detik)")
```

- [ ] **Step 2: Wire di `run_single()`**

Di `run_single()`, cari baris:
```python
    color_fragment = color_grader.build_color_filter(lut=lut, effects=False)
    overlay_fragment = color_grader.build_overlay_filter(text=args.text, channel=args.channel)
```

Tambahkan tepat setelah dua baris itu:
```python
    kenburns_fragment = ""
    if getattr(args, "kenburns", False):
        from modules import utils as _u
        _dur = _u.ffprobe_duration(work_input)
        kenburns_fragment = color_grader.build_kenburns_filter(_dur)
        if kenburns_fragment:
            print("[INFO] Ken Burns aktif.")
```

- [ ] **Step 3: Tambah `kenburns_fragment` ke pemanggilan `encoder.reframe_single()`**

Cari blok:
```python
        encoder.reframe_single(
            work_input, reframed, max_duration=60.0,
            blur_background=args.blur_background, color_fragment=color_fragment,
            overlay_fragment=overlay_fragment, subtitle_fragment=subtitle_fragment,
            smart_crop=args.smart_crop,
        )
```

Ganti menjadi:
```python
        encoder.reframe_single(
            work_input, reframed, max_duration=60.0,
            blur_background=args.blur_background, color_fragment=color_fragment,
            overlay_fragment=overlay_fragment, subtitle_fragment=subtitle_fragment,
            smart_crop=args.smart_crop,
            kenburns_fragment=kenburns_fragment,
        )
```

- [ ] **Step 4: Verifikasi argparse terdaftar**

```bash
cd /home/kevinman/Video/clip/videostudio && python videostudio.py --help | grep kenburns
```

Expected: `--kenburns   Ken Burns zoom effect (mode single; dilewati jika durasi >45 detik)`

- [ ] **Step 5: Commit**

```bash
git add videostudio.py
git commit -m "feat: tambah --kenburns flag ke mode single"
```

---

## Task 8: Wire `--transition` ke `videostudio.py` (mode compile)

**Files:**
- Modify: `videostudio.py`

- [ ] **Step 1: Tambahkan argparse flag `--transition`**

Di `videostudio.py`, setelah baris `--kenburns`, tambahkan:

```python
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
```

- [ ] **Step 2: Wire di `run_compile()`**

Di `run_compile()`, cari blok:
```python
    # [3] Gabung.
    print("[3] Menggabungkan semua segmen...")
    merged = os.path.join(TEMP_DIR, "merged.mp4")
    try:
        encoder.concat_segments(processed, merged, TEMP_DIR)
    except Exception as exc:
        print(f"[ERROR] Gagal menggabungkan: {exc}")
        sys.exit(1)
```

Ganti menjadi:
```python
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
```

- [ ] **Step 3: Verifikasi argparse terdaftar**

```bash
cd /home/kevinman/Video/clip/videostudio && python videostudio.py --help | grep -A3 transition
```

Expected: tampil deskripsi `--transition` dengan daftar pilihan.

- [ ] **Step 4: Jalankan full test suite (pastikan tidak ada regresi)**

```bash
cd /home/kevinman/Video/clip/videostudio && python -m pytest tests/ -v
```

Expected: semua PASS

- [ ] **Step 5: Commit**

```bash
git add videostudio.py
git commit -m "feat: tambah --transition flag ke mode compile dengan xfade"
```

---

## Task 9: Smoke test manual (opsional tapi direkomendasikan)

Jika ada video pendek di `input/` untuk diuji:

- [ ] **Test Ken Burns (mode single)**

```bash
cd /home/kevinman/Video/clip/videostudio
python videostudio.py --mode single --kenburns --no-music 2>&1 | tail -5
```

Expected: `[INFO] Ken Burns aktif.` dan video output di `output/`.

- [ ] **Test `--transition` (mode compile, butuh ≥2 klip di input/)**

```bash
cd /home/kevinman/Video/clip/videostudio
python videostudio.py --mode compile --transition fade slideleft --no-music 2>&1 | tail -5
```

Expected: `[INFO] Transisi: fade, slideleft (td=0.4s)` dan video output di `output/output_final.mp4`.

---

## Ringkasan Perubahan

| Flag | Mode | Efek |
|------|------|------|
| `--kenburns` | `single` | Zoom lambat 1.0→1.08 sepanjang video |
| `--transition fade slideleft` | `compile` | xfade berantai antar klip |
| (tanpa flag) | semua | Tidak ada perubahan perilaku |
