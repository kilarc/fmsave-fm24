from __future__ import annotations

import struct

from fmsave._layouts import fm24_24_4_2
from fmsave.readers.tactics import _read_single_slot_block

LAYOUT = fm24_24_4_2.TACTICS


def _unit(head: int) -> bytes:
    # Two prefix bytes, then the FM26 unit shape two bytes shorter: lead, head byte, a 7-byte
    # field, the separator and 10 bytes.
    return b"\x00\x00" + LAYOUT.unit_lead + bytes([head]) + bytes(7) + b"\xff" + bytes(10)


def _block(mask: int, heads: list[int]) -> bytes:
    body = LAYOUT.slot_tag + struct.pack("<I", mask) + bytes(8) + b"\x01\x01"
    body += struct.pack("<I", len(heads)) + bytes(6)
    return body + b"".join(_unit(head) for head in heads)


def test_fm24_slot_block_reads_its_only_block_as_the_in_possession_half() -> None:
    data = _block(1, [3, 4]) + _block(4, [])
    assert len(_unit(0)) == LAYOUT.unit_bytes
    read = _read_single_slot_block(data, 0, len(data), 0, LAYOUT)
    assert read is not None
    slot, end, separators = read
    assert end == 27 + 2 * LAYOUT.unit_bytes
    assert data.startswith(LAYOUT.slot_tag, end)
    assert slot.in_possession_mask == 1
    assert slot.in_possession_setting_count == 2
    assert [unit.head_byte for unit in slot.in_possession_settings] == [3, 4]
    assert slot.out_of_possession_mask is None
    assert slot.out_of_possession_setting_count is None
    assert slot.out_of_possession_settings == ()
    assert separators == ()


def test_fm24_slot_block_that_runs_past_its_record_is_not_read() -> None:
    data = _block(1, [3, 4])
    assert _read_single_slot_block(data, 0, len(data) - 1, 0, LAYOUT) is None
    assert _read_single_slot_block(b"\x00" + data, 0, len(data) + 1, 0, LAYOUT) is None
