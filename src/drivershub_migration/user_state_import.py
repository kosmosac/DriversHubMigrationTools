"""Build the durable user-state import transaction."""

from __future__ import annotations

import json
from pathlib import Path

from .account_import import _integer, _sql_value


def _records(directory: Path, name: str) -> list[dict[str, object]]:
    try:
        document = json.loads((directory / "normalized" / f"{name}.json").read_text(encoding="utf-8"))
        records = document["records"]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ValueError(f"Unable to read normalized {name}") from exc
    if not isinstance(records, list) or not all(isinstance(row, dict) for row in records):
        raise ValueError(f"The normalized {name} records are invalid")
    return records


def _role_list(value: object, field: str) -> str:
    if not isinstance(value, list):
        raise ValueError(f"{field} is not an array")
    roles = [_integer(role, field) for role in value]
    return "," + ",".join(str(role) for role in roles) + "," if roles else ",,"


def build_user_state_stage(
    directory: Path, *, convert_personal_notes_to_global: bool = False
) -> tuple[str, dict[str, object]]:
    profiles = _records(directory, "profiles")
    bans = _records(directory, "bans")
    statements = ["SET time_zone = '+00:00';", "START TRANSACTION;"]
    replaced_destination_state = False
    try:
        preflight = json.loads(
            (directory / "target-preflight.json").read_text(encoding="utf-8")
        )
    except FileNotFoundError:
        preflight = {}
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Unable to read destination preflight") from exc
    resolution = preflight.get("bootstrap") if isinstance(preflight, dict) else None
    if (
        isinstance(resolution, dict)
        and resolution.get("action") == "merge-matching-destination-accounts"
    ):
        statements.extend(
            [
                "DELETE FROM `user_note`;",
                "DELETE FROM `user_role_history`;",
                "DELETE FROM `banned`;",
                "DELETE FROM `ban_history`;",
            ]
        )
        replaced_destination_state = True
    role_histories = ban_histories = global_notes = 0
    personal_notes_skipped = personal_notes_converted = 0
    for profile in profiles:
        uid = _integer(profile.get("uid"), "uid")
        global_note = profile.get("global_note")
        global_note = global_note if isinstance(global_note, str) else ""
        personal_note = profile.get("note")
        personal_note = personal_note if isinstance(personal_note, str) else ""
        if personal_note and convert_personal_notes_to_global:
            global_note = (
                global_note
                + "\n\n[Migrated personal administrator note]\n"
                + personal_note
                if global_note
                else personal_note
            )
            personal_notes_converted += 1
        elif personal_note:
            personal_notes_skipped += 1
        if global_note:
            statements.append("INSERT INTO `user_note` (`from_uid`,`to_uid`,`note`,`update_timestamp`) " + f"VALUES (-1000,{uid},{_sql_value(global_note)},NULL);")
            global_notes += 1
        histories = profile.get("role_history")
        if histories is not None:
            if not isinstance(histories, list):
                raise ValueError(f"Profile {uid} has invalid role history")
            for row in histories:
                if not isinstance(row, dict):
                    raise ValueError(f"Profile {uid} has an invalid role-history record")
                historyid = _integer(row.get("historyid"), "historyid")
                timestamp = _integer(row.get("timestamp"), "timestamp")
                if timestamp < 0:
                    raise ValueError("Role-history timestamps must be Unix seconds")
                statements.append("INSERT INTO `user_role_history` (`historyid`,`uid`,`added_roles`,`removed_roles`,`timestamp`) VALUES (" + f"{historyid},{uid},{_sql_value(_role_list(row.get('added_roles'), 'added_roles'))},{_sql_value(_role_list(row.get('removed_roles'), 'removed_roles'))},{timestamp});")
                role_histories += 1
        histories = profile.get("ban_history")
        if histories is not None:
            if not isinstance(histories, list):
                raise ValueError(f"Profile {uid} has invalid ban history")
            for row in histories:
                if not isinstance(row, dict):
                    raise ValueError(f"Profile {uid} has an invalid ban-history record")
                historyid = _integer(row.get("historyid"), "historyid")
                expire = _integer(row.get("expire_timestamp"), "expire_timestamp")
                reason = row.get("reason") if isinstance(row.get("reason"), str) else ""
                statements.append("INSERT INTO `ban_history` (`historyid`,`uid`,`email`,`discordid`,`steamid`,`truckersmpid`,`expire_timestamp`,`reason`) " + f"SELECT {historyid},`uid`,NULLIF(`email`,''),`discordid`,`steamid`,`truckersmpid`,{expire},{_sql_value(reason)} FROM `user` WHERE `uid`={uid};")
                ban_histories += 1
    for row in bans:
        values = [_integer(row.get("uid"), "ban uid", optional=True), row.get("email") if isinstance(row.get("email"), str) else None, _integer(row.get("discordid"), "ban discordid", optional=True), _integer(row.get("steamid"), "ban steamid", optional=True), _integer(row.get("truckersmpid"), "ban truckersmpid", optional=True), _integer(row.get("expire_timestamp"), "ban expire_timestamp"), row.get("reason") if isinstance(row.get("reason"), str) else ""]
        statements.append("INSERT INTO `banned` (`uid`,`email`,`discordid`,`steamid`,`truckersmpid`,`expire_timestamp`,`reason`) VALUES (" + ",".join(_sql_value(value) for value in values) + ");")
    statements.append("COMMIT;")
    return "\n".join(statements) + "\n", {"state": "ready", "global_notes": global_notes, "personal_notes_converted": personal_notes_converted, "personal_notes_skipped": personal_notes_skipped, "role_history_records": role_histories, "active_bans": len(bans), "ban_history_records": ban_histories, "replaced_destination_user_state": replaced_destination_state, "database_time_zone": "+00:00"}
