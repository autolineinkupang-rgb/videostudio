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
