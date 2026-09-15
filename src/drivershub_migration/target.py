"""Read-only preflight checks for Drivers Hub destinations."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
from typing import Callable

from .import_plan import create_import_plan
from .storage import write_json


USER_QUERY = (
    "SELECT JSON_OBJECT('uid',uid,'userid',userid,'name',name,'email',email,"
    "'discordid',discordid,'steamid',steamid,'truckersmpid',truckersmpid,"
    "'roles',roles) FROM user ORDER BY uid;"
)

USER_COLUMNS = (
    "uid",
    "userid",
    "name",
    "email",
    "discordid",
    "steamid",
    "truckersmpid",
    "roles",
)


def _identity(value: object, *, email: bool = False) -> object | None:
    if value is None or isinstance(value, bool):
        return None
    if email:
        return value.strip().lower() if isinstance(value, str) and "@" in value else None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _bootstrap_resolution(
    source_accounts: list[dict[str, object]],
    target_accounts: list[dict[str, object]],
) -> dict[str, object]:
    if not target_accounts:
        return {"state": "not-required", "reason": "The destination has no account."}
    if len(target_accounts) != 1:
        return {
            "state": "manual-decision-required",
            "reason": "The destination contains more than one account.",
        }

    bootstrap = target_accounts[0]
    matches: dict[object, set[str]] = {}
    for source in source_accounts:
        if not source.get("is_administrator"):
            continue
        for field in ("steamid", "discordid", "email"):
            source_value = _identity(source.get(field), email=field == "email")
            target_value = _identity(bootstrap.get(field), email=field == "email")
            if source_value is not None and source_value == target_value:
                matches.setdefault(source["source_uid"], set()).add(field)

    if len(matches) == 1:
        source_uid, fields = next(iter(matches.items()))
        return {
            "state": "ready",
            "action": "merge-with-source-administrator",
            "source_uid": source_uid,
            "matched_by": sorted(fields),
            "target_uid": bootstrap.get("uid"),
            "target_userid": bootstrap.get("userid"),
        }
    if len(matches) > 1:
        return {
            "state": "manual-decision-required",
            "reason": "Bootstrap identities match different source administrators.",
            "candidate_source_uids": sorted(matches),
        }

    used_uids = {
        value
        for account in [*source_accounts, *target_accounts]
        if isinstance((value := account.get("target_uid", account.get("uid"))), int)
    }
    used_userids = {
        value
        for account in [*source_accounts, *target_accounts]
        if isinstance((value := account.get("target_userid", account.get("userid"))), int)
        and value >= 0
    }
    return {
        "state": "ready",
        "action": "retain-as-recovery-account",
        "original_uid": bootstrap.get("uid"),
        "original_userid": bootstrap.get("userid"),
        "replacement_uid": max(used_uids, default=0) + 1,
        "replacement_userid": max(used_userids, default=0) + 1,
    }


def _compose_command(target: Path) -> list[str]:
    return [
        "docker",
        "compose",
        "--project-directory",
        str(target),
        "exec",
        "-T",
        "mariadb",
        "sh",
        "-c",
        'exec mariadb --batch --raw --skip-column-names '
        '-u"$MARIADB_USER" -p"$MARIADB_PASSWORD" "$MARIADB_DATABASE" '
        f"-e \"{USER_QUERY}\"",
    ]


def _read_aio_accounts(
    target: Path,
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> list[dict[str, object]]:
    if not (target / "compose.yaml").is_file() or not (target / ".env").is_file():
        raise ValueError("The target is not an initialized Drivers Hub Docker AIO directory")
    try:
        completed = runner(
            _compose_command(target),
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = exc.stderr.strip() if isinstance(exc, subprocess.CalledProcessError) and exc.stderr else str(exc)
        raise ValueError(f"Unable to read the destination database: {detail}") from exc

    accounts = []
    try:
        for line in completed.stdout.splitlines():
            if line.strip():
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError("Destination user row is not an object")
                accounts.append(value)
    except json.JSONDecodeError as exc:
        raise ValueError("The destination database returned invalid account data") from exc
    return accounts


def _read_mariadb_accounts(config: dict[str, object]) -> list[dict[str, object]]:
    try:
        import pymysql
        import pymysql.cursors
    except ImportError as exc:
        raise ValueError("Install the project dependencies to use direct MariaDB access") from exc
    parameters = {
        "host": config.get("host") or "127.0.0.1",
        "port": int(config.get("port") or 3306),
        "user": config.get("user"),
        "password": config.get("password"),
        "database": config.get("database"),
        "cursorclass": pymysql.cursors.DictCursor,
        "connect_timeout": 10,
    }
    if config.get("unix_socket"):
        parameters["unix_socket"] = config["unix_socket"]
    if not parameters["user"] or not parameters["database"]:
        raise ValueError("Direct MariaDB mode requires a database user and database name")
    try:
        connection = pymysql.connect(**parameters)
        with connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT " + ",".join(USER_COLUMNS) + " FROM user ORDER BY uid")
                return [dict(row) for row in cursor.fetchall()]
    except pymysql.MySQLError as exc:
        raise ValueError(f"Unable to read the destination database: {exc}") from exc


def preflight_target(
    migration_directory: Path,
    target_directory: Path | None = None,
    *,
    mode: str = "aio",
    database: dict[str, object] | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, object]:
    plan = create_import_plan(migration_directory)
    if plan["state"] != "complete":
        raise ValueError("The identity import plan contains conflicts")
    if mode == "aio":
        if target_directory is None:
            raise ValueError("AIO mode requires the target deployment directory")
        target = target_directory.resolve()
        target_accounts = _read_aio_accounts(target, runner)
        target_description = str(target)
    elif mode == "mariadb":
        target_accounts = _read_mariadb_accounts(database or {})
        target_description = "direct-mariadb"
    else:
        raise ValueError("DRIVERSHUB_TARGET_MODE must be aio or mariadb")

    source_accounts = plan["accounts"]
    source_uids = {account["target_uid"] for account in source_accounts}
    source_userids = {
        account["target_userid"]
        for account in source_accounts
        if isinstance(account["target_userid"], int)
        and account["target_userid"] >= 0
    }
    collisions = []
    for account in target_accounts:
        fields = []
        if account.get("uid") in source_uids:
            fields.append("uid")
        if account.get("userid") in source_userids:
            fields.append("userid")
        if fields:
            collisions.append(
                {
                    "target_uid": account.get("uid"),
                    "target_userid": account.get("userid"),
                    "fields": fields,
                }
            )

    report = {
        "format_version": 1,
        "state": "action-required" if target_accounts else "complete",
        "target_mode": mode,
        "target": target_description,
        "source_accounts": len(source_accounts),
        "target_accounts": target_accounts,
        "collisions": collisions,
        "bootstrap": _bootstrap_resolution(source_accounts, target_accounts),
        "required_action": (
            "Approve or change the proposed bootstrap account action before import."
            if target_accounts
            else None
        ),
    }
    write_json(migration_directory / "target-preflight.json", report)
    return report
