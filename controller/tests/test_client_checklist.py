"""client/checklist.py: step 4's rows (web-ui.md § 4, Q3 resolved) from the prefs file."""

from datetime import UTC, datetime

import pytest

from contract import assert_schema
from spotivault.client.checklist import ROWS, ROWS_BY_ID, auto_state, build_checklist, drifted

T0 = datetime(2026, 11, 15, 9, 20, tzinfo=UTC)

# The prefs of a client set up as step 4 asks (FINDINGS row 26).
GOOD = {
    "audio.allow_downgrade": "false",
    "audio.automix": "false",
    "audio.normalize_v2": "false",
    "audio.play_bitrate_enumeration": "4",
    "audio.crossfade_migrated_to_ps": "true",
    "audio.gapless_migrated_to_ps": "true",
}
TICKED = {"crossfade": True, "gapless": True, "autoplay": True}


def test_the_rows_follow_web_ui_md() -> None:
    assert [(r.id, r.section, r.check, r.blocker) for r in ROWS] == [
        ("crossfade", "playback", "confirm", True),
        ("gapless", "playback", "confirm", True),
        ("automix", "playback", "auto", True),
        ("autoplay", "playback", "confirm", False),
        ("normalization", "playback", "auto", True),
        ("equalizer", "playback", "auto", True),
        ("mono", "playback", "auto", True),
        ("streaming_quality", "audio_quality", "auto", True),
        ("auto_adjust_quality", "audio_quality", "auto", True),
        ("volume", "player", "set_for_you", False),
    ]
    assert {r.id: r.pref_key for r in ROWS if r.check == "auto"} == {
        "automix": "audio.automix",
        "normalization": "audio.normalize_v2",
        "equalizer": "audio.equalizer_v2",
        "mono": "audio.downmixer_v2",
        "streaming_quality": "audio.play_bitrate_enumeration",
        "auto_adjust_quality": "audio.allow_downgrade",
    }


@pytest.mark.parametrize(
    ("row", "prefs", "state"),
    [
        ("automix", GOOD, "ok"),
        ("automix", {**GOOD, "audio.automix": "true"}, "needs_change"),
        ("automix", {}, "needs_change"),  # missing: at its default, which is on
        ("automix", {"audio.automix": "maybe"}, "unknown"),
        ("automix", None, "unknown"),  # no prefs file
        ("normalization", {}, "needs_change"),
        ("auto_adjust_quality", {}, "needs_change"),
        ("auto_adjust_quality", {"audio.allow_downgrade": "FALSE"}, "ok"),
        ("equalizer", {}, "ok"),  # missing: off (the client drops the key when it's turned off)
        ("equalizer", {"audio.equalizer_v2": "true"}, "needs_change"),
        ("equalizer", {"audio.equalizer_v2": "false"}, "ok"),
        ("mono", {}, "ok"),
        ("mono", {"audio.downmixer_v2": "true"}, "needs_change"),
        ("streaming_quality", GOOD, "ok"),
        ("streaming_quality", {"audio.play_bitrate_enumeration": "3"}, "needs_change"),
        ("streaming_quality", {}, "needs_change"),  # missing: Automatic
        ("streaming_quality", {"audio.play_bitrate_enumeration": "high"}, "unknown"),
    ],
)
def test_auto_rows(row: str, prefs: dict[str, str] | None, state: str) -> None:
    assert auto_state(ROWS_BY_ID[row], prefs) == state


def test_a_set_up_client_is_ready() -> None:
    checklist = build_checklist(GOOD, TICKED, T0)
    assert_schema("Checklist", checklist.model_dump(mode="json"))
    assert checklist.ready
    assert checklist.checked_at == T0
    states = {row.id: (row.state, row.confirmed) for row in checklist.rows}
    assert states == {
        "crossfade": (None, True),
        "gapless": (None, True),
        "automix": ("ok", None),
        "autoplay": (None, True),
        "normalization": ("ok", None),
        "equalizer": ("ok", None),
        "mono": ("ok", None),
        "streaming_quality": ("ok", None),
        "auto_adjust_quality": ("ok", None),
        "volume": (None, None),
    }
    assert drifted(checklist) == []


def test_autoplay_isnt_a_blocker() -> None:
    assert build_checklist(GOOD, {"crossfade": True, "gapless": True}, T0).ready


def test_an_unticked_confirm_row_blocks() -> None:
    checklist = build_checklist(GOOD, {"crossfade": True}, T0)
    assert not checklist.ready
    assert drifted(checklist) == []  # the pre-run check only re-reads Auto rows


def test_a_changed_setting_blocks_and_drifts() -> None:
    prefs = {**GOOD, "audio.normalize_v2": "true", "audio.equalizer_v2": "true"}
    checklist = build_checklist(prefs, TICKED, T0)
    assert not checklist.ready
    assert [row.id for row in drifted(checklist)] == ["normalization", "equalizer"]


def test_no_prefs_file_is_unknown_and_not_ready() -> None:
    checklist = build_checklist(None, {}, T0)
    assert_schema("Checklist", checklist.model_dump(mode="json"))
    assert not checklist.ready
    assert {row.state for row in checklist.rows if row.check == "auto"} == {"unknown"}
    assert {row.confirmed for row in checklist.rows if row.check == "confirm"} == {False}
