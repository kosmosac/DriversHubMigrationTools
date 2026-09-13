"""Create a non-writing identity and claim plan for destination import."""

from __future__ import annotations

import json
from pathlib import Path

from .storage import write_json
from .verify import verify_export


def _identifier(value: object) -> int | None:
    if isinstance(value, bool) or value is None or value in {"", "NULL"}:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def create_import_plan(directory: Path) -> dict[str, object]:
    verification = verify_export(directory)
    if verification["integrity"] != "valid" or verification["export"] != "complete":
        raise ValueError("The migration directory did not pass verification")

    profiles_path = directory / "normalized" / "profiles.json"
    try:
        document = json.loads(profiles_path.read_text(encoding="utf-8"))
        profiles = document["records"]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ValueError("The export does not contain valid normalized profiles") from exc
    if not isinstance(profiles, list):
        raise ValueError("The normalized profile records are not a list")

    accounts: list[dict[str, object]] = []
    conflicts: list[dict[str, object]] = []
    seen: dict[str, dict[object, int]] = {
        "uid": {},
        "userid": {},
        "steamid": {},
        "discordid": {},
        "email": {},
    }
    for profile in profiles:
        if not isinstance(profile, dict):
            conflicts.append({"field": "profile", "error": "Profile is not an object"})
            continue
        uid = _identifier(profile.get("uid"))
        userid = profile.get("userid")
        if uid is None or not isinstance(userid, int):
            conflicts.append(
                {"field": "identity", "error": "Profile has no valid uid or userid"}
            )
            continue
        steamid = _identifier(profile.get("steamid"))
        discordid = _identifier(profile.get("discordid"))
        truckersmpid = _identifier(profile.get("truckersmpid"))
        raw_email = profile.get("email")
        email = raw_email.strip() if isinstance(raw_email, str) and "@" in raw_email else None
        values = {
            "uid": uid,
            "userid": userid,
            "steamid": steamid,
            "discordid": discordid,
            "email": email.lower() if email is not None else None,
        }
        for field, value in values.items():
            if value is None or (field == "userid" and value < 0):
                continue
            previous = seen[field].get(value)
            if previous is not None and previous != uid:
                conflicts.append(
                    {"field": field, "value": value, "uids": [previous, uid]}
                )
            else:
                seen[field][value] = uid
        claim_methods = []
        if steamid is not None:
            claim_methods.append("steam")
        if discordid is not None:
            claim_methods.append("discord")
        if email is not None:
            claim_methods.append("email")
        accounts.append(
            {
                "source_uid": uid,
                "target_uid": uid,
                "source_userid": userid,
                "target_userid": userid,
                "name": profile.get("name"),
                "claim_methods": claim_methods,
                "steamid": steamid,
                "discordid": discordid,
                "truckersmpid": truckersmpid,
                "email": email,
                "password": "not-imported",
                "mfa": "enroll-again",
                "state": "claimable" if claim_methods else "manual-recovery-required",
            }
        )

    plan = {
        "format_version": 1,
        "state": "blocked" if conflicts else "complete",
        "identity_policy": "preserve-source-ids",
        "claim_policy": "steam-discord-or-email",
        "accounts": sorted(accounts, key=lambda account: account["source_uid"]),
        "summary": {
            "accounts": len(accounts),
            "claimable": sum(account["state"] == "claimable" for account in accounts),
            "manual_recovery_required": sum(
                account["state"] == "manual-recovery-required" for account in accounts
            ),
            "conflicts": len(conflicts),
        },
        "conflicts": conflicts,
        "destination_preconditions": [
            "The destination is a fresh installation.",
            "Existing destination uid and userid values do not conflict with source values.",
            "The bootstrap administrator is handled explicitly before user insertion.",
            "Steam and Discord authentication are configured before account claims begin.",
        ],
    }
    write_json(directory / "import-plan.json", plan)
    return plan
