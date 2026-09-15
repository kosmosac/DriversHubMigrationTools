"""Build relationships that depend on imported deliveries."""

from __future__ import annotations

from pathlib import Path

from .account_import import _integer, _sql_value
from .content_import import _records


def _userid(value: object, field: str) -> int:
    if not isinstance(value, dict):
        raise ValueError(f"{field} is not an object")
    return _integer(value.get("userid"), f"{field}.userid")


def build_relationship_stage(directory: Path) -> tuple[str, dict[str, object]]:
    deliveries = _records(directory, "deliveries")
    delivery_ids = {_integer(row.get("logid"), "delivery logid") for row in deliveries}
    challenges = _records(directory, "challenges-details")
    divisions = _records(directory, "division-pending")
    statements = ["SET time_zone = '+00:00';", "START TRANSACTION;"]
    challenge_links = completions = 0
    seen_links: set[tuple[int, int, int]] = set()
    seen_completions: set[tuple[int, int]] = set()
    for challenge in challenges:
        challengeid = _integer(challenge.get("challengeid"), "challengeid")
        records = challenge.get("record")
        if not isinstance(records, list):
            raise ValueError(f"Challenge {challengeid} has invalid records")
        for record in records:
            if not isinstance(record, dict):
                raise ValueError(f"Challenge {challengeid} has an invalid record")
            userid = _userid(record.get("user"), "challenge user")
            logids = record.get("dlog")
            if not isinstance(logids, list):
                raise ValueError(f"Challenge {challengeid} has invalid delivery links")
            for raw_logid in logids:
                logid = _integer(raw_logid, "challenge delivery logid")
                if logid not in delivery_ids:
                    raise ValueError(f"Challenge {challengeid} references unavailable delivery {logid}")
                key = (userid, challengeid, logid)
                if key in seen_links:
                    continue
                seen_links.add(key)
                statements.append(
                    "INSERT INTO `challenge_record` (`userid`,`challengeid`,`logid`,`timestamp`) "
                    f"SELECT {userid},{challengeid},{logid},`timestamp` FROM `dlog` WHERE `logid`={logid};"
                )
                challenge_links += 1
            if bool(record.get("is_completed")):
                key = (userid, challengeid)
                if key in seen_completions:
                    raise ValueError(f"Challenge {challengeid} has duplicate completion for user {userid}")
                seen_completions.add(key)
                points = _integer(record.get("points"), "challenge completion points")
                timestamp = _integer(record.get("complete_timestamp"), "challenge completion timestamp")
                statements.append(
                    "INSERT INTO `challenge_completed` (`userid`,`challengeid`,`points`,`timestamp`) VALUES ("
                    + ",".join(_sql_value(value) for value in [userid, challengeid, points, timestamp])
                    + ");"
                )
                completions += 1
    for row in divisions:
        logid = _integer(row.get("logid"), "division logid")
        if logid not in delivery_ids:
            raise ValueError(f"Division request references unavailable delivery {logid}")
        divisionid = _integer(row.get("divisionid"), "divisionid")
        userid = _userid(row.get("user"), "division user")
        statements.append(
            "INSERT INTO `division` (`logid`,`divisionid`,`userid`,`distance`,`request_timestamp`,`status`,`update_timestamp`,`update_staff_userid`,`message`) "
            f"SELECT {logid},{divisionid},{userid},`distance`,`timestamp`,0,0,-1,'' FROM `dlog` WHERE `logid`={logid};"
        )
    statements.append("COMMIT;")
    return "\n".join(statements) + "\n", {
        "state": "ready", "challenge_delivery_links": challenge_links,
        "challenge_completions": completions, "pending_division_requests": len(divisions),
        "relationship_timestamp_source": "referenced delivery Unix timestamp",
        "database_time_zone": "+00:00",
    }
