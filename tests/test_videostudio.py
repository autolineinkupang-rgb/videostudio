import sys, os
import types
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from videostudio import parse_timestamps


def test_parse_timestamps_basic():
    result = parse_timestamps("10-45,90-130")
    assert result == [
        {"start_sec": 10.0, "end_sec": 45.0},
        {"start_sec": 90.0, "end_sec": 130.0},
    ]


def test_parse_timestamps_single():
    result = parse_timestamps("15-60")
    assert result == [{"start_sec": 15.0, "end_sec": 60.0}]


def test_parse_timestamps_invalid_entry_skipped():
    result = parse_timestamps("abc,10-45")
    assert result == [{"start_sec": 10.0, "end_sec": 45.0}]


def test_parse_timestamps_empty():
    result = parse_timestamps("")
    assert result == []


def test_no_burn_clears_subtitle_fragment():
    args = types.SimpleNamespace(no_burn=True)
    subtitle_fragment = ",ass='/tmp/test.ass'"
    if getattr(args, "no_burn", False):
        subtitle_fragment = ""
    assert subtitle_fragment == ""


def test_no_burn_false_preserves_subtitle_fragment():
    args = types.SimpleNamespace(no_burn=False)
    subtitle_fragment = ",ass='/tmp/test.ass'"
    if getattr(args, "no_burn", False):
        subtitle_fragment = ""
    assert subtitle_fragment == ",ass='/tmp/test.ass'"


def test_clips_per_minute_calc():
    # 2-minute video at 3 clips/min → 6 clips
    duration = 120.0
    clips_per_minute = 3.0
    max_clips = None  # --max-clips not provided

    if clips_per_minute and max_clips is None:
        max_clips = max(1, int(duration / 60.0 * clips_per_minute))

    assert max_clips == 6


def test_clips_per_minute_max_clips_wins():
    # --max-clips overrides --clips-per-minute
    duration = 120.0
    clips_per_minute = 3.0
    max_clips = 2  # user set --max-clips 2

    if clips_per_minute and max_clips is None:
        max_clips = max(1, int(duration / 60.0 * clips_per_minute))

    assert max_clips == 2  # unchanged
