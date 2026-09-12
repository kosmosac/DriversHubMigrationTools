"""Read-only preflight checks for a Drivers Hub Docker AIO destination."""

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


def preflight_target(
    migration_directory: Path,
    target_directory: Path,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, object]:
    plan = create_import_plan(migration_directory)
    if plan["state"] != "complete":
        raise ValueError("The identity import plan contains conflicts")
    target = target_directory.resolve()
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

    target_accounts = []
    try:
        for line in completed.stdout.splitlines():
            if line.strip():
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError("Destination user row is not an object")
                target_accounts.append(value)
    except json.JSONDecodeError as exc:
        raise ValueError("The destination database returned invalid account data") from exc

    source_accounts = plan["accounts"]
    source_uids = {account["target_uid"] for account in source_accounts}
    source_userids = {
        account["target_userid"]
        for account in source_accounts
        if account["target_userid"] >= 0
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
        "target_directory": str(target),
        "source_accounts": len(source_accounts),
        "target_accounts": target_accounts,
        "collisions": collisions,
        "required_action": (
            "Select how each existing destination account is preserved or merged before import."
            if target_accounts
            else None
        ),
    }
    write_json(migration_directory / "target-preflight.json", report)
    return report
