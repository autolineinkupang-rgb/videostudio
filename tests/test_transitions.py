import sys, os
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


def test_empty_transitions_list_raises():
    try:
        transitions.concat_with_transitions(
            clips=["a.mp4", "b.mp4"], out_path="out.mp4", transitions=[]
        )
        assert False, "Harus raise ValueError"
    except ValueError as e:
        assert "transitions" in str(e).lower()


def test_negative_td_raises():
    try:
        transitions.concat_with_transitions(
            clips=["a.mp4", "b.mp4"], out_path="out.mp4", transitions=["fade"], td=-1.0
        )
        assert False, "Harus raise ValueError"
    except ValueError:
        pass
