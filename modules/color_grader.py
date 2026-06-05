"""Color grading: LUT (.cube), efek warna, vignette, dan teks overlay.

Berasal dari compile/shortmaker.sh (logika LUT + drawtext channel/teks).
Menghasilkan fragmen filter yang digabung ke pass encode utama.
"""
import os
from typing import Optional

from . import utils

_CFG = utils.load_config()
SAFE_ZONE = 250  # pixel dari atas/bawah — area aman UI YouTube/TikTok


def find_lut(efek_dir: str = "efek") -> Optional[str]:
    """Ambil file .cube pertama dari folder efek/ jika ada."""
    efek_dir = utils.resolve_path(efek_dir)
    if not os.path.isdir(efek_dir):
        return None
    cubes = sorted(f for f in os.listdir(efek_dir) if f.lower().endswith(".cube"))
    return os.path.join(efek_dir, cubes[0]) if cubes else None


def _escape_lut_path(path: str) -> str:
    return path.replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


def build_color_filter(lut: Optional[str] = None, effects: bool = False) -> str:
    """Fragmen filter warna. LUT bila tersedia, jika tidak boost default.

    effects=True menambah tajam (unsharp) + vignette untuk gaya Shorts/Reels.
    """
    frag = ""
    if lut and os.path.exists(utils.resolve_path(lut)):
        lut_path = _escape_lut_path(utils.resolve_path(lut))
        frag += f",lut3d='{lut_path}',eq=contrast=1.05:saturation=1.1"
    else:
        frag += ",eq=contrast=1.1:brightness=0.02:saturation=1.15:gamma=1.05"
    if effects:
        frag += ",unsharp=5:5:0.55:3:3:0.25,vignette=PI/6"
    return frag


def build_effects_filter() -> str:
    """Fragmen efek video ringan untuk mode clipper --effects (warna lebih hidup)."""
    return ",eq=contrast=1.07:saturation=1.12:brightness=0.01,unsharp=5:5:0.55:3:3:0.25,vignette=PI/6"


def _escape_drawtext(text: str) -> str:
    # Escape karakter spesial drawtext agar teks user aman.
    return (
        text.replace("\\", "\\\\").replace(":", "\\:").replace("'", "’")
        .replace("%", "\\%")
    )


def build_overlay_filter(
    text: Optional[str] = None,
    channel: Optional[str] = None,
    font: Optional[str] = None,
    safe_zone: int = SAFE_ZONE,
) -> str:
    """Fragmen drawtext: nama channel (kiri atas) + teks custom (tengah bawah)."""
    font_path = utils.find_font(font or _CFG["paths"]["font_bold"])
    fontfile = f":fontfile='{font_path}'" if font_path and os.path.exists(font_path) else ""
    frag = ""

    if channel:
        frag += (
            f",drawtext=text='{_escape_drawtext(channel)}'{fontfile}"
            f":fontsize=38:fontcolor=white"
            f":shadowcolor=black@0.7:shadowx=2:shadowy=2"
            f":x=24:y={safe_zone}+20"
            f":alpha='if(lt(t,0.5),t*2,1)'"
        )
    if text:
        frag += (
            f",drawtext=text='{_escape_drawtext(text)}'{fontfile}"
            f":fontsize=52:fontcolor=white"
            f":box=1:boxcolor=black@0.55:boxborderw=14"
            f":x=(w-tw)/2:y=h-{safe_zone}-th-20"
            f":alpha='if(lt(t,0.5),0,1)'"
        )
    return frag


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
