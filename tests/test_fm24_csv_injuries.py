"""FM24 injury CSV annotations: side labels and the re-injury risk column."""

from fmsave.fm24_csv import SIDE_LABELS, _insert_after, _side


def test_side_labels_follow_the_confirmed_codes() -> None:
    assert SIDE_LABELS == {1: "오른쪽", 2: "왼쪽", 3: "좌우 없음", 0: "기록 없음"}
    assert _side(1) == "오른쪽"
    assert _side("2") == "왼쪽"
    assert _side(None) is None
    assert _side("") is None


def test_added_columns_sit_next_to_their_source() -> None:
    columns = ["kind", "unknown_r11", "unknown_r12", "unknown_hi7_date"]
    columns = _insert_after(columns, "unknown_r11", ["side"])
    columns = _insert_after(columns, "unknown_r12", ["reinjury_risk"])
    assert columns == [
        "kind",
        "unknown_r11",
        "side",
        "unknown_r12",
        "reinjury_risk",
        "unknown_hi7_date",
    ]
