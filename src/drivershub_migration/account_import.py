"""Build the transactional account stage for a destination import."""

from __future__ import annotations

import json
import math
from base64 import b64encode
from pathlib import Path


TRACKER_IDS = {
    "tracksim": 2,
    "trucky": 3,
    "custom": 4,
    "unitracker": 5,
}

UID_REFERENCES = {
    "application": ("uid",),
    "application_token": ("uid",),
    "auditlog": ("uid",),
    "auth_ticket": ("uid",),
    "banned": ("uid",),
    "email_confirmation": ("uid",),
    "pending_user_deletion": ("uid",),
    "session": ("uid",),
    "user_activity": ("uid",),
    "user_note": ("from_uid", "to_uid"),
    "user_notification": ("uid",),
    "user_password": ("uid",),
    "user_role_history": ("uid",),
}

USERID_REFERENCES = {
    "announcement": ("userid",),
    "bonus_point": ("userid", "staff_userid"),
    "challenge": ("userid",),
    "challenge_completed": ("userid",),
    "challenge_record": ("userid",),
    "daily_bonus_history": ("userid",),
    "division": ("userid", "update_staff_userid"),
    "dlog": ("userid",),
    "dlog_deleted": ("userid",),
    "dlog_stats": ("userid",),
    "downloads": ("userid",),
    "economy_balance": ("userid",),
    "economy_garage": ("userid",),
    "economy_merch": ("userid",),
    "economy_transaction": ("from_userid", "to_userid"),
    "economy_truck": ("userid", "assigneeid"),
    "event": ("userid",),
    "poll": ("userid",),
    "poll_vote": ("userid",),
    "task": ("userid",),
    "telemetry": ("userid",),
}


def _read_object(path: Path, description: str) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Unable to read {description}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"The {description} is not an object")
    return value


def _sql_value(value: object) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Unsupported non-finite SQL number")
        return repr(value)
    if isinstance(value, str):
        if value == "":
            return "''"
        return "CONVERT(0x" + value.encode("utf-8").hex() + " USING utf8mb4)"
    raise ValueError(f"Unsupported SQL value type: {type(value).__name__}")


def _integer(value: object, field: str, *, optional: bool = False) -> int | None:
    if value is None and optional:
        return None
    if isinstance(value, bool):
        raise ValueError(f"{field} is not an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().removeprefix("-").isdigit():
        return int(value.strip())
    raise ValueError(f"{field} is not an integer")


def _profile_rows(directory: Path) -> list[dict[str, object]]:
    document = _read_object(
        directory / "normalized" / "profiles.json", "normalized profiles"
    )
    records = document.get("records")
    if not isinstance(records, list):
        raise ValueError("The normalized profiles have no records array")
    profiles: list[dict[str, object]] = []
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise ValueError(f"Profile record {index} is not an object")
        profiles.append(record)
    return profiles


def _relocate_recovery_account(bootstrap: dict[str, object]) -> list[str]:
    old_uid = _integer(bootstrap.get("original_uid"), "original_uid")
    new_uid = _integer(bootstrap.get("replacement_uid"), "replacement_uid")
    old_userid = _integer(
        bootstrap.get("original_userid"), "original_userid", optional=True
    )
    new_userid = _integer(
        bootstrap.get("replacement_userid"), "replacement_userid", optional=True
    )
    statements: list[str] = []
    for table, columns in UID_REFERENCES.items():
        for column in columns:
            statements.append(
                f"UPDATE `{table}` SET `{column}`={new_uid} WHERE `{column}`={old_uid};"
            )
    if old_userid is not None and new_userid is not None:
        for table, columns in USERID_REFERENCES.items():
            for column in columns:
                statements.append(
                    f"UPDATE `{table}` SET `{column}`={new_userid} "
                    f"WHERE `{column}`={old_userid};"
                )
    statements.append(
        "UPDATE `user` SET "
        f"`uid`={new_uid},`userid`={_sql_value(new_userid)} WHERE `uid`={old_uid};"
    )
    return statements


def _merge_bootstrap_account(
    bootstrap: dict[str, object], source_userid: int | None
) -> list[str]:
    target_uid = _integer(bootstrap.get("target_uid"), "target_uid")
    source_uid = _integer(bootstrap.get("source_uid"), "source_uid")
    target_userid = _integer(
        bootstrap.get("target_userid"), "target_userid", optional=True
    )
    statements: list[str] = []
    for table, columns in UID_REFERENCES.items():
        for column in columns:
            statements.append(
                f"UPDATE `{table}` SET `{column}`={source_uid} "
                f"WHERE `{column}`={target_uid};"
            )
    if target_userid is not None and source_userid is not None:
        for table, columns in USERID_REFERENCES.items():
            for column in columns:
                statements.append(
                    f"UPDATE `{table}` SET `{column}`={source_userid} "
                    f"WHERE `{column}`={target_userid};"
                )
    statements.append(
        "UPDATE `user` SET "
        f"`uid`={source_uid},`userid`={_sql_value(source_userid)} "
        f"WHERE `uid`={target_uid};"
    )
    return statements


def _move_existing_account(
    old_uid: int,
    old_userid: int | None,
    new_uid: int,
    new_userid: int | None,
) -> list[str]:
    """Move an existing account and its known references to new internal IDs."""
    statements: list[str] = []
    if old_uid != new_uid:
        for table, columns in UID_REFERENCES.items():
            for column in columns:
                statements.append(
                    f"UPDATE `{table}` SET `{column}`={new_uid} WHERE `{column}`={old_uid};"
                )
    if old_userid is not None and new_userid is not None and old_userid != new_userid:
        for table, columns in USERID_REFERENCES.items():
            for column in columns:
                statements.append(
                    f"UPDATE `{table}` SET `{column}`={new_userid} "
                    f"WHERE `{column}`={old_userid};"
                )
    assignments = []
    if old_uid != new_uid:
        assignments.append(f"`uid`={new_uid}")
    if old_userid != new_userid:
        assignments.append(f"`userid`={_sql_value(new_userid)}")
    if assignments:
        statements.append(
            "UPDATE `user` SET " + ",".join(assignments) + f" WHERE `uid`={old_uid};"
        )
    return statements


def build_account_stage(directory: Path) -> tuple[str, dict[str, object]]:
    """Return a single UTC transaction and a non-sensitive stage summary."""
    preflight = _read_object(
        directory / "target-preflight.json", "destination preflight"
    )
    plan = _read_object(directory / "import-plan.json", "import plan")
    bootstrap = preflight.get("bootstrap")
    if not isinstance(bootstrap, dict) or bootstrap.get("state") not in {
        "ready",
        "not-required",
    }:
        raise ValueError("The bootstrap account action is not ready")
    if plan.get("state") != "complete":
        raise ValueError("The account import plan is not complete")

    action = bootstrap.get("action", "not-required")
    statements = ["SET time_zone = '+00:00';", "START TRANSACTION;"]
    merged_source_uids: set[int] = set()
    if action == "retain-as-recovery-account":
        statements.extend(_relocate_recovery_account(bootstrap))
    elif action == "merge-with-source-administrator":
        merged_source_uid = _integer(bootstrap.get("source_uid"), "source_uid")
        merged_source_uids.add(merged_source_uid)
        matching_account = next(
            (
                account
                for account in plan.get("accounts", [])
                if isinstance(account, dict)
                and account.get("source_uid") == merged_source_uid
            ),
            None,
        )
        if not isinstance(matching_account, dict):
            raise ValueError("The merged bootstrap account is absent from the import plan")
        source_userid = _integer(
            matching_account.get("target_userid"), "target_userid", optional=True
        )
        statements.extend(_merge_bootstrap_account(bootstrap, source_userid))
    elif action == "merge-matching-destination-accounts":
        accounts = bootstrap.get("accounts")
        if not isinstance(accounts, list) or not accounts:
            raise ValueError("The destination account merge has no accounts")

        recovery = bootstrap.get("recovery_account")
        if recovery is not None:
            if not isinstance(recovery, dict):
                raise ValueError("The destination recovery account is not an object")
            statements.extend(_relocate_recovery_account(recovery))

        # Vacate current IDs before assigning preserved source IDs. This makes
        # swaps between two existing destination accounts collision-safe.
        for account in accounts:
            if not isinstance(account, dict):
                raise ValueError("Destination account merge entry is not an object")
            target_uid = _integer(account.get("target_uid"), "target_uid")
            target_userid = _integer(
                account.get("target_userid"), "target_userid", optional=True
            )
            staging_uid = _integer(
                account.get("staging_uid", target_uid), "staging_uid"
            )
            staging_userid = _integer(
                account.get("staging_userid", target_userid),
                "staging_userid",
                optional=True,
            )
            statements.extend(
                _move_existing_account(
                    target_uid, target_userid, staging_uid, staging_userid
                )
            )

        for account in accounts:
            source_uid = _integer(account.get("source_uid"), "source_uid")
            source_userid = _integer(
                account.get("source_userid"), "source_userid", optional=True
            )
            current_uid = _integer(
                account.get("staging_uid", account.get("target_uid")), "current_uid"
            )
            current_userid = _integer(
                account.get("staging_userid", account.get("target_userid")),
                "current_userid",
                optional=True,
            )
            statements.extend(
                _move_existing_account(
                    current_uid, current_userid, source_uid, source_userid
                )
            )
            merged_source_uids.add(source_uid)
    elif action != "not-required":
        raise ValueError(f"Unsupported bootstrap action: {action}")

    inserted = 0
    merged = 0
    for profile in _profile_rows(directory):
        uid = _integer(profile.get("uid"), "uid")
        userid = _integer(profile.get("userid"), "userid", optional=True)
        join_timestamp = _integer(profile.get("join_timestamp"), "join_timestamp")
        if join_timestamp < 0:
            raise ValueError("join_timestamp must be Unix seconds")
        roles = profile.get("roles")
        if not isinstance(roles, list):
            raise ValueError(f"Profile {uid} has no roles array")
        role_ids = [_integer(role, "role") for role in roles]
        values = {
            "userid": userid,
            "name": profile.get("name") if isinstance(profile.get("name"), str) else "",
            "email": profile.get("email") if isinstance(profile.get("email"), str) else "",
            "avatar": profile.get("avatar") if isinstance(profile.get("avatar"), str) else "",
            "bio": b64encode(
                (profile.get("bio") if isinstance(profile.get("bio"), str) else "").encode()
            ).decode(),
            "roles": ",".join(str(role) for role in role_ids),
            "discordid": _integer(profile.get("discordid"), "discordid", optional=True),
            "steamid": _integer(profile.get("steamid"), "steamid", optional=True),
            "truckersmpid": _integer(
                profile.get("truckersmpid"), "truckersmpid", optional=True
            ),
            "join_timestamp": join_timestamp,
            "mfa_secret": "",
            "tracker_in_use": TRACKER_IDS.get(str(profile.get("tracker", "")).lower(), 0),
        }
        if uid in merged_source_uids:
            assignments = ",".join(
                f"`{column}`={_sql_value(value)}"
                for column, value in values.items()
                if column != "mfa_secret"
            )
            statements.append(f"UPDATE `user` SET {assignments} WHERE `uid`={uid};")
            merged += 1
        else:
            columns = ["uid", *values]
            row = [uid, *values.values()]
            statements.append(
                "INSERT INTO `user` ("
                + ",".join(f"`{column}`" for column in columns)
                + ") VALUES ("
                + ",".join(_sql_value(value) for value in row)
                + ");"
            )
            inserted += 1
    statements.extend(
        [
            "SET @next_userid = (SELECT COALESCE(MAX(`userid`), 0) + 1 FROM `user` WHERE `userid` >= 0);",
            "UPDATE `settings` SET `sval`=@next_userid WHERE `skey`='nxtuserid';",
            "COMMIT;",
        ]
    )
    return "\n".join(statements) + "\n", {
        "state": "ready",
        "bootstrap_action": action,
        "inserted_accounts": inserted,
        "merged_accounts": merged,
        "preserved_passwords": merged,
        "mfa_reset_accounts": inserted,
        "database_time_zone": "+00:00",
    }
