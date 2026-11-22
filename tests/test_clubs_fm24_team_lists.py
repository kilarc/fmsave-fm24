"""FM24 team-list anchors: a run of 1.0 floats in a small club record."""

from dataclasses import replace

from fmsave._layouts import fm24_24_4_2
from fmsave.readers.clubs import _read_team_list

LAYOUT = fm24_24_4_2.TEAM_LISTS

# Bytes as a small FM24 club record stores them: three 1.0 floats in a row, then the two entry
# counts, filler, and the team list (4198, 33963, 33964). Read from the first float, the bytes
# instead parse as a one-team list naming 19451, a team another club stores.
_TAIL = bytes.fromhex(
    "0000803f0000803f0000803f"
    "00005e01fb4b000000000003"
    "66100000ab840000ac840000"
    "0000000000000000"
)
_RECORD = bytes(100) + _TAIL + bytes(16)


def test_fm24_reads_the_list_after_the_last_repeated_float_anchor() -> None:
    team_list = _read_team_list(_RECORD, 0, len(_RECORD), LAYOUT)
    assert team_list.team_ids == (4198, 33963, 33964)


def test_without_the_flag_the_first_float_anchor_is_used() -> None:
    layout = replace(LAYOUT, skip_repeated_float_anchors=0)
    team_list = _read_team_list(_RECORD, 0, len(_RECORD), layout)
    assert team_list.team_ids == (19451,)


def test_fm24_layout_sets_the_team_list_flags() -> None:
    assert LAYOUT.clip_at_unaccepted_records == 1
    assert LAYOUT.skip_repeated_float_anchors == 1
    assert LAYOUT.near_one_float_anchors == 1


# Manchester City's record in a 2024 career save: the anchor float drifted to 1.0101
# (3b 4c 81 3f), so no exact 1.0 exists, and the list (509, 29284, 29285) follows it.
_DRIFTED = bytes.fromhex(
    "1b443997" "4a3f4c8a" "3e3f"
    "3b4c813f"
    "000000000000000000000003"
    "fd010000" "64720000" "65720000"
    "00000000"
)
_DRIFTED_RECORD = bytes(100) + _DRIFTED + bytes(16)


def test_fm24_falls_back_to_a_float_anchor_near_one() -> None:
    team_list = _read_team_list(_DRIFTED_RECORD, 0, len(_DRIFTED_RECORD), LAYOUT)
    assert team_list.team_ids == (509, 29284, 29285)


def test_without_the_fallback_a_drifted_anchor_finds_no_list() -> None:
    layout = replace(LAYOUT, near_one_float_anchors=0)
    team_list = _read_team_list(_DRIFTED_RECORD, 0, len(_DRIFTED_RECORD), layout)
    assert team_list.team_ids == ()
