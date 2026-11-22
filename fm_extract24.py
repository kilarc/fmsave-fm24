"""Export all fmsave tables from private copies, with coverage and failure reports."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import sys
import tempfile
import time
import warnings
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

import fmsave
from fmsave.fm24_csv import write_table_csv
from fmsave.checks import validate_save

ENTITIES = (
    "clubs",
    "players",
    "contracts",
    "suspensions",
    "managed_clubs",
    "nations",
    "stages",
    "competitions",
    "fixtures",
    "officials",
    "league_tables",
    "transfer_windows",
    "competition_rules",
    "player_match_stats",
    "team_match_stats",
    "player_season_stats",
    "player_season_history",
    "stadiums",
    "finances",
    "sponsorships",
    "facilities",
    "affiliates",
    "job_vacancies",
    "staff",
    "staff_lists",
    "injury_types",
    "injuries",
    "training",
    "mentoring",
    "tactics",
    "set_pieces",
    "selections",
    "squad_planner",
    "media_predictions",
    "injury_episodes",
    "historical_league_positions",
    "starting_loan_terms",
    "matched_live_loans",
    "club_finance_snapshots",
    "last_transfer_terms",
    "injury_link_keys",
    "match_results",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def copy_with_utf8_bom(source: Path, target: Path, attempts: int = 20) -> None:
    """Copy a finished CSV into place with a UTF-8 BOM, retrying while OneDrive holds it."""
    for attempt in range(attempts):
        try:
            with source.open("rb") as reader, target.open("wb") as writer:
                writer.write(b"\xef\xbb\xbf")
                shutil.copyfileobj(reader, writer)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.5)


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def process_save(source: Path, destination: Path, entities: list[str]) -> Path:
    source_hash = sha256(source)
    rows: list[dict[str, object]] = []
    started = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    with tempfile.TemporaryDirectory(prefix="fm24_read_") as temporary:
        copied = Path(temporary) / source.name
        shutil.copy2(source, copied)
        if sha256(copied) != source_hash:
            raise RuntimeError("세이브가 복사 중 변경됐습니다. 저장이 끝난 뒤 다시 실행하세요.")
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            with fmsave.open(copied) as career:
                game_date = str(career.info.game_date or "nodate")
                output = destination / f"{source.stem}__{game_date}__{started}"
                output.mkdir(parents=True)
                info = {
                    "game": career.info.game,
                    "build": career.info.build,
                    "game_date": game_date,
                    "database": career.info.db_version,
                    "source_name": source.name,
                    "source_sha256": source_hash,
                    "section_schemas": dict(career.info.section_schemas),
                    "open_warnings": [str(item.message) for item in caught],
                }
                write_json(output / "info.json", info)
                for entity in entities:
                    begin = time.monotonic()
                    warning_start = len(caught)
                    result: dict[str, object] = {"entity": entity}
                    # Written in the temporary folder first, then copied in one go, so a synced
                    # output folder (OneDrive) never sees a rename it can lock.
                    pending = Path(temporary) / f"{entity}.csv"
                    try:
                        table = getattr(career, entity)()
                        extra_coverage = write_table_csv(table, entity, career.info.build, pending, career)
                        copy_with_utf8_bom(pending, output / f"{entity}.csv")
                        pending.unlink(missing_ok=True)
                        with (output / f"{entity}__coverage.csv").open(
                            "w", newline="", encoding="utf-8-sig"
                        ) as coverage:
                            writer = csv.writer(coverage)
                            writer.writerow(("column", "rows", "non_null", "null", "fill_rate"))
                            for column, share in (dict(table.coverage) | extra_coverage).items():
                                present = round(len(table) * share)
                                writer.writerow(
                                    (column, len(table), present, len(table) - present, share)
                                )
                        result.update(status="decoded" if len(table) else "empty", rows=len(table))
                    except fmsave.UnsupportedGameError as error:
                        # A table this game version does not store in a mapped form, such as
                        # FM24 team match stats: reported, but not counted as a failure.
                        pending.unlink(missing_ok=True)
                        result.update(status="unsupported", error=str(error))
                    except Exception as error:  # noqa: BLE001 - each reader reports its own failure
                        pending.unlink(missing_ok=True)
                        result.update(
                            status="error", error_type=type(error).__name__, error=str(error)
                        )
                    result["seconds"] = round(time.monotonic() - begin, 3)
                    result["warnings"] = [str(item.message) for item in caught[warning_start:]]
                    rows.append(result)
                    write_json(output / "export_log.json", rows)
                    print(f"{entity}: {result['status']} ({result.get('rows', 0)}행)", flush=True)
                write_json(output / "validation.json", validate_save(career).to_json_dict())
    unchanged = sha256(source) == source_hash
    write_json(
        output / "summary.json",
        {
            "source_unchanged": unchanged,
            "decoded": sum(row["status"] == "decoded" for row in rows),
            "empty": sum(row["status"] == "empty" for row in rows),
            "unsupported": sum(row["status"] == "unsupported" for row in rows),
            "errors": sum(row["status"] == "error" for row in rows),
            "readers": rows,
        },
    )
    if not unchanged:
        raise RuntimeError(
            "실행 중 원본 세이브가 변경됐습니다. 추출 결과의 기준은 복사 시점입니다."
        )
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="FM24 세이브 전체 추출 및 컬럼 채움률 검사")
    parser.add_argument("target", type=Path, help=".fm 파일 또는 세이브 폴더")
    parser.add_argument("-o", "--out", type=Path, default=Path("fm24_dump"))
    parser.add_argument("--entities", nargs="+", choices=ENTITIES)
    arguments = parser.parse_args(argv)
    target = arguments.target.resolve()
    saves = [target] if target.is_file() else sorted(target.glob("*.fm"))
    if not saves:
        parser.error(f"세이브 파일이 없습니다: {target}")
    arguments.out.mkdir(parents=True, exist_ok=True)
    exit_code = 0
    for save in saves:
        output = process_save(save, arguments.out.resolve(), list(arguments.entities or ENTITIES))
        print(f"출력: {output}", flush=True)
        summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
        if summary["errors"]:
            exit_code = 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
