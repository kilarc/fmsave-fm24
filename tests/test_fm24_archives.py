import struct
from contextlib import nullcontext
from datetime import date
from types import SimpleNamespace

import pytest

from fmsave._errors import ReaderCheckError, UnsupportedGameError
from fmsave.readers import fm24_archives as ar


def stub(sections=None, **attrs):
    sections = sections or {}
    return SimpleNamespace(
        info=SimpleNamespace(build="24.4.2", file_name="example", game_date=date(2024, 1, 1)),
        _read_section=sections.__getitem__,
        **attrs,
    )


def words(*values):
    return struct.pack(f"<{len(values)}I", *values)


def test_index_preserves_anonymous_rows_and_binds_list():
    data = ar._POOL_HEAD + b"\x02\x00" + bytes(3 * 16)
    # Single at 32, list with slots at 0 and 16.
    index = ar._INDEX_HEAD + words(1, 32, 1, 2, 0, 16, 0, 16) + b"\x02\x00"
    save = stub({"x_dt": data, "x_ls": index})
    assert ar._pool(save, "x", 2, 16)[1:] == ([0, 0, -1], 1)


@pytest.mark.parametrize("offset", [1, 16, 48])
def test_corrupt_offsets_cannot_attribute_other_rows(offset):
    data = ar._POOL_HEAD + b"\x02\x00" + bytes(3 * 16)
    index = ar._INDEX_HEAD + words(1, offset, 1, 2, 0, 16, 0, 16) + b"\x02\x00"
    with pytest.raises(ReaderCheckError):
        ar._pool(stub({"x_dt": data, "x_ls": index}), "x", 2, 16)


def test_injury_same_day_collision_keeps_duration_but_does_not_assign_match(monkeypatch):
    raw_day = struct.pack("<HH", 1, 2024)
    records = b"".join(ar._INJURY.pack(13, 7, 1, 2, raw_day, days, 0, 0) for days in (7, 21))
    monkeypatch.setattr(ar, "_pool", lambda *args: (bytes(8) + records, [0, 0], 1))
    monkeypatch.setattr(ar, "_player_history_owners", lambda *args: {0: 42})
    event = SimpleNamespace(kind="history", player_uid=42, date=date(2024, 1, 1))
    save = stub(players=lambda: [], injury_types=lambda: [], injuries=lambda: [event])
    result = ar.injury_episodes(save)
    assert [(x.player_uid, x.duration_days, x.end_from_duration, x.log_cause) for x in result] == [
        (42, 7, date(2024, 1, 8), None),
        (42, 21, date(2024, 1, 22), None),
    ]


def test_season_history_requires_unique_group_and_team():
    def run(team, group):
        block = bytearray(155)
        for at in (0, 27, 54, 67):
            struct.pack_into("<I", block, at, team)
        block[141:143] = b"\xff\xff"
        struct.pack_into("<I", block, 147, group)
        return block

    blob = run(1, 2) + run(7, 3) + run(8, 3) + run(9, 4) + run(9, 5)
    assert ar._league_history_owners(blob, 7, {1, 7, 8, 9}) == {2: 1}


def test_counted_loan_group_extends_only_an_unambiguous_owner():
    def row(amount):
        return b"\x01" + struct.pack("<iiiiHHBBBHH", amount, 100, 2, 3, 1, 2030, 1, 1, 0, 1, 2020)

    loan = ar.StartingLoan(42, 7, 17, "club", 1, 1000, date(2020, 1, 1), date(2030, 1, 1), None)

    def read(db):
        return ar.matched_live_loans(
            stub(
                starting_loan_terms=lambda: [loan],
                _context=SimpleNamespace(section=lambda _: nullcontext(db)),
            )
        )

    good = read(words(2) + row(1000) + row(1375))
    assert [(r.original_amount, r.starting_record_id, r.owner_source) for r in good] == [
        (1000, 42, "opening_terms_match"),
        (1375, None, "same_counted_loan_list"),
    ]
    assert len(read(words(3) + row(1000) + row(1375))) == 1
    assert not read(words(2) + row(1000) + row(1000))


def test_transfer_fields_are_bounded_and_keep_free_transfer_zero():
    raw = ar._TRANSFER_MARKER + words(2) + b"ab" + words(12, 0, 1750) + b"\x01"
    assert ar.last_transfer_record(raw, 0, len(raw), 9, "p") == ar.LastTransfer(9, "p", 0, 1750)
    assert ar.last_transfer_record(raw, 0, len(raw) - 1, 9, "p") is None


def test_build_gate():
    with pytest.raises(UnsupportedGameError):
        ar.starting_loans(SimpleNamespace(info=SimpleNamespace(build="27.0.0")))


def test_injury_keys_preserve_selector_and_csv_order(monkeypatch):
    records = SimpleNamespace(
        position_by_pindex={4: 0, 9: 1}, uids=(501, 999), ambiguous_positions={1}
    )
    save = stub(
        {"injury_manager": words(10, 5)}, _context=SimpleNamespace(player_records=lambda: records)
    )
    save.info.section_schemas = {}
    layout = SimpleNamespace(
        log_array_index=0, typed_array_index=1, array_strides=(4, 4), arrays_offset=0
    )
    walk = SimpleNamespace(
        log_offset=0, log_rows=1, typed_offset=4, typed_rows=1, window_a_rows=0, window_b_rows=0
    )
    fields = SimpleNamespace(fields_struct=struct.Struct("<I"), selector_index=0)
    monkeypatch.setattr(ar, "find_injury_manager_layout", lambda *args: layout)
    monkeypatch.setattr(ar, "walk_injury_manager", lambda *args: walk)
    monkeypatch.setattr(ar, "_log_row_fields", lambda _: fields)
    monkeypatch.setattr(ar, "_typed_row_fields", lambda _: fields)
    assert list(ar.injury_link_keys(save)) == [
        ar.InjuryLinkKey("roster", None, 5, 501),
        ar.InjuryLinkKey("history", 0, 10, None),
        ar.InjuryLinkKey("typed", 1, 5, 501),
    ]
