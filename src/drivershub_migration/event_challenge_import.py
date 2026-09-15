"""Build imports for event and challenge definitions."""

from __future__ import annotations

import json
from pathlib import Path

from .account_import import _integer, _sql_value
from .content_import import _compressed, _records, _timestamp


JOB_REQUIREMENTS = ["source_city_id", "source_company_id", "destination_city_id", "destination_company_id", "minimum_distance", "cargo_id", "minimum_cargo_mass", "maximum_cargo_damage", "maximum_speed", "maximum_fuel", "minimum_profit", "maximum_profit", "maximum_offence", "allow_overspeed", "allow_auto_park", "allow_auto_load", "must_not_be_late", "must_be_special", "minimum_average_speed", "maximum_average_speed", "minimum_average_fuel", "maximum_average_fuel", "minimum_seconds_spent", "maximum_seconds_spent", "maximum_distance", "minimum_detour_percentage", "maximum_detour_percentage", "minimum_adblue", "maximum_adblue", "minimum_fuel", "market", "game", "truck_id", "truck_plate_country_id", "minimum_truck_wheel", "maximum_truck_wheel", "maximum_cargo_mass", "minimum_cargo_damage", "minimum_offence", "minimum_xp", "maximum_xp", "minimum_train", "maximum_train", "minimum_ferry", "maximum_ferry", "minimum_teleport", "maximum_teleport", "minimum_tollgate", "maximum_tollgate", "minimum_toll_paid", "maximum_toll_paid", "minimum_collision", "maximum_collision", "minimum_warp", "maximum_warp", "enabled_realistic_settings"]


def _userid(value: object, field: str, *, fallback: int | None = None) -> int:
    if not isinstance(value, dict):
        raise ValueError(f"{field} is not an object")
    result = _integer(value.get("userid"), f"{field}.userid", optional=True)
    if result is None:
        if fallback is None:
            raise ValueError(f"{field}.userid is unavailable")
        return fallback
    return result


def _id_list(values: object, field: str) -> str:
    if not isinstance(values, list):
        raise ValueError(f"{field} is not an array")
    return ",".join(str(_integer(value, field)) for value in values)


def build_event_challenge_stage(directory: Path) -> tuple[str, dict[str, object]]:
    statements = ["SET time_zone = '+00:00';", "START TRANSACTION;"]
    challenges = _records(directory, "challenges-details")
    deferred_records = 0
    for row in challenges:
        requirements = row.get("job_requirements")
        if not isinstance(requirements, dict):
            raise ValueError("Challenge job requirements are invalid")
        missing = [key for key in JOB_REQUIREMENTS if key not in requirements]
        if missing:
            raise ValueError("Challenge job requirements are incomplete")
        requirement_list = [requirements[key] for key in JOB_REQUIREMENTS]
        roles = _id_list(row.get("required_roles"), "challenge required roles")
        roles = f",{roles}," if roles else ",,"
        values = [
            _integer(row.get("challengeid"), "challengeid"), _userid(row.get("creator"), "challenge creator"),
            row.get("title") if isinstance(row.get("title"), str) else "", _compressed(row.get("description"), "challenge description"),
            _timestamp(row.get("start_time"), "challenge start time"), _timestamp(row.get("end_time"), "challenge end time"),
            _integer(row.get("type"), "challenge type"), _integer(row.get("orderid"), "challenge orderid"), bool(row.get("is_pinned")),
            _integer(row.get("delivery_count"), "challenge delivery count"), roles, _integer(row.get("required_distance"), "challenge required distance"),
            _integer(row.get("reward_points"), "challenge reward points"), bool(row.get("public_details")),
            _compressed(json.dumps(requirement_list, separators=(",", ":"), ensure_ascii=False), "challenge requirements"),
            _timestamp(row.get("timestamp"), "challenge timestamp"),
        ]
        statements.append("INSERT INTO `challenge` (`challengeid`,`userid`,`title`,`description`,`start_time`,`end_time`,`challenge_type`,`orderid`,`is_pinned`,`delivery_count`,`required_roles`,`required_distance`,`reward_points`,`public_details`,`job_requirements`,`timestamp`) VALUES (" + ",".join(_sql_value(value) for value in values) + ");")
        records = row.get("record")
        if not isinstance(records, list):
            raise ValueError("Challenge record is not an array")
        deferred_records += sum(len(record.get("dlog", [])) for record in records if isinstance(record, dict))

    events = _records(directory, "events-details")
    missing_creators = 0
    for row in events:
        creator = _userid(row.get("creator"), "event creator", fallback=-1)
        if creator == -1:
            missing_creators += 1
        attendees = [_userid(value, "event attendee") for value in row.get("attendees", [])] if isinstance(row.get("attendees"), list) else None
        votes = [_userid(value, "event voter") for value in row.get("votes", [])] if isinstance(row.get("votes"), list) else None
        if attendees is None or votes is None:
            raise ValueError("Event attendee data is invalid")
        values = [
            _integer(row.get("eventid"), "eventid"), creator,
            row.get("title") if isinstance(row.get("title"), str) else "", _compressed(row.get("description"), "event description"),
            _compressed(row.get("link"), "event link"), row.get("departure") if isinstance(row.get("departure"), str) else "",
            row.get("destination") if isinstance(row.get("destination"), str) else "", row.get("distance") if isinstance(row.get("distance"), str) else "",
            _timestamp(row.get("meetup_timestamp"), "event meetup timestamp"), _integer(row.get("departure_timestamp"), "event departure timestamp"),
            bool(row.get("is_private")), _integer(row.get("orderid"), "event orderid"), bool(row.get("is_pinned")),
            _timestamp(row.get("timestamp"), "event timestamp"), ",".join(map(str, votes)), ",".join(map(str, attendees)),
            _integer(row.get("points"), "event points"),
        ]
        statements.append("INSERT INTO `event` (`eventid`,`userid`,`title`,`description`,`link`,`departure`,`destination`,`distance`,`meetup_timestamp`,`departure_timestamp`,`is_private`,`orderid`,`is_pinned`,`timestamp`,`vote`,`attendee`,`points`) VALUES (" + ",".join(_sql_value(value) for value in values) + ");")
    statements.append("COMMIT;")
    return "\n".join(statements) + "\n", {"state": "ready", "challenges": len(challenges), "events": len(events), "event_creators_unavailable": missing_creators, "challenge_delivery_links_deferred": deferred_records, "database_time_zone": "+00:00"}
