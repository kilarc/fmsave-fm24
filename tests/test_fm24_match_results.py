import struct

from fmsave.readers.fm24_archives import match_result_block

_MARKER = b"\xe0\x1f\x88\x3b"


def _block(report_id, home, away, home_extra=b"\xff\xff\xff", away_extra=b"\xff\xff\xff",
           attendance=23339, away_fans=2105, zeros=5):
    return (
        _MARKER + b"\x00\x00" + b"\xff" * 16 + b"\x00" * zeros + b"\x01"
        + bytes([home]) + home_extra + bytes([away]) + away_extra
        + struct.pack("<III", report_id, attendance, away_fans) + b"\x00" * 16
    )


def test_reads_normal_time_score_attendance_and_away_fans():
    report = b"\x00" * 300 + _block(6445, 2, 1)
    assert match_result_block(report, 6445) == (2, 1, 23339, 2105, (None,) * 3, (None,) * 3)


def test_extra_time_goals_sit_in_the_first_extra_byte():
    report = b"\x00" * 300 + _block(704, 0, 0, b"\x01\xff\xff", b"\x00\xff\xff", 10189, 366)
    home_goals, away_goals, _, _, home_extra, away_extra = match_result_block(report, 704)
    assert (home_goals, away_goals) == (0, 0)
    assert (home_extra[0], away_extra[0]) == (1, 0)


def test_small_report_id_is_not_found_inside_the_ff_run():
    # 255 spells ff 00 00 00, which also occurs where the 0xFF run meets the zeros.
    report = b"\x00" * 300 + _block(255, 1, 1, attendance=7924, away_fans=175)
    assert match_result_block(report, 255)[:4] == (1, 1, 7924, 175)


def test_result_under_a_later_marker():
    first = _MARKER + b"\x00\x00" + b"\xff" * 16 + b"\x00" * 60
    report = b"\x00" * 270 + first + _block(2791, 3, 0)
    assert match_result_block(report, 2791)[:2] == (3, 0)


def test_no_block_gives_none():
    assert match_result_block(b"\x00" * 400 + _MARKER + b"\x00" * 200, 99) is None
