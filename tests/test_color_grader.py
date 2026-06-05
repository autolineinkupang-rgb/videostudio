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
