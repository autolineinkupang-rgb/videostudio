"""Generate output/report.txt berisi ringkasan hasil pipeline.

Berasal dari clipper/clipper.py (build_report). Mencatat jumlah klip,
durasi total, ukuran total, dan detail per klip.
"""
import os
from typing import Any, Dict, List, Optional

from . import utils


def generate_report(
    clips: List[Dict[str, Any]],
    report_path: str,
    source: str = "",
    mode: str = "",
    timestamps: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """Tulis report.txt. `clips` = list info klip (filename, size_bytes, dst)."""
    report_path = utils.resolve_path(report_path)
    utils.ensure_parent_dir(report_path)

    total_size = sum(c.get("size_bytes", 0) for c in clips)
    total_duration = sum(float(c.get("duration") or 0) for c in clips)

    lines = [
        "VideoStudio Terpadu — Report",
        "=" * 40,
        f"Mode        : {mode}",
        f"Sumber      : {source}",
        f"Total klip  : {len(clips)}",
        f"Durasi total: {total_duration:.1f} detik",
        f"Ukuran total: {total_size / (1024 * 1024):.2f} MB",
        "",
    ]
    for clip in clips:
        size_mb = clip.get("size_bytes", 0) / (1024 * 1024)
        lines.append(clip.get("filename", "?"))
        lines.append(
            f"  start: {clip.get('start', '')}  end: {clip.get('end', '')}  "
            f"durasi: {float(clip.get('duration') or 0):.1f}s  score: {clip.get('score', 0)}  "
            f"ukuran: {size_mb:.2f} MB"
        )
        if clip.get("reason"):
            lines.append(f"  reason: {clip.get('reason')}")
        if clip.get("transcript"):
            lines.append(f"  transcript: {str(clip.get('transcript'))[:200]}")
        lines.append("")

    with open(report_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))

    if timestamps:
        with open(report_path, "a", encoding="utf-8") as fh:
            fh.write("\nDetail timestamps:\n")
            for idx, item in enumerate(timestamps, start=1):
                fh.write(f"clip_{idx:02d}: {item.get('start')} -> {item.get('end')} "
                         f"score={item.get('score', 0)}\n")
                if item.get("reason"):
                    fh.write(f"  reason: {item.get('reason')}\n")

    print(f"[INFO] Report dibuat: {report_path}")
    return report_path
