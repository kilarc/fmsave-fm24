"""FM24 layouts. Unchanged layouts remain candidates subject to reader validation."""

from dataclasses import replace

from fmsave._layouts import Layout, LayoutEntry, SquadPlannerLayout
from fmsave._layouts import fm26_26_3_2 as fm26

BUILD = "24.4.2"
# No build is declared fully supported before every reader has been validated.
KNOWN_BUILDS: tuple[str, ...] = ()

PLAYER_RECORDS = replace(
    fm26.PLAYER_RECORDS,
    marker_offset=101,
    team_id_offset=15,
    ratings_offset=23,
    attributes_offset=38,
    transfer_value_offset=92,
    club_join_date_offset=97,
    match_sharpness_offset=105,
    condition_offset=109,
    height_offset=122,
    decode_extent=123,
)
PERSON_BLOCKS = replace(
    fm26.PERSON_BLOCKS,
    personality_offset_from_birth=17,
    date_zero_bytes_offset_from_birth=10,
    nation_id_offset_from_birth=9,
    relation_present_offset_from_birth=33,
    relation_count_offset_from_birth=34,
    relation_entries_offset_from_birth=35,
)
# skip_paired_id_lists: in some FM24 saves 6 Croatian and 11 South African club records matched
# an earlier paired-id list as their team list (one id shared by several clubs).
TEAM_LISTS = replace(
    fm26.TEAM_LISTS,
    first_entry_bytes=24,
    first_entry_lead_byte=1,
    skip_paired_id_lists=1,
    clip_at_unaccepted_records=1,
    skip_repeated_float_anchors=1,
    near_one_float_anchors=1,
    admit_missing_main_nation_records=1,
)
CLUB_TABLE = replace(fm26.CLUB_TABLE, walk_table=False)
INJURY_MANAGER = replace(fm26.INJURY_MANAGER, tail=b"")
CONTRACTS = replace(
    fm26.CONTRACTS,
    clause_ff_offset=-15,
    clause_zero_offset=-7,
    clause_count_offset=-4,
    clause_entries_offset=-3,
    clause_trailer_bytes=1,
    head_gate_offset=-34,
    head_type_offset=-32,
    head_money_a_offset=-31,
    head_money_b_offset=-27,
    head_money_c_offset=-23,
)
FIXTURE_CALENDAR = replace(fm26.FIXTURE_CALENDAR, marker_byte_value=24, secondary_marker=24)
# FM24 entry-list items are 3 bytes (a type byte and a u16 id) where FM26 stores 7: every
# staff object with a nonempty list had its ability block exactly 4 bytes per entry earlier
# than the FM26 stride put it, and every object with an empty list already read.
STAFF = replace(
    fm26.STAFF,
    entry_bytes=3,
    code_count=4,
    sentinel_offset=9,
    sentinel_value=10,
    preferences_offset=10,
    block_40_offset=36,
)
MATCH_REPORTS = replace(
    fm26.MATCH_REPORTS,
    index_tail=b"\x01",
    competition_id_offset=37,
    team_marker=b"\x02\x02",
    team_entry_bytes=22,
)
TACTICS = replace(
    fm26.TACTICS,
    header_marker=12,
    selection_end_marker=b"\x3a\x00",
    taker_markers=(b"\x00\x00\x00\x05\x02",),
    order_marker=b"\x01\x08",
    user_signature=bytes.fromhex("223a001802000000"),
    alternate_signature=bytes.fromhex("223a001802000000"),
    preset_signature=bytes.fromhex("223a001802000001"),
    team_instruction_bytes=20,
    slot_tag=bytes.fromhex("3a0002"),
    # One block per slot: all 16 stored tactics of a career save walk their 11 slots whole this
    # way, each with exactly one goalkeeper slot.
    single_block_slots=True,
    # One of five career team blocks stores 24 rows here (the others 0); with them counted, its
    # routine area lines up byte for byte with the others and all 20 routines walk.
    routine_area_list_count_offset=578,
    routine_area_list_entry_bytes=26,
)
TRAINING = replace(fm26.TRAINING, block_entry_lead_byte=4, block_entry_bytes=16)
_NATION_STEPS = list(fm26.NATION_TABLE.record_steps)
_NATION_STEPS[4] = replace(_NATION_STEPS[4], lead_bytes=24)
_NATION_STEPS[13] = replace(_NATION_STEPS[13], lead_bytes=43)
NATION_TABLE = replace(fm26.NATION_TABLE, record_steps=tuple(_NATION_STEPS))
SPONSOR_CHAINS = replace(
    fm26.SPONSOR_CHAINS,
    row_bytes=24,
    tag=1,
    annual_offset=20,
)

_OVERRIDES: dict[type[object], Layout] = {
    type(PLAYER_RECORDS): PLAYER_RECORDS,
    type(PERSON_BLOCKS): PERSON_BLOCKS,
    type(TEAM_LISTS): TEAM_LISTS,
    type(CLUB_TABLE): CLUB_TABLE,
    type(INJURY_MANAGER): INJURY_MANAGER,
    type(CONTRACTS): CONTRACTS,
    type(FIXTURE_CALENDAR): FIXTURE_CALENDAR,
    type(STAFF): STAFF,
    type(MATCH_REPORTS): MATCH_REPORTS,
    type(NATION_TABLE): NATION_TABLE,
    type(SPONSOR_CHAINS): SPONSOR_CHAINS,
    type(TACTICS): TACTICS,
    type(TRAINING): TRAINING,
}
# FM24 stores the FM27 planner shape (4 groups x 3 counted sets x 27 slots) in game_db, about
# 23 KB after the human manager's person record, rather than in `humans`. Two careers' saves
# put it at the same distance; a before/after pair that reordered one slot changed only those
# selector bytes. The lead markers and footer are FM27's anchors and go unused here.
SQUAD_PLANNER = SquadPlannerLayout(
    lead_marker=b"",
    lead_date_marker=b"",
    lead_tail=b"\x01\x02\x00\x04",
    group_marker=b"\x03\x1b",
    set_marker=b"\x1b",
    footer_marker=b"",
    owner_window_bytes=65536,
)

LAYOUTS = tuple(
    LayoutEntry(
        entry.region,
        3569 if entry.region == "game_db" else 7 if entry.region == "injury_manager" else None,
        BUILD,
        _OVERRIDES.get(type(entry.layout), entry.layout),
    )
    for entry in fm26.LAYOUTS
) + (LayoutEntry("humans", None, BUILD, SQUAD_PLANNER),)
