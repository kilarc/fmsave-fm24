"""Reading the per-league team blocks that hold the pre-season media prediction (FM24).

A league's block sits in the unnamed span: a tagged header that names the competition's rules
file, the bytes `01 a4 00 00 00`, a u32 team count and one pad byte, then one record per team.
A record opens with the u32 team id, a zero byte and six 0xff bytes; the fields this reader
ships sit at fixed offsets from that id. Records are not all one length, so each next record
is found by its opening signature inside a bounded window.

The walk is its own check: a block counts only when every record is found and both the
predicted rank and the table position are each a permutation of 0..n-1. A competition that
stores no prediction holds 255 in every predicted-rank byte and is skipped without error.
"""

from __future__ import annotations

import re
import struct
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

_HEAD = b"\x01\xa4\x00\x00\x00"
_HEAD_BYTES = len(_HEAD) + 4 + 1
_RECORD = re.compile(rb"(?s)....\x00\xff\xff\xff\xff\xff\xff")
_NO_RANK = 255
_MAX_TEAMS = 400
_FIELDS_BYTES = 33
_NEXT_RECORD_WINDOW = 8192
_HEADER_LOOKBACK = 600
_RULES_TAG = b"elif\x01\x1a"
_SCORE = struct.Struct("<H")
_UINT32 = struct.Struct("<I")

_SCORE_OFFSET = 15
_RANK_LOW_OFFSET = 17
_TABLE_POSITION_OFFSET = 20
_RANK_HIGH_OFFSET = 21
_PREDICTED_OFFSET = 24
_RANK_GROUP_OFFSET = 26
_RANK_27_OFFSET = 27


@dataclass(frozen=True, slots=True)
class RawPrediction:
    team_id: int
    score: int
    predicted: int
    table_position: int
    unknown: Mapping[str, int]


@dataclass(frozen=True, slots=True)
class RawPredictionBlock:
    rules_name: str | None
    records: tuple[RawPrediction, ...]


@dataclass(frozen=True, slots=True)
class PredictionScan:
    blocks: tuple[RawPredictionBlock, ...]
    blocks_without_prediction: int
    rejected_blocks: int


def _rules_name(span: bytes, head_at: int) -> str | None:
    start = max(0, head_at - _HEADER_LOOKBACK)
    tag_at = span.rfind(_RULES_TAG, start, head_at)
    if tag_at < 0:
        return None
    length_at = tag_at + len(_RULES_TAG)
    (length,) = _UINT32.unpack_from(span, length_at)
    text_at = length_at + _UINT32.size
    if length == 0 or text_at + length > head_at:
        return None
    raw = span[text_at : text_at + length]
    if not raw.isascii() or not raw.replace(b"_", b"").isalnum():
        return None
    return raw.decode("ascii")


def _signature_starts(span: bytes, first: int, count: int) -> list[int]:
    """The records that open with the signature, each found inside a window past the last."""
    found = [first]
    at = first
    while len(found) < count:
        match = _RECORD.search(span, at + _FIELDS_BYTES, at + _NEXT_RECORD_WINDOW)
        if match is None:
            break
        at = match.start()
        found.append(at)
    return found


def _stride_starts(span: bytes, first: int, count: int, found: list[int]) -> list[int] | None:
    """`count` records of one length from `first`, when one of them lacks the signature.

    The length is the smallest gap between records that do open with the signature, and every
    one of them inside the block must sit a whole number of records from the first.
    """
    if len(found) < 2:
        return None
    stride = min(found[index + 1] - found[index] for index in range(len(found) - 1))
    block_end = first + count * stride
    if any((start - first) % stride for start in found if start < block_end):
        return None
    starts = [first + index * stride for index in range(count)]
    if starts[-1] + _FIELDS_BYTES > len(span):
        return None
    return starts


def _record_starts(span: bytes, first: int, count: int) -> list[int] | None:
    found = _signature_starts(span, first, count)
    if len(found) == count:
        return found if found[-1] + _FIELDS_BYTES <= len(span) else None
    return _stride_starts(span, first, count, found)


def scan_prediction_blocks(span: bytes) -> PredictionScan:
    """Every league team block whose predicted ranks are a whole permutation."""
    blocks: list[RawPredictionBlock] = []
    without = 0
    rejected = 0
    head_at = span.find(_HEAD)
    while head_at >= 0:
        first = head_at + _HEAD_BYTES
        if first + _FIELDS_BYTES <= len(span):
            (count,) = _UINT32.unpack_from(span, head_at + len(_HEAD))
            if 2 <= count <= _MAX_TEAMS and _RECORD.match(span, first):
                found = _signature_starts(span, first, count)
                # Only a record that opens with the signature is surely a record, so only its
                # rank byte says whether this block stores a prediction at all.
                stores_prediction = any(
                    at + _FIELDS_BYTES <= len(span) and span[at + _PREDICTED_OFFSET] != _NO_RANK
                    for at in found
                )
                starts = _record_starts(span, first, count)
                if starts is None:
                    rejected += stores_prediction
                    without += not stores_prediction
                else:
                    predicted = [span[at + _PREDICTED_OFFSET] for at in starts]
                    table = [span[at + _TABLE_POSITION_OFFSET] for at in starts]
                    every_rank = list(range(count))
                    if all(rank == _NO_RANK for rank in predicted) or not stores_prediction:
                        without += 1
                    elif sorted(predicted) != every_rank or sorted(table) != every_rank:
                        rejected += 1
                    else:
                        blocks.append(
                            RawPredictionBlock(
                                _rules_name(span, head_at),
                                tuple(_raw_record(span, at) for at in starts),
                            )
                        )
        head_at = span.find(_HEAD, head_at + 1)
    return PredictionScan(tuple(blocks), without, rejected)


def _raw_record(span: bytes, at: int) -> RawPrediction:
    return RawPrediction(
        team_id=_UINT32.unpack_from(span, at)[0],
        score=_SCORE.unpack_from(span, at + _SCORE_OFFSET)[0],
        predicted=span[at + _PREDICTED_OFFSET],
        table_position=span[at + _TABLE_POSITION_OFFSET],
        unknown={
            "rank_low": span[at + _RANK_LOW_OFFSET],
            "rank_high": span[at + _RANK_HIGH_OFFSET],
            "rank_group": span[at + _RANK_GROUP_OFFSET],
            "rank_27": span[at + _RANK_27_OFFSET],
        },
    )


def block_competitions(
    blocks: Iterable[RawPredictionBlock],
    fixture_pairs: Iterable[tuple[int, int, int | None, str | None]],
) -> list[tuple[int | None, str | None]]:
    """For each block, the competition whose fixtures pair two of its teams most often.

    `fixture_pairs` is (home team, away team, competition id, competition name). A block with
    no such fixture, or whose leading competition holds no more than half of them, has none.
    """
    blocks = list(blocks)
    by_team: dict[int, list[int]] = {}
    for index, block in enumerate(blocks):
        for record in block.records:
            by_team.setdefault(record.team_id, []).append(index)
    votes: list[Counter[int]] = [Counter() for _ in blocks]
    names: dict[int, str | None] = {}
    for home, away, competition_id, competition_name in fixture_pairs:
        if competition_id is None:
            continue
        shared = set(by_team.get(home, ())) & set(by_team.get(away, ()))
        for index in shared:
            votes[index][competition_id] += 1
        if competition_name is not None or competition_id not in names:
            names[competition_id] = competition_name
    result: list[tuple[int | None, str | None]] = []
    for counter in votes:
        total = sum(counter.values())
        if not total:
            result.append((None, None))
            continue
        competition_id, count = counter.most_common(1)[0]
        if count * 2 <= total:
            result.append((None, None))
        else:
            result.append((competition_id, names.get(competition_id)))
    return result
