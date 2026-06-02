"""Smart crop subject-aware untuk reframe 9:16.

Sampling beberapa frame dari rentang klip, deteksi wajah dengan OpenCV Haar
cascade (built-in OpenCV, tanpa file model eksternal), lalu hitung offset crop
horizontal agar subjek tidak terpotong saat reframe landscape → portrait.

Aman bila OpenCV TIDAK terpasang: semua fungsi mengembalikan None sehingga
pemanggil (encoder) jatuh ke fallback center-crop / blur-background.
"""
import subprocess
from typing import List, Optional


def _load_detectors():
    """Muat Haar cascade frontal (+ profil). None bila OpenCV tak tersedia."""
    try:
        import cv2
    except Exception:
        return None
    try:
        base = cv2.data.haarcascades
        frontal = cv2.CascadeClassifier(base + "haarcascade_frontalface_default.xml")
        profile = cv2.CascadeClassifier(base + "haarcascade_profileface.xml")
        if frontal.empty():
            return None
        return cv2, frontal, (None if profile.empty() else profile)
    except Exception:
        return None


def _grab_frames(video: str, start: float, dur: float, n: int = 7, sample_w: int = 640):
    """Ambil n frame merata dari [start, start+dur] sebagai array BGR (numpy)."""
    import numpy as np

    frames = []
    if dur <= 0 or n <= 0:
        return frames
    bytes_per_frame_row = sample_w * 3
    for i in range(n):
        t = start + dur * (i + 0.5) / n
        cmd = [
            "ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", video,
            "-frames:v", "1", "-vf", f"scale={sample_w}:-1",
            "-f", "rawvideo", "-pix_fmt", "bgr24", "-",
        ]
        try:
            p = subprocess.run(cmd, capture_output=True)
        except Exception:
            continue
        if not p.stdout:
            continue
        h = len(p.stdout) // bytes_per_frame_row
        if h <= 0:
            continue
        usable = h * bytes_per_frame_row
        frames.append(np.frombuffer(p.stdout[:usable], dtype=np.uint8).reshape(h, sample_w, 3))
    return frames


def compute_crop_x(
    video: str,
    start: float,
    dur: float,
    src_w: int,
    src_h: int,
    out_w: int = 1080,
    out_h: int = 1920,
    sample_w: int = 640,
) -> Optional[int]:
    """Hitung offset-x crop (di ruang frame yang sudah di-scale untuk menutupi
    out_w x out_h) agar berpusat pada wajah. None bila OpenCV/ wajah tak ada.
    """
    if not src_w or not src_h:
        return None
    loaded = _load_detectors()
    if loaded is None:
        return None
    cv2, frontal, profile = loaded
    import numpy as np

    frames = _grab_frames(video, start, dur, sample_w=sample_w)
    if not frames:
        return None

    centers: List[float] = []  # fraksi 0..1 pusat-x wajah (terbobot luas)
    for f in frames:
        gray = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
        faces = list(frontal.detectMultiScale(gray, 1.1, 5, minSize=(30, 30)))
        if not faces and profile is not None:
            faces = list(profile.detectMultiScale(gray, 1.1, 5, minSize=(30, 30)))
        weight = sum(w * h for (x, y, w, h) in faces)
        if weight <= 0:
            continue
        cx = sum((x + w / 2.0) * (w * h) for (x, y, w, h) in faces) / weight
        centers.append(cx / float(sample_w))

    if not centers:
        return None

    cx_frac = float(np.median(centers))
    # Skala "cover": faktor maksimum agar frame menutupi out_w x out_h.
    scale = max(out_w / float(src_w), out_h / float(src_h))
    scaled_w = src_w * scale
    cx = cx_frac * scaled_w
    x = int(round(cx - out_w / 2.0))
    return max(0, min(x, int(scaled_w - out_w)))
