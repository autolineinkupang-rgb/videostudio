import sys, os
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
