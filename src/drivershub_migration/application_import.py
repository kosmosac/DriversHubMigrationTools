"""Build the application import transaction."""

from __future__ import annotations

import json
from pathlib import Path

from .account_import import _integer, _sql_value
from .content_import import _compressed, _records, _timestamp


def build_application_stage(directory: Path) -> tuple[str, dict[str, object]]:
    applications = _records(directory, "applications-details")
    statements = ["SET time_zone = '+00:00';", "START TRANSACTION;"]
    pending = 0
    for row in applications:
        creator = row.get("creator")
        staff = row.get("last_respond_staff")
        answers = row.get("application")
        if not isinstance(creator, dict) or not isinstance(staff, dict):
            raise ValueError("Application user information is invalid")
        if not isinstance(answers, dict):
            raise ValueError("Application answers are not an object")
        status = _integer(row.get("status"), "application status")
        if status == 0:
            pending += 1
        staff_userid = _integer(
            staff.get("userid"), "application staff userid", optional=True
        )
        values = [
            _integer(row.get("applicationid"), "applicationid"),
            _integer(row.get("type"), "application type"),
            _integer(creator.get("uid"), "application creator uid"),
            _compressed(json.dumps(answers, separators=(",", ":"), ensure_ascii=False), "application answers"),
            status,
            _timestamp(row.get("submit_timestamp"), "application submit timestamp"),
            staff_userid if staff_userid is not None else -1,
            _timestamp(row.get("respond_timestamp"), "application response timestamp"),
        ]
        statements.append(
            "INSERT INTO `application` (`applicationid`,`application_type`,`uid`,`data`,`status`,`submit_timestamp`,`update_staff_userid`,`update_staff_timestamp`) VALUES ("
            + ",".join(_sql_value(value) for value in values)
            + ");"
        )
    statements.append("COMMIT;")
    return "\n".join(statements) + "\n", {
        "state": "ready",
        "applications": len(applications),
        "pending_applications": pending,
        "database_time_zone": "+00:00",
    }
