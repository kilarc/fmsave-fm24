"""CSV annotations for the FM24 study's interpretation of transfer values."""

from pathlib import Path

from fmsave import export
from fmsave._layouts.fm24_24_4_2 import PLAYER_RECORDS
from fmsave.models.common import TransferValueState
from fmsave.models.players import Player
from fmsave.readers._common import MISSING_REFERENCE
from fmsave.table import Table

_SPECIAL = {
    TransferValueState.PLACEHOLDER: (PLAYER_RECORDS.transfer_value_placeholder, "판매 불가(해당 저장 시점)"),
    TransferValueState.ZERO: (0, "원값 0(이적가치 미확인)"),
    TransferValueState.UNSET: (MISSING_REFERENCE, "값 미설정"),
}


def transfer_annotation(state: str, value: int | None) -> tuple[int, str | None]:
    if state == TransferValueState.OK and value is not None:
        return value, None
    return _SPECIAL[TransferValueState(state)]


# FM24 injured side. Confirmed against the in-game injury report body diagram (front view is
# mirrored): code 1 marked a right foot and a right groin. Code 0 appears only on archive rows
# from before the game started, where the database stores no side.
SIDE_LABELS = {1: "오른쪽", 2: "왼쪽", 3: "좌우 없음", 0: "기록 없음"}


def _insert_after(columns: list[str], anchor: str, added: list[str]) -> list[str]:
    at = columns.index(anchor) + 1
    return columns[:at] + added + columns[at:]


def _side(value: object) -> str | None:
    return None if value is None or value == "" else SIDE_LABELS.get(int(value))


def _write_injuries(table: Table, path: Path) -> dict[str, float]:
    """Injuries with `side` (from r11) and `reinjury_risk` (r12: the temporary re-injury risk
    a recent or current injury carries around its return date; higher at equal proneness means
    more injuries soon after return)."""
    from fmsave.models.injuries import InjuryRecord

    columns = list(export.column_names(InjuryRecord))
    columns = _insert_after(columns, "unknown_r11", ["side"])
    columns = _insert_after(columns, "unknown_r12", ["reinjury_risk"])

    def rows():
        for row in export.flat_rows(table, InjuryRecord, json_ready=True):
            row["side"] = _side(row.get("unknown_r11"))
            row["reinjury_risk"] = row.get("unknown_r12")
            yield row

    export.write_csv(rows(), columns, path)
    return {"side": 1.0 if len(table) else 0.0, "reinjury_risk": 1.0 if len(table) else 0.0}


def _write_injury_episodes(table: Table, path: Path) -> dict[str, float]:
    """Injury archive rows with `side` decoded from `archive_side_code`."""
    from fmsave.readers.fm24_archives import InjuryEpisode

    columns = _insert_after(list(export.column_names(InjuryEpisode)), "archive_side_code", ["side"])

    def rows():
        for row in export.flat_rows(table, InjuryEpisode, json_ready=True):
            row["side"] = _side(row.get("archive_side_code"))
            yield row

    export.write_csv(rows(), columns, path)
    return {"side": 1.0 if len(table) else 0.0}


# FM24 contract money (stored units; the screen shows them times the display rate):
# money_a = loyalty bonus total over the whole contract (about 3 weeks' wage per contract year),
# money_b = total of an amount paid in yearly instalments, money_c = the part still unpaid
# (c/b is 4/5, 2/3, 1/2 after one of 5, 3, 2 instalments).
CONTRACT_MONEY_COLUMNS = (
    ("unknown_money_a", "loyalty_bonus_total"),
    ("unknown_money_b", "installment_total"),
    ("unknown_money_c", "installment_remaining"),
)


def _write_contracts(table: Table, path: Path) -> dict[str, float]:
    from fmsave.models.contracts import Contract

    columns = list(export.column_names(Contract))
    for source, added in CONTRACT_MONEY_COLUMNS:
        columns = _insert_after(columns, source, [added])

    def rows():
        for row in export.flat_rows(table, Contract, json_ready=True):
            for source, added in CONTRACT_MONEY_COLUMNS:
                row[added] = row.get(source)
            yield row

    export.write_csv(rows(), columns, path)
    return {added: 1.0 if len(table) else 0.0 for _, added in CONTRACT_MONEY_COLUMNS}


def _write_job_vacancies(table: Table, career, path: Path) -> dict[str, float]:
    """Job vacancies with `team_kind`: a club's team, a clubless stub team (national sides such
    as the U-21 teams of European qualifying), or a team no record links."""
    from fmsave.models.jobs import JobVacancy

    stubs = career._context.club_index().stub_team_ids
    columns = list(export.column_names(JobVacancy))
    at = columns.index("team_slot") + 1
    columns[at:at] = ["team_kind"]

    def rows():
        for row in export.flat_rows(table, JobVacancy, json_ready=True):
            if row["club_uid"] is not None:
                row["team_kind"] = "club"
            elif row["team_id"] in stubs:
                row["team_kind"] = "stub_team(구단 없는 팀: 국가대표 등)"
            else:
                row["team_kind"] = "미연결"
            yield row

    export.write_csv(rows(), columns, path)
    return {"team_kind": 1.0 if len(table) else 0.0}


def write_table_csv(
    table: Table, entity: str, build: str, path: Path, career=None
) -> dict[str, float]:
    """Write a table and return coverage for any added CSV columns."""
    if entity == "job_vacancies" and build == "24.4.2" and career is not None:
        return _write_job_vacancies(table, career, path)
    if entity == "contracts" and build == "24.4.2":
        return _write_contracts(table, path)
    if entity == "injuries" and build == "24.4.2":
        return _write_injuries(table, path)
    if entity == "injury_episodes" and build == "24.4.2":
        return _write_injury_episodes(table, path)
    if entity != "players" or build != "24.4.2":
        table.write_csv(path)
        return {}
    columns = list(export.column_names(Player))
    at = columns.index("transfer_value") + 1
    columns[at:at] = ["transfer_value_note", "transfer_value_raw"]
    noted = 0

    def annotated_rows():
        nonlocal noted
        for row in export.flat_rows(table, Player, json_ready=True):
            raw, note = transfer_annotation(row["transfer_value_state"], row["transfer_value"])
            row["transfer_value_note"] = note
            row["transfer_value_raw"] = raw
            if note is not None:
                noted += 1
            yield row

    export.write_csv(annotated_rows(), columns, path)
    return {"transfer_value_raw": 1.0 if len(table) else 0.0,
            "transfer_value_note": noted / len(table) if len(table) else 0.0}
