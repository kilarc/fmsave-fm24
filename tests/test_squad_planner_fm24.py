from __future__ import annotations

import struct

import pytest

import fmsave
from fmsave._layouts import SquadPlannerLayout, find_layout, fm24_24_4_2
from fmsave.readers.squad_planner import find_squad_planner_layout, read_owner_planner_selectors

LAYOUT = fm24_24_4_2.SQUAD_PLANNER


def _planner(first_slots: dict[tuple[int, int], tuple[int, ...]]) -> bytes:
    """Four groups of three sets of 27 counted slots, FM24's planner shape."""
    body = bytearray(LAYOUT.lead_tail)
    for group in range(4):
        for set_index, marker in enumerate(
            (LAYOUT.group_marker, LAYOUT.set_marker, LAYOUT.set_marker)
        ):
            body += marker
            for slot in range(27):
                selectors = first_slots.get((group, slot), ()) if set_index == 0 else ()
                body.append(len(selectors))
                body += struct.pack(f"<{len(selectors)}I", *selectors)
    return bytes(body)


def test_fm24_registers_one_planner_layout_stored_after_its_owner() -> None:
    match = find_squad_planner_layout("FM24", None, "24.4.2")
    assert match.layout is LAYOUT
    assert match.layout.owner_window_bytes is not None
    assert find_layout(SquadPlannerLayout, "humans", None, "24.4.2").layout is LAYOUT


def test_fm24_planner_reads_first_sets_in_depth_order() -> None:
    game_db = b"\x00" * 100 + _planner({(0, 0): (5, 9, 7), (2, 26): (3,), (3, 1): (4,)})
    groups = read_owner_planner_selectors(game_db, 40, LAYOUT, "x.fm")
    assert groups is not None
    assert len(groups) == 3
    assert groups[0][0] == (5, 9, 7)
    assert groups[2][26] == (3,)
    assert all(len(slots) == 27 for slots in groups)


def test_fm24_planner_outside_the_owner_window_is_not_found() -> None:
    assert LAYOUT.owner_window_bytes is not None
    game_db = b"\x00" * (LAYOUT.owner_window_bytes + 10) + _planner({})
    assert read_owner_planner_selectors(game_db, 0, LAYOUT, "x.fm") is None


def test_fm24_planner_lead_without_a_whole_walk_is_skipped() -> None:
    broken = LAYOUT.lead_tail + LAYOUT.group_marker + b"\x01"
    game_db = broken + b"\x00" * 8 + _planner({(1, 4): (11,)})
    groups = read_owner_planner_selectors(game_db, 0, LAYOUT, "x.fm")
    assert groups is not None
    assert groups[1][4] == (11,)


def test_two_whole_fm24_planners_are_ambiguous() -> None:
    game_db = _planner({}) + _planner({})
    with pytest.raises(fmsave.ReaderCheckError, match="ambiguous"):
        read_owner_planner_selectors(game_db, 0, LAYOUT, "x.fm")
