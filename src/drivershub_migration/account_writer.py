"""Execute the transactional account import after explicit safety checks."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
from typing import Callable

from .account_import import build_account_stage
from .storage import write_json
from .target import preflight_target


WRITER_SERVICES = {"backend", "bannergen", "db-init"}


def _journal_path(directory: Path) -> Path:
    return directory / "import-journal.json"


def _ensure_not_complete(directory: Path) -> None:
    path = _journal_path(directory)
    if not path.exists():
        return
    try:
        journal = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("The existing import journal is invalid") from exc
    accounts = journal.get("stages", {}).get("accounts", {})
    if isinstance(accounts, dict) and accounts.get("state") == "complete":
        raise ValueError("The account import is already complete")


def _aio_command(target: Path, *arguments: str) -> list[str]:
    return [
        "docker",
        "compose",
        "--project-directory",
        str(target),
        *arguments,
    ]


def _check_aio_writers(
    target: Path, runner: Callable[..., subprocess.CompletedProcess[str]]
) -> None:
    try:
        completed = runner(
            _aio_command(target, "ps", "--status", "running", "--services"),
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError("Unable to inspect destination services") from exc
    running = {line.strip() for line in completed.stdout.splitlines() if line.strip()}
    unsafe = sorted(running & WRITER_SERVICES)
    if unsafe:
        raise ValueError(
            "Stop destination writer services before import: " + ", ".join(unsafe)
        )
    if "mariadb" not in running:
        raise ValueError("The destination MariaDB service must be running")


def _execute_aio(
    target: Path,
    sql: str,
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> None:
    command = _aio_command(
        target,
        "exec",
        "-T",
        "mariadb",
        "sh",
        "-c",
        'exec mariadb --batch --raw --skip-column-names '
        '-u"$MARIADB_USER" -p"$MARIADB_PASSWORD" "$MARIADB_DATABASE"',
    )
    try:
        runner(command, input=sql, check=True, capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = (
            exc.stderr.strip()
            if isinstance(exc, subprocess.CalledProcessError) and exc.stderr
            else str(exc)
        )
        raise ValueError(f"The destination rejected the account transaction: {detail}") from exc


def _expected_uids(directory: Path) -> list[int]:
    try:
        plan = json.loads((directory / "import-plan.json").read_text(encoding="utf-8"))
        accounts = plan["accounts"]
        uids = [account["target_uid"] for account in accounts]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ValueError("Unable to read expected destination account IDs") from exc
    if not all(isinstance(uid, int) and not isinstance(uid, bool) for uid in uids):
        raise ValueError("The import plan contains an invalid destination UID")
    return uids


def _verify_aio_accounts(
    target: Path,
    expected_uids: list[int],
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> int:
    if not expected_uids:
        return 0
    identifiers = ",".join(str(uid) for uid in expected_uids)
    query = f"SELECT COUNT(DISTINCT uid) FROM user WHERE uid IN ({identifiers});"
    command = _aio_command(
        target,
        "exec",
        "-T",
        "mariadb",
        "sh",
        "-c",
        'exec mariadb --batch --raw --skip-column-names '
        '-u"$MARIADB_USER" -p"$MARIADB_PASSWORD" "$MARIADB_DATABASE" '
        f'-e "{query}"',
    )
    try:
        completed = runner(command, check=True, capture_output=True, text=True)
        return int(completed.stdout.strip())
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        raise ValueError("Unable to verify imported destination accounts") from exc


def _execute_mariadb(sql: str, database: dict[str, object]) -> None:
    try:
        import pymysql
        import pymysql.cursors
    except ImportError as exc:
        raise ValueError("Install the project dependencies for direct MariaDB access") from exc
    parameters = {
        "host": database.get("host") or "127.0.0.1",
        "port": int(database.get("port") or 3306),
        "user": database.get("user"),
        "password": database.get("password"),
        "database": database.get("database"),
        "connect_timeout": 10,
        "autocommit": False,
    }
    if database.get("unix_socket"):
        parameters["unix_socket"] = database["unix_socket"]
    if not parameters["user"] or not parameters["database"]:
        raise ValueError("Direct MariaDB mode requires a database user and database name")
    try:
        connection = pymysql.connect(**parameters)
        with connection:
            with connection.cursor() as cursor:
                for statement in sql.splitlines():
                    if statement.strip() not in {"START TRANSACTION;", "COMMIT;"}:
                        cursor.execute(statement)
            connection.commit()
    except (pymysql.MySQLError, ValueError) as exc:
        raise ValueError(f"The destination rejected the account transaction: {exc}") from exc


def _verify_mariadb_accounts(
    expected_uids: list[int], database: dict[str, object]
) -> int:
    if not expected_uids:
        return 0
    try:
        import pymysql
    except ImportError as exc:
        raise ValueError("Install the project dependencies for direct MariaDB access") from exc
    parameters = {
        "host": database.get("host") or "127.0.0.1",
        "port": int(database.get("port") or 3306),
        "user": database.get("user"),
        "password": database.get("password"),
        "database": database.get("database"),
        "connect_timeout": 10,
    }
    if database.get("unix_socket"):
        parameters["unix_socket"] = database["unix_socket"]
    identifiers = ",".join(["%s"] * len(expected_uids))
    try:
        connection = pymysql.connect(**parameters)
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT COUNT(DISTINCT uid) FROM user WHERE uid IN ({identifiers})",
                    expected_uids,
                )
                row = cursor.fetchone()
        return int(row[0])
    except (pymysql.MySQLError, TypeError, ValueError) as exc:
        raise ValueError("Unable to verify imported destination accounts") from exc


def import_accounts(
    migration_directory: Path,
    target_directory: Path | None,
    *,
    mode: str,
    database: dict[str, object],
    backup_confirmed: bool,
    writers_stopped: bool,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, object]:
    if not backup_confirmed:
        raise ValueError("The account import requires --backup-confirmed")
    _ensure_not_complete(migration_directory)

    if mode == "aio":
        if target_directory is None:
            raise ValueError("AIO mode requires the target deployment directory")
        target = target_directory.resolve()
        preflight_target(
            migration_directory, target, mode=mode, database=database, runner=runner
        )
        _check_aio_writers(target, runner)
    elif mode == "mariadb":
        if not writers_stopped:
            raise ValueError("Direct MariaDB mode requires --writers-stopped")
        preflight_target(
            migration_directory, None, mode=mode, database=database, runner=runner
        )
        target = None
    else:
        raise ValueError("DRIVERSHUB_TARGET_MODE must be aio or mariadb")

    sql, summary = build_account_stage(migration_directory)
    expected_uids = _expected_uids(migration_directory)
    journal = {
        "format_version": 1,
        "state": "in-progress",
        "target_mode": mode,
        "stages": {"accounts": {**summary, "state": "in-progress"}},
    }
    write_json(_journal_path(migration_directory), journal)
    try:
        if mode == "aio":
            _execute_aio(target, sql, runner)  # type: ignore[arg-type]
            verified_accounts = _verify_aio_accounts(
                target, expected_uids, runner  # type: ignore[arg-type]
            )
        else:
            _execute_mariadb(sql, database)
            verified_accounts = _verify_mariadb_accounts(expected_uids, database)
        if verified_accounts != len(expected_uids):
            raise ValueError(
                "Destination account verification failed: "
                f"expected {len(expected_uids)}, found {verified_accounts}"
            )
    except ValueError as exc:
        journal["state"] = "failed"
        journal["stages"]["accounts"]["state"] = "failed"
        journal["stages"]["accounts"]["error"] = str(exc)
        write_json(_journal_path(migration_directory), journal)
        raise

    journal["state"] = "partial"
    journal["stages"]["accounts"]["state"] = "complete"
    journal["stages"]["accounts"]["verified_accounts"] = verified_accounts
    write_json(_journal_path(migration_directory), journal)
    return journal
