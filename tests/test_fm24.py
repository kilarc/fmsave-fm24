from __future__ import annotations

import struct
from datetime import date
from types import SimpleNamespace

import pytest

from fmsave import _version
from fmsave._errors import ReaderCheckError, UnsupportedGameError
from fmsave._layouts import PlayerRecordLayout, find_layout
from fmsave._layouts import fm24_24_4_2 as fm24
from fmsave._layouts import fm26_26_3_2 as fm26
from fmsave.readers.injuries import walk_injury_manager
from fmsave.readers.player_scan import locate_player_records
from fmsave.readers.team_match_stats import index_entries


def test_plain_fm24_writer_version_is_length_bound() -> None:
    data = b"\x00" * 8 + struct.pack("<I", 6) + b"24.4.2"
    version = _version.find_game_version(data, fm26.SAVE_SUMMARY, "example.fm")
    assert (version.major, version.build, version.build_number) == (24, "24.4.2", 0)
    with pytest.raises(UnsupportedGameError):
        _version.find_game_version(
            data.replace(b"24.4.2", b"23.4.2"), fm26.SAVE_SUMMARY, "example.fm"
        )
    with pytest.raises(UnsupportedGameError):
        _version.find_game_version(
            data[:8] + struct.pack("<I", 5) + b"24.4.2", fm26.SAVE_SUMMARY, "example.fm"
        )


def test_fm24_metadata_uses_the_database_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    head = bytearray(64)
    struct.pack_into("<I", head, 16, 4)
    head[20:24] = b"2430"
    struct.pack_into("<HH", head, 36, 32, 2030)
    info = b"\0" * 8 + struct.pack("<I", 8) + b"24.3.0+0"
    monkeypatch.setattr(_version, "read_metadata_section", lambda *_: info)
    monkeypatch.setattr(_version, "read_section_heads", lambda *_: {"game_db": bytes(head)})
    facts = _version.read_game_info_facts(
        SimpleNamespace(file_name="example.fm"),  # type: ignore[arg-type]
        {"game_db": 3569},
        _version.GameVersion(24, "24.4.2", 0),
        False,
    )
    assert facts.game_date == date(2030, 2, 1)
    with pytest.raises(UnsupportedGameError):
        _version.read_game_info_facts(
            SimpleNamespace(file_name="example.fm"),  # type: ignore[arg-type]
            {"game_db": 4000},
            _version.GameVersion(24, "24.4.2", 0),
            False,
        )


@pytest.mark.parametrize("build", ["24.3.0", "24.4.2", "24.4.2+0"])
def test_fm24_never_borrows_fm26_by_shared_schema(build: str) -> None:
    selected = find_layout(PlayerRecordLayout, "game_db", 3569, build)
    assert selected.layout is fm24.PLAYER_RECORDS
    assert (
        find_layout(PlayerRecordLayout, "game_db", 4000, fm26.BUILD).layout is fm26.PLAYER_RECORDS
    )


def test_fm24_player_scan_reads_shifted_fields_and_non_null_date() -> None:
    data = bytearray(400)
    r = 64
    struct.pack_into("<III", data, r - 19, 6, 1001, 1001)
    data[r - 7] = 2
    struct.pack_into("<HHHHh", data, r - 6, 3000, 4000, 5000, 156, 174)
    data[r + 8] = 20
    struct.pack_into("<I", data, r + 15, 91)
    data[r + 23 : r + 38] = bytes([1, 1, 1, 1, 1, 1, 1, 20, 1, 1, 1, 1, 1, 1, 1])
    data[r + 38 : r + 92] = bytes([60] * 54)
    struct.pack_into("<I", data, r + 92, 450_000)
    struct.pack_into("<HH", data, r + 97, 1, 2024)
    struct.pack_into("<HH", data, r + 101, 2, 2025)
    struct.pack_into("<H", data, r + 105, 9000)
    struct.pack_into("<H", data, r + 109, 9800)
    data[r + 122] = 188
    records = locate_player_records(bytes(data), 0, fm24.PLAYER_RECORDS, "example.fm")
    assert list(records.uids) == [1001]
    assert list(records.pindexes) == [6]
    assert list(records.record_offsets) == [r]
    assert records.markerless_count == 1


def test_fm24_injury_arrays_require_an_exact_end() -> None:
    data = bytearray(12)
    for _ in range(4):
        data.extend(struct.pack("<I", 0))
    data.extend(struct.pack("<I", 0))
    data.extend(struct.pack("<III", 2, 31, 32))
    data.extend(struct.pack("<I", 0))
    result = walk_injury_manager(bytes(data), fm24.INJURY_MANAGER, "example.fm")
    assert result.list_entries == (0, 2, 0)
    with pytest.raises(ReaderCheckError):
        walk_injury_manager(bytes(data) + b"\x99", fm24.INJURY_MANAGER, "example.fm")
    with pytest.raises(ReaderCheckError):
        walk_injury_manager(bytes(data), fm26.INJURY_MANAGER, "example.fm")


def test_fm24_empty_report_page_tail_is_explicit() -> None:
    # A declared zero-page store cannot smuggle additional records in its tail.
    section = bytearray(18)
    section.extend(b"\x01")
    assert (
        index_entries(bytes(section), fm24.MATCH_REPORTS, "example.fm", check_borrowed=True) == ()
    )
    with pytest.raises(ReaderCheckError):
        index_entries(bytes(section), fm26.MATCH_REPORTS, "example.fm", check_borrowed=True)
    with pytest.raises(ReaderCheckError):
        index_entries(
            bytes(section) + b"\x00", fm24.MATCH_REPORTS, "example.fm", check_borrowed=True
        )
