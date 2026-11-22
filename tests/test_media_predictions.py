from __future__ import annotations

import struct

from fmsave.readers.predictions import block_competitions, scan_prediction_blocks


def _record(team_id: int, score: int, predicted: int, table: int, tail: int = 0) -> bytes:
    body = bytearray(struct.pack("<I", team_id) + b"\x00" + b"\xff" * 6)
    body += struct.pack("<I", 150000)
    body += struct.pack("<H", score)
    high = min(predicted + 1, 255)
    body += bytes([predicted, 0, 0, table, high, 0, 0, predicted, 0, predicted, 7])
    body += bytes(6)
    body += b"\x11" * (40 + tail)
    return bytes(body)


def _block(rules: str, teams: list[tuple[int, int, int, int]], tails: bool = False) -> bytes:
    name = rules.encode()
    head = b"elif\x01\x1a" + struct.pack("<I", len(name)) + name + b"\x00" * 12
    head += b"\x01\xa4\x00\x00\x00" + struct.pack("<I", len(teams)) + b"\x00"
    records = b"".join(
        _record(*team, tail=index * 3 if tails else 0) for index, team in enumerate(teams)
    )
    return head + records


def test_a_whole_block_gives_ranked_rows_and_its_rules_name() -> None:
    teams = [(101, 9000, 0, 2), (102, 8000, 1, 0), (103, 7000, 2, 1)]
    scan = scan_prediction_blocks(b"\x00" * 50 + _block("eng_prem", teams, tails=True))
    assert scan.rejected_blocks == 0
    assert len(scan.blocks) == 1
    block = scan.blocks[0]
    assert block.rules_name == "eng_prem"
    assert [(r.team_id, r.score, r.predicted, r.table_position) for r in block.records] == teams
    assert block.records[0].unknown["rank_high"] == 1


def test_a_record_without_the_opening_signature_is_still_read_at_the_block_stride() -> None:
    teams = [(100 + index, 9000 - index, index, (index + 1) % 5) for index in range(5)]
    block = bytearray(_block("eng_prem", teams))
    record_bytes = len(_record(0, 0, 0, 0))
    third_record = len(block) - 3 * record_bytes
    block[third_record + 4] = 1  # the zero byte after the team id
    scan = scan_prediction_blocks(bytes(block))
    assert scan.rejected_blocks == 0
    assert [(r.team_id, r.predicted) for r in scan.blocks[0].records] == [
        (100 + index, index) for index in range(5)
    ]


def test_a_block_without_a_prediction_is_skipped_quietly() -> None:
    teams = [(101, 9000, 255, 0), (102, 8000, 255, 1)]
    scan = scan_prediction_blocks(_block("cup", teams))
    assert scan.blocks == ()
    assert scan.blocks_without_prediction == 1
    assert scan.rejected_blocks == 0


def test_ranks_that_are_not_a_permutation_reject_the_block() -> None:
    teams = [(101, 9000, 0, 0), (102, 8000, 0, 1)]
    scan = scan_prediction_blocks(_block("x", teams))
    assert scan.blocks == ()
    assert scan.rejected_blocks == 1


def test_competition_is_the_one_whose_fixtures_pair_the_teams() -> None:
    teams = [(101, 9000, 0, 0), (102, 8000, 1, 1), (103, 7000, 2, 2)]
    scan = scan_prediction_blocks(_block("eng_prem", teams))
    pairs = [(101, 102, 7, None), (102, 103, 7, None), (101, 103, 50, "Cup"), (101, 999, 50, "Cup")]
    assert block_competitions(scan.blocks, pairs) == [(7, None)]
    assert block_competitions(scan.blocks, []) == [(None, None)]
