"""The pre-season media prediction a league stores for each of its teams (FM24)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import ClassVar

from fmsave._status import register_field_statuses


@dataclass(frozen=True, slots=True)
class MediaPrediction:
    """One team's predicted finish in one league, as the league's own team block stores it.

    Every league the save runs keeps one block per season with a record per team. The block
    sorts its teams by `prediction_score` and stores that rank as `predicted_position`; the
    score and the rank stayed byte-identical for all 20 teams of a league across saves 17 days
    apart at the end of a season while the same records' `table_position` moved. The game
    can still revise the prediction during a season, so a mid-season save may hold a revised
    one (unconfirmed against a screen). Competitions that store no
    prediction (cups, groups, leagues the save does not run) hold 255 in every rank byte and
    give no rows.

    Attributes:
        competition_id: The competition whose fixtures pair these teams most often, or None
            when no fixture pairs two of them (unconfirmed).
        competition_name: Denormalised name of competition_id, None where the save stores no
            name (unconfirmed).
        rules_name: The rules file name stored in the block header, such as `eng_prem`
            (unconfirmed).
        team_id: The team the record belongs to (unconfirmed).
        club_uid: Uid of the club fielding team_id, None when no club lists it (unconfirmed).
        club_name: Denormalised full name of club_uid (unconfirmed).
        predicted_position: 1 for the favourite: the team's rank by prediction_score among the
            block's teams (unconfirmed).
        prediction_score: The stored score the prediction ranks by; higher is stronger
            (unconfirmed).
        table_position: The team's current league position, 1 for the leader. It matched the
            final table of a finished season on every team checked (unconfirmed).
        unknown: Rank-like bytes with no confirmed meaning: `rank_low` and `rank_high` bracket
            the predicted rank on every team measured (a likely best and worst case),
            `rank_group` repeats the top rank of a run of close scores, and `rank_27` equals
            the club reputation order on one league and the table order on another
            (unconfirmed). All are zero-based as stored.
    """

    competition_id: int | None
    competition_name: str | None
    rules_name: str | None
    team_id: int
    club_uid: int | None
    club_name: str | None
    predicted_position: int
    prediction_score: int
    table_position: int
    unknown: Mapping[str, int]

    UNKNOWN_KEYS: ClassVar[tuple[str, ...]] = ("rank_low", "rank_high", "rank_group", "rank_27")


register_field_statuses(
    MediaPrediction,
    unconfirmed=(
        "competition_id",
        "competition_name",
        "rules_name",
        "team_id",
        "club_uid",
        "club_name",
        "predicted_position",
        "prediction_score",
        "table_position",
        "unknown",
    ),
)
