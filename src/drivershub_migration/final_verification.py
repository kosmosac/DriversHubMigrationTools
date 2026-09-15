"""Verify a completed import against the stopped destination database."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

from .account_writer import _aio_command, _check_aio_writers
from .storage import write_json


REQUIRED_STAGES = (
    "accounts", "configuration", "user_state", "content", "applications",
    "events_challenges", "economy", "deliveries", "relationships",
    "polls_tasks", "economy_inventory",
)


def _expected_counts(journal: dict[str, object]) -> dict[str, int]:
    stages = journal["stages"]
    accounts = stages["accounts"]
    content = stages["content"]
    return {
        "imported_accounts": int(accounts.get("verified_accounts", 0)),
        "user_notes": int(stages["user_state"].get("global_notes", 0)),
        "role_history": int(stages["user_state"].get("role_history_records", 0)),
        "active_bans": int(stages["user_state"].get("active_bans", 0)),
        "ban_history": int(stages["user_state"].get("ban_history_records", 0)),
        "announcements": int(content.get("resources", {}).get("announcements", 0)),
        "downloads": int(content.get("resources", {}).get("downloads", 0)),
        "applications": int(stages["applications"].get("applications", 0)),
        "challenges": int(stages["events_challenges"].get("challenges", 0)),
        "events": int(stages["events_challenges"].get("events", 0)),
        "economy_balances": int(stages["economy"].get("balances", 0)),
        "economy_transactions": int(stages["economy"].get("transactions", 0)),
        "deliveries": int(stages["deliveries"].get("deliveries", 0)),
        "delivery_metadata": int(stages["deliveries"].get("deliveries", 0)),
        "delivery_placeholders": int(stages["deliveries"].get("detail_placeholders", 0)),
        "delivery_telemetry": int(stages["deliveries"].get("imported_telemetry", 0)),
        "challenge_links": int(stages["relationships"].get("challenge_delivery_links", 0)),
        "challenge_completions": int(stages["relationships"].get("challenge_completions", 0)),
        "pending_divisions": int(stages["relationships"].get("pending_division_requests", 0)),
        "polls": int(stages["polls_tasks"].get("polls", 0)),
        "poll_choices": int(stages["polls_tasks"].get("poll_choices", 0)),
        "poll_votes": int(stages["polls_tasks"].get("poll_votes", 0)),
        "tasks": int(stages["polls_tasks"].get("tasks", 0)),
        "economy_trucks": int(stages["economy_inventory"].get("trucks", 0)),
        "economy_garage_slots": int(stages["economy_inventory"].get("garage_slots", 0)),
        "economy_merchandise": int(stages["economy_inventory"].get("merchandise", 0)),
    }


COUNT_QUERIES = {
    "user_notes": "SELECT COUNT(*) FROM `user_note`",
    "role_history": "SELECT COUNT(*) FROM `user_role_history`",
    "active_bans": "SELECT COUNT(*) FROM `banned`",
    "ban_history": "SELECT COUNT(*) FROM `ban_history`",
    "announcements": "SELECT COUNT(*) FROM `announcement`",
    "downloads": "SELECT COUNT(*) FROM `downloads`",
    "applications": "SELECT COUNT(*) FROM `application`",
    "challenges": "SELECT COUNT(*) FROM `challenge`",
    "events": "SELECT COUNT(*) FROM `event`",
    "economy_balances": "SELECT COUNT(*) FROM `economy_balance`",
    "economy_transactions": "SELECT COUNT(*) FROM `economy_transaction`",
    "deliveries": "SELECT COUNT(*) FROM `dlog`",
    "delivery_metadata": "SELECT COUNT(*) FROM `dlog_meta`",
    "delivery_placeholders": "SELECT COUNT(*) FROM `dlog_meta` WHERE `note`='migration-import/pending-detail-enrichment'",
    "delivery_telemetry": "SELECT COUNT(*) FROM `telemetry`",
    "challenge_links": "SELECT COUNT(*) FROM `challenge_record`",
    "challenge_completions": "SELECT COUNT(*) FROM `challenge_completed`",
    "pending_divisions": "SELECT COUNT(*) FROM `division` WHERE `status`=0",
    "polls": "SELECT COUNT(*) FROM `poll`",
    "poll_choices": "SELECT COUNT(*) FROM `poll_choice`",
    "poll_votes": "SELECT COUNT(*) FROM `poll_vote`",
    "tasks": "SELECT COUNT(*) FROM `task`",
    "economy_trucks": "SELECT COUNT(*) FROM `economy_truck`",
    "economy_garage_slots": "SELECT COUNT(*) FROM `economy_garage`",
    "economy_merchandise": "SELECT COUNT(*) FROM `economy_merch`",
}

INTEGRITY_QUERIES = {
    "empty_migration_delivery_details": "SELECT COUNT(*) FROM `dlog` d JOIN `dlog_meta` m ON m.`logid`=d.`logid` WHERE d.`data`='' AND m.`note`='migration-import/pending-detail-enrichment'",
    "deliveries_without_metadata": "SELECT COUNT(*) FROM `dlog` d LEFT JOIN `dlog_meta` m ON m.`logid`=d.`logid` WHERE m.`logid` IS NULL",
    "metadata_without_delivery": "SELECT COUNT(*) FROM `dlog_meta` m LEFT JOIN `dlog` d ON d.`logid`=m.`logid` WHERE d.`logid` IS NULL",
    "challenge_links_without_delivery": "SELECT COUNT(*) FROM `challenge_record` r LEFT JOIN `dlog` d ON d.`logid`=r.`logid` WHERE d.`logid` IS NULL",
    "challenge_links_without_challenge": "SELECT COUNT(*) FROM `challenge_record` r LEFT JOIN `challenge` c ON c.`challengeid`=r.`challengeid` WHERE c.`challengeid` IS NULL",
    "challenge_completions_without_challenge": "SELECT COUNT(*) FROM `challenge_completed` r LEFT JOIN `challenge` c ON c.`challengeid`=r.`challengeid` WHERE c.`challengeid` IS NULL",
    "pending_divisions_without_delivery": "SELECT COUNT(*) FROM `division` v LEFT JOIN `dlog` d ON d.`logid`=v.`logid` WHERE v.`status`=0 AND d.`logid` IS NULL",
    "poll_choices_without_poll": "SELECT COUNT(*) FROM `poll_choice` c LEFT JOIN `poll` p ON p.`pollid`=c.`pollid` WHERE p.`pollid` IS NULL",
    "poll_votes_without_poll": "SELECT COUNT(*) FROM `poll_vote` v LEFT JOIN `poll` p ON p.`pollid`=v.`pollid` WHERE p.`pollid` IS NULL",
    "poll_votes_without_choice": "SELECT COUNT(*) FROM `poll_vote` v LEFT JOIN `poll_choice` c ON c.`choiceid`=v.`choiceid` WHERE c.`choiceid` IS NULL",
    "economy_trucks_without_garage_slot": "SELECT COUNT(*) FROM `economy_truck` t LEFT JOIN `economy_garage` g ON g.`slotid`=t.`slotid` WHERE t.`slotid` IS NOT NULL AND g.`slotid` IS NULL",
}


def _query_aio(target: Path, queries: dict[str, str], runner) -> dict[str, int]:
    sql = " UNION ALL ".join(
        f"SELECT '{name}',({query})" for name, query in queries.items()
    ) + ";"
    command = _aio_command(
        target, "exec", "-T", "mariadb", "sh", "-c",
        'exec mariadb --batch --raw --skip-column-names '
        '-u"$MARIADB_USER" -p"$MARIADB_PASSWORD" "$MARIADB_DATABASE"',
    )
    try:
        completed = runner(command, input=sql, check=True, capture_output=True, text=True)
        return {name: int(value) for name, value in (line.split("\t", 1) for line in completed.stdout.splitlines())}
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        raise ValueError("Unable to query the destination database") from exc


def _query_mariadb(queries: dict[str, str], database: dict[str, object]) -> dict[str, int]:
    try:
        import pymysql
    except ImportError as exc:
        raise ValueError("Install the project dependencies for direct MariaDB access") from exc
    parameters = {
        "host": database.get("host") or "127.0.0.1", "port": int(database.get("port") or 3306),
        "user": database.get("user"), "password": database.get("password"),
        "database": database.get("database"), "connect_timeout": 10,
    }
    if database.get("unix_socket"):
        parameters["unix_socket"] = database["unix_socket"]
    if not parameters["user"] or not parameters["database"]:
        raise ValueError("Direct MariaDB mode requires a database user and database name")
    try:
        connection = pymysql.connect(**parameters)
        with connection:
            with connection.cursor() as cursor:
                result = {}
                for name, query in queries.items():
                    cursor.execute(query)
                    result[name] = int(cursor.fetchone()[0])
                return result
    except (pymysql.MySQLError, TypeError, ValueError) as exc:
        raise ValueError("Unable to query the destination database") from exc


def verify_target(directory: Path, target_directory: Path | None, *, mode: str, database: dict[str, object], writers_stopped: bool, runner=subprocess.run) -> dict[str, object]:
    path = directory / "import-journal.json"
    try:
        journal = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Unable to read the import journal") from exc
    stages = journal.get("stages")
    if not isinstance(stages, dict):
        raise ValueError("The import journal has no stages")
    incomplete = [name for name in REQUIRED_STAGES if not isinstance(stages.get(name), dict) or stages[name].get("state") != "complete"]
    if incomplete:
        raise ValueError("Complete these import stages first: " + ", ".join(incomplete))

    if mode == "aio":
        if target_directory is None:
            raise ValueError("AIO mode requires the target deployment directory")
        target = target_directory.resolve()
        _check_aio_writers(target, runner)
        query = lambda values: _query_aio(target, values, runner)
    elif mode == "mariadb":
        if not writers_stopped:
            raise ValueError("Direct MariaDB mode requires --writers-stopped")
        query = lambda values: _query_mariadb(values, database)
    else:
        raise ValueError("DRIVERSHUB_TARGET_MODE must be aio or mariadb")

    expected = _expected_counts(journal)
    actual = query(COUNT_QUERIES)
    imported_uids = [int(account["target_uid"]) for account in json.loads((directory / "import-plan.json").read_text(encoding="utf-8"))["accounts"]]
    uid_list = ",".join(map(str, imported_uids)) or "NULL"
    actual["imported_accounts"] = query({"imported_accounts": f"SELECT COUNT(*) FROM `user` WHERE `uid` IN ({uid_list})"})["imported_accounts"]
    mismatches = [
        {"resource": name, "expected": value, "actual": actual.get(name)}
        for name, value in expected.items() if actual.get(name) != value
    ]
    integrity = query(INTEGRITY_QUERIES)
    violations = {name: value for name, value in integrity.items() if value != 0}
    state = "complete" if not mismatches and not violations else "failed"
    report = {
        "format_version": 1, "state": state, "expected": expected, "actual": actual,
        "count_mismatches": mismatches, "integrity_violations": violations,
        "writers_stopped": True,
    }
    write_json(directory / "target-verification.json", report)
    journal["state"] = state
    journal["final_verification"] = {"state": state, "count_mismatches": len(mismatches), "integrity_violations": len(violations)}
    write_json(path, journal)
    return report
