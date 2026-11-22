"""Additional offline archives present in Football Manager 24.4.2."""

from __future__ import annotations

import re
import struct
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from datetime import date, time, timedelta
from typing import TYPE_CHECKING

from fmsave._errors import ReaderCheckError, UnsupportedGameError
from fmsave._scan import decode_date
from fmsave.readers.finances import find_finance_layouts, read_current_balance
from fmsave.readers.injuries import (
    _log_row_fields,
    _typed_row_fields,
    find_injury_manager_layout,
    walk_injury_manager,
)
from fmsave.readers.season_history import find_history_layout, walk_history_index
from fmsave.table import Table

if TYPE_CHECKING:
    from fmsave._save import Save

_WORD = struct.Struct("<I")
_SIGNED = struct.Struct("<i")
_MISSING = 0xFFFFFFFF
_INDEX_HEAD = b"\x03\x01tad.\x04\x00"
_POOL_HEAD = b"\x03\x01tmc."
_INJURY = struct.Struct("<HiBB4sHBB")
_RANK = struct.Struct("<HHBBHiBBBBBBHHH")
# Following the injury archive selector, there are three six-byte records.
_PLAYER_LIST = re.compile(rb"\x03\x00\x00\x00\x01.{5}\x01.{5}\x01.{5}", re.DOTALL)


def _check_build(save: Save) -> None:
    if save.info.build != "24.4.2":
        raise UnsupportedGameError("These archive readers cover FM24 24.4.2 only.")


def _pool(save: Save, stem: str, schema: int, stride: int):
    data = save._read_section(stem + "_dt")
    index = save._read_section(stem + "_ls")
    if not data.startswith(_POOL_HEAD + struct.pack("<H", schema)) or (len(data) - 8) % stride:
        raise ReaderCheckError(f"{stem}: unsupported archive header or record length")
    layout = replace(
        find_history_layout(save.info.build),
        index_header=_INDEX_HEAD,
        unit_bytes=stride,
        footer=struct.pack("<H", schema),
    )
    refs = walk_history_index(index, save.info.file_name, layout)
    count = (len(data) - 8) // stride
    owners = [-2] * count
    for group, offsets in enumerate((refs.singles, *refs.lists), start=-1):
        for offset in offsets:
            slot, remainder = divmod(offset, stride)
            if remainder or slot >= count or owners[slot] != -2:
                raise ReaderCheckError(f"{stem}: misaligned, overlapping or out-of-range reference")
            owners[slot] = group
    if -2 in owners:
        raise ReaderCheckError(f"{stem}: archive contains unaccounted records")
    return data, owners, len(refs.lists)


def _player_history_owners(save: Save, group_count: int) -> dict[int, int]:
    records = save._context.player_records()
    candidates: dict[int, list[int]] = defaultdict(list)
    ambiguous_groups: set[int] = set()
    with save._context.section("game_db") as db:
        for j, start in enumerate(records.record_offsets):
            end = records.record_offsets[j + 1] if j + 1 < len(records.record_offsets) else len(db)
            groups = []
            for match in _PLAYER_LIST.finditer(db, start + 184, min(end, start + 4096)):
                at = match.start() - 4
                if db[at - 1] or (
                    decode_date(db, at - 10) is None and db[at - 10 : at - 6] != b"\x01\0\x6c\x07"
                ):
                    continue
                group = _WORD.unpack_from(db, at)[0]
                if group < group_count or group == _MISSING:
                    groups.append(group)
            if j in records.ambiguous_positions or len(groups) != 1:
                ambiguous_groups.update(groups)
            elif groups[0] != _MISSING:
                candidates[groups[0]].append(records.uids[j])
    return {
        g: uids[0] for g, uids in candidates.items() if len(uids) == 1 and g not in ambiguous_groups
    }


@dataclass(frozen=True, slots=True)
class InjuryEpisode:
    archive_row: int
    history_group: int | None
    player_uid: int | None
    player_name: str | None
    onset_date: date | None
    duration_days: int
    end_from_duration: date | None
    end_after_save: bool | None
    type_id: int
    type_name: str | None
    archive_team_ref: int | None
    archive_cause_code: int
    archive_cause_category: str | None
    archive_side_code: int
    log_team_id: int | None
    log_club_uid: int | None
    log_cause: str | None
    log_severity: str | None


@dataclass(frozen=True, slots=True)
class InjuryLinkKey:
    kind: str
    injury_csv_row: int | None
    selector: int
    player_uid: int | None
    window_start: date | None = None
    window_end: date | None = None


def injury_link_keys(save: Save) -> Table[InjuryLinkKey]:
    """Same-career player selectors, including the original keys on orphaned injury logs."""
    _check_build(save)
    records = save._context.player_records()
    known = {
        pindex + 1: records.uids[pos]
        for pindex, pos in records.position_by_pindex.items()
        if pos not in records.ambiguous_positions
    }
    rows = [InjuryLinkKey("roster", None, selector, uid) for selector, uid in known.items()]
    section = save._read_section("injury_manager")
    layout = find_injury_manager_layout(
        save.info.section_schemas.get("injury_manager"), save.info.build
    )
    walk = walk_injury_manager(section, layout, save.info.file_name)
    # The first two arrays carry two dates and a person selector. Their precise
    # relationship to a particular injury is not established by this layout.
    cursor = layout.arrays_offset
    for index, count in enumerate((walk.window_a_rows, walk.window_b_rows)):
        cursor += 4
        stride = layout.array_strides[index]
        for i in range(count):
            at = cursor + stride * i
            start, end = decode_date(section, at + 1), decode_date(section, at + 5)
            if stride != 14 or section[at] != 1 or start is None or end is None or end < start:
                raise ReaderCheckError("Unsupported FM24 injury date window")
            selector = _WORD.unpack_from(section, at + 9)[0]
            rows.append(
                InjuryLinkKey(
                    ("window_a", "window_b")[index], None, selector, known.get(selector), start, end
                )
            )
        cursor += count * stride
    groups = (
        (
            "history",
            walk.log_offset,
            walk.log_rows,
            layout.log_array_index,
            _log_row_fields(layout),
        ),
        (
            "typed",
            walk.typed_offset,
            walk.typed_rows,
            layout.typed_array_index,
            _typed_row_fields(layout),
        ),
    )
    csv_row = 0
    for kind, start, count, array, fields in groups:
        for i in range(count):
            at = start + i * layout.array_strides[array]
            selector = fields.fields_struct.unpack_from(section, at)[fields.selector_index]
            rows.append(InjuryLinkKey(kind, csv_row, selector, known.get(selector)))
            csv_row += 1
    return Table(rows, InjuryLinkKey)


# Broad categories agree with each unambiguously matched contemporaneous event in M and L.
_CAUSE_CATEGORIES = {
    0: "in_training",
    1: "in_match",
    2: "in_match",
    3: "in_training",
    4: "in_match",
    5: "in_training",
}


def injury_episodes(save: Save) -> Table[InjuryEpisode]:
    _check_build(save)
    data, groups, group_count = _pool(save, "injury_histories", 2, _INJURY.size)
    owners = _player_history_owners(save, group_count)
    names = {r.uid: r.name for r in save.players()}
    types = {r.id: r.name for r in save.injury_types()}
    logs = defaultdict(list)
    for r in save.injuries():
        if r.kind == "history" and r.player_uid is not None and r.date:
            logs[r.player_uid, r.date].append(r)
    dates = [decode_date(data, at + 8) for at in range(8, len(data), _INJURY.size)]
    keys = [(owners.get(group), day) for group, day in zip(groups, dates)]
    multiplicity = Counter(keys)
    rows = []
    for i, (group, key) in enumerate(zip(groups, keys)):
        uid, day = key
        kind, team, cause, side, _, days, _, _ = _INJURY.unpack_from(data, 8 + i * _INJURY.size)
        end = day + timedelta(days=days) if day is not None else None
        matches = logs.get(key, ())
        log = matches[0] if len(matches) == 1 and multiplicity[key] == 1 else None
        rows.append(
            InjuryEpisode(
                i,
                group if group >= 0 else None,
                uid,
                names.get(uid),
                day,
                days,
                end,
                end > save.info.game_date if end and save.info.game_date else None,
                kind,
                types.get(kind),
                team if team >= 0 else None,
                cause,
                _CAUSE_CATEGORIES.get(cause),
                side,
                log.team_id if log else None,
                log.club_uid if log else None,
                log.cause.label.name.lower() if log and log.cause else None,
                log.severity.label.name.lower() if log and log.severity else None,
            )
        )
    return Table(rows, InjuryEpisode)


@dataclass(frozen=True, slots=True)
class StartingLoan:
    record_id: int
    team_id: int
    club_uid: int | None
    club_name: str | None
    type_code: int
    original_amount: int
    start_date: date | None
    end_date: date | None
    interest_rate_raw: float | None


def starting_loans(save: Save) -> Table[StartingLoan]:
    _check_build(save)
    data = save._read_section("starting_club_debt_db")
    if len(data) < 22 or not data.startswith(_POOL_HEAD + b"\xf1\x0d"):
        raise ReaderCheckError("Unsupported starting debt table")
    count = _WORD.unpack_from(data, 8)[0]
    if len(data) != 22 + 79 * count or _WORD.unpack_from(data, len(data) - 4)[0] != count:
        raise ReaderCheckError("Starting debt count or trailer mismatch")
    clubs = save._context.club_index()
    rows = []
    for idx in range(count):
        at = 12 + 79 * idx
        if _WORD.unpack_from(data, at + 68)[0] != idx:
            raise ReaderCheckError("Starting debt sequence mismatch")
        team, amount = struct.unpack_from("<ii", data, at + 2)
        code = data[at + 16]
        if not (1 <= code <= 15 and team >= 0 and amount > 0):
            continue
        start, end = decode_date(data, at + 21), decode_date(data, at + 25)
        owner = clubs.team_to_club.get(team)
        club = clubs.club_by_uid.get(owner[0]) if owner else None
        rate = struct.unpack_from("<f", data, at + 29)[0]
        rows.append(
            StartingLoan(
                idx,
                team,
                club.uid if club else None,
                club.name if club else None,
                code,
                amount,
                start,
                end,
                rate if 0 <= rate <= 100 else None,
            )
        )
    return Table(rows, StartingLoan)


@dataclass(frozen=True, slots=True)
class LiveLoan:
    starting_record_id: int | None
    team_id: int
    club_uid: int | None
    club_name: str | None
    type_code: int
    original_amount: int
    start_date: date
    end_date: date
    interest_rate_raw: float | None
    term_money_1_raw: int
    term_money_2_raw: int
    term_money_3_raw: int
    owner_source: str


_DATE_PAIR = re.compile(rb"[\x07\x08](?=.{6}[\x07\x08])", re.DOTALL)


def _loan_key(db, at):
    if at < 4 or at + 28 > len(db) or db[at] != 1 or not 1 <= db[at + 21] <= 15:
        return None
    amount = _SIGNED.unpack_from(db, at + 1)[0]
    start = decode_date(db, at + 24)
    end = decode_date(db, at + 17)
    if amount <= 0 or start is None or end is None or start > end:
        return None
    return db[at + 21], amount, start, end


def _counted_loan_group(db, at):
    first = at
    while _loan_key(db, first - 28) is not None:
        first -= 28
    stop = at + 28
    while _loan_key(db, stop) is not None:
        stop += 28
    count = (stop - first) // 28
    if _WORD.unpack_from(db, first - 4)[0] == count:
        return range(first, stop, 28)
    return ()


def matched_live_loans(save: Save) -> Table[LiveLoan]:
    _check_build(save)
    keys = defaultdict(list)
    for loan in save.starting_loan_terms():
        if loan.start_date and loan.end_date and loan.start_date <= loan.end_date:
            keys[loan.type_code, loan.original_amount, loan.start_date, loan.end_date].append(loan)
    amounts = {k[1] for k in keys}
    hits = defaultdict(list)
    with save._context.section("game_db") as db:
        for m in _DATE_PAIR.finditer(db):
            at = m.start() - 20
            if at < 4 or at + 28 > len(db) or db[at] != 1 or not 1 <= db[at + 21] <= 15:
                continue
            amount = _SIGNED.unpack_from(db, at + 1)[0]
            if amount not in amounts:
                continue
            key = (db[at + 21], amount, decode_date(db, at + 24), decode_date(db, at + 17))
            if key in keys:
                hits[key].append(at)
        direct = {}
        for key, offsets in hits.items():
            if len(offsets) == len(keys[key]) == 1:
                direct[offsets[0]] = keys[key][0]
        owners = direct.copy()
        for at, loan in direct.items():
            group = _counted_loan_group(db, at)
            if any(pos in direct and direct[pos].team_id != loan.team_id for pos in group):
                continue
            owners.update((pos, loan) for pos in group if pos not in owners)
        rows = []
        for at, owner in sorted(owners.items()):
            key = _loan_key(db, at)
            if key is None:
                continue
            loan = direct.get(at)
            vals = struct.unpack_from("<iii", db, at + 5)
            rows.append(
                LiveLoan(
                    loan.record_id if loan else None,
                    owner.team_id,
                    owner.club_uid,
                    owner.club_name,
                    key[0],
                    key[1],
                    key[2],
                    key[3],
                    loan.interest_rate_raw if loan else None,
                    *vals,
                    "opening_terms_match" if loan else "same_counted_loan_list",
                )
            )
    return Table(rows, LiveLoan)


@dataclass(frozen=True, slots=True)
class ClubFinanceSnapshot:
    club_uid: int
    club_name: str
    save_date: date
    balance_at_save_candidate: int | None
    latest_month: date
    month_balance: int
    month_transfer_budget_remaining: int
    month_wage_budget_weekly: int
    month_wage_payroll_weekly: int


def club_finance_snapshots(save: Save) -> Table[ClubFinanceSnapshot]:
    _check_build(save)
    latest = {row.club_uid: row for row in save.finances()}
    layouts = find_finance_layouts(save.info.section_schemas.get("game_db"), save.info.build)
    # Same structural position as the verified FM27 live bank balance. Kept explicitly
    # provisional on FM24 until a same-save, same-day screen establishes the unit and value.
    layouts = replace(layouts, sponsors=replace(layouts.sponsors, balance_offset=22))
    rows = []
    with save._context.section("game_db") as db:
        for span in save._context.own_club_record_spans():
            row = latest.get(span.club_uid)
            if row is None:
                continue
            rows.append(
                ClubFinanceSnapshot(
                    row.club_uid,
                    row.club_name,
                    save.info.game_date,
                    read_current_balance(db, span, layouts),
                    row.month,
                    row.balance,
                    row.transfer_budget_remaining,
                    row.wage_budget_weekly,
                    row.wage_payroll_weekly,
                )
            )
    return Table(rows, ClubFinanceSnapshot)


@dataclass(frozen=True, slots=True)
class LastTransfer:
    player_uid: int
    player_name: str | None
    last_fee: int | None
    wage_at_signing: int | None


_TRANSFER_MARKER = b"\x01\x00\x6c\x07" * 3


def last_transfer_record(db, begin, end, uid, name):
    """Read the FM Open Scout FM24 last-transfer shape inside this player's own boundaries."""
    if end is None or begin >= end:
        return None
    at = db.find(_TRANSFER_MARKER, begin, end)
    if at < 0 or at + 16 > end:
        return None
    size = _WORD.unpack_from(db, at + 12)[0]
    head = at + 16 + size
    if size > 64 or head + 13 > end or db[head + 12] != 1:
        return None
    fee, wage = struct.unpack_from("<ii", db, head + 4)
    if fee < 0 and wage < 0:
        return None
    return LastTransfer(uid, name, fee if fee >= 0 else None, wage if wage >= 0 else None)


@dataclass(frozen=True, slots=True)
class MatchResult:
    report_id: int
    competition_id: int
    competition_name: str | None
    date: date
    kick_off_time: time
    home_team_id: int
    home_club_uid: int | None
    home_club_name: str | None
    away_team_id: int
    away_club_uid: int | None
    away_club_name: str | None
    home_goals: int | None
    away_goals: int | None
    attendance: int | None
    away_fans: int | None
    home_goals_after_extra_time: int | None
    unknown_home_b2: int | None
    unknown_home_b3: int | None
    away_goals_after_extra_time: int | None
    unknown_away_b2: int | None
    unknown_away_b3: int | None


# The result block follows this marker in FM24 match reports: per team the goals at the end of
# normal time and three further bytes (0xFF when unused): the goals after extra time, then two
# bytes set only in some cup ties. Then the report's own id, the attendance and the away fans.
# Checked against the in-game fixture list: score, attendance, away fans, and a cup tie shown as
# "e 1-0" whose normal-time bytes are 0-0 and extra-time bytes 1-0.
_RESULT_MARKER = b"\xe0\x1f\x88\x3b"
_RESULT_ID_FIRST = 34
_RESULT_SEARCH = 160
_GOALS_MAXIMUM = 40


def _byte_or_none(value: int) -> int | None:
    return None if value == 0xFF else value


def match_result_block(report: bytes, report_id: int):
    """(home goals, away goals, attendance, away fans, home extras, away extras), or None."""
    # Some reports carry a second marker block before the result one (continental ties), and
    # the 0xFF run after the marker can spell a small report id, so the id is looked for only
    # past that run and under each marker in turn.
    key = _WORD.pack(report_id)
    marker = report.find(_RESULT_MARKER)
    while marker >= 0:
        at = report.find(key, marker + _RESULT_ID_FIRST, marker + _RESULT_SEARCH)
        if at >= 0 and at + 12 <= len(report):
            break
        marker = report.find(_RESULT_MARKER, marker + 1)
    else:
        return None
    home, away = report[at - 8], report[at - 4]
    if home > _GOALS_MAXIMUM or away > _GOALS_MAXIMUM:
        return None
    attendance, away_fans = struct.unpack_from("<II", report, at + 4)
    return (
        home,
        away,
        attendance,
        away_fans,
        tuple(_byte_or_none(b) for b in report[at - 7 : at - 4]),
        tuple(_byte_or_none(b) for b in report[at - 3 : at]),
    )


def match_results(save: Save) -> Table[MatchResult]:
    """One row per match report the save keeps (league, cup and friendly matches)."""
    from fmsave._layouts import MatchReportLayout, find_layout
    from fmsave.readers._common import MATCH_REPORTS_SECTION
    from fmsave.readers.team_match_stats import _decompress, _header, indexed_reports

    _check_build(save)
    info = save.info
    match = find_layout(
        MatchReportLayout, MATCH_REPORTS_SECTION, info.section_schemas.get(MATCH_REPORTS_SECTION), info.build
    )
    layout = match.layout
    clubs = save._context.club_index()
    names = {c.id: c.name for c in save.competitions()}

    def club(team):
        link = clubs.team_to_club.get(team)
        found = clubs.club_by_uid.get(link[0]) if link else None
        return (found.uid, found.name) if found else (None, None)

    rows = []
    with save._context.section(MATCH_REPORTS_SECTION) as section:
        view = memoryview(section)
        for report_id, start, size in indexed_reports(section, layout, info.file_name):
            report = _decompress(view[start : start + size], layout)
            header = _header(report, layout) if report is not None else None
            if header is None:
                continue
            block = match_result_block(report, report_id)
            hg, ag, attendance, away_fans, home_extra, away_extra = block or (
                None, None, None, None, (None,) * 3, (None,) * 3
            )
            home_uid, home_name = club(header.home_team_id)
            away_uid, away_name = club(header.away_team_id)
            rows.append(
                MatchResult(
                    report_id,
                    header.competition_id,
                    names.get(header.competition_id),
                    header.kick_off.date(),
                    header.kick_off.time(),
                    header.home_team_id,
                    home_uid,
                    home_name,
                    header.away_team_id,
                    away_uid,
                    away_name,
                    hg,
                    ag,
                    attendance,
                    away_fans,
                    *home_extra,
                    *away_extra,
                )
            )
    rows.sort(key=lambda r: (r.date, r.kick_off_time, r.report_id))
    return Table(rows, MatchResult)


@dataclass(frozen=True, slots=True)
class LeagueHistory:
    archive_row: int
    history_group: int | None
    team_id: int | None
    club_uid: int | None
    club_name: str | None
    season_end_year: int
    competition_id: int
    position: int | None
    division_size: int
    played: int
    won: int
    drawn: int
    lost: int
    goals_for: int
    goals_against: int
    points_raw: int


# Four independently stored team references precede the record-manager history selectors.
_TC_TEAM = re.compile(
    rb"(?=(?P<team>.{2}\x00\x00).{23}(?P=team).{23}(?P=team).{9}(?P=team))", re.DOTALL
)


def _league_history_owners(manager, group_count, teams):
    by_team = defaultdict(set)
    for m in _TC_TEAM.finditer(manager):
        at = m.start() + 147
        if at + 4 > len(manager) or manager[at - 6 : at - 4] != b"\xff\xff":
            continue
        team = _WORD.unpack(m["team"])[0]
        group = _WORD.unpack_from(manager, at)[0]
        if team in teams and group < group_count:
            by_team[team].add(group)
    ownership = defaultdict(set)
    for team, groups in by_team.items():
        for group in groups:
            ownership[group].add(team)
    return {
        g: next(iter(ids))
        for g, ids in ownership.items()
        if len(ids) == 1 and len(by_team[next(iter(ids))]) == 1
    }


def league_history(save: Save) -> Table[LeagueHistory]:
    _check_build(save)
    data, groups, count = _pool(save, "tc_league_history", 1, _RANK.size)
    clubs = save._context.club_index()
    owners = _league_history_owners(save._read_section("tc_record_man"), count, clubs.team_to_club)
    rows = []
    for i, r in enumerate(_RANK.iter_unpack(memoryview(data)[8:])):
        year, competition, rank, size, _, _, played, _, won, drawn, lost, _, gf, ga, points = r
        group = groups[i]
        team = owners.get(group)
        link = clubs.team_to_club.get(team)
        club = clubs.club_by_uid.get(link[0]) if link else None
        rows.append(
            LeagueHistory(
                i,
                group if group >= 0 else None,
                team,
                club.uid if club else None,
                club.name if club else None,
                year,
                competition,
                rank + 1 if rank < size else None,
                size,
                played,
                won,
                drawn,
                lost,
                gf,
                ga,
                points,
            )
        )
    return Table(rows, LeagueHistory)
