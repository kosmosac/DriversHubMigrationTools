"""Small database adapter for post-migration live updates."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable

from .account_writer import _aio_command, _execute_aio, _execute_mariadb


def query_rows(
    sql: str,
    target_directory: Path | None,
    *,
    mode: str,
    database: dict[str, object],
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> list[list[str]]:
    if mode == "aio":
        if target_directory is None:
            raise ValueError("AIO mode requires the target deployment directory")
        target = target_directory.resolve()
        command = _aio_command(
            target,
            "exec", "-T", "mariadb", "sh", "-c",
            'exec mariadb --batch --raw --skip-column-names '
            '-u"$MARIADB_USER" -p"$MARIADB_PASSWORD" "$MARIADB_DATABASE"',
        )
        try:
            completed = runner(command, input=sql, check=True, capture_output=True, text=True)
        except (OSError, subprocess.CalledProcessError) as exc:
            detail = exc.stderr.strip() if isinstance(exc, subprocess.CalledProcessError) and exc.stderr else str(exc)
            raise ValueError(f"Unable to query the destination database: {detail}") from exc
        return [line.split("\t") for line in completed.stdout.splitlines() if line]
    if mode != "mariadb":
        raise ValueError("DRIVERSHUB_TARGET_MODE must be aio or mariadb")
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
                cursor.execute(sql)
                return [["NULL" if value is None else str(value) for value in row] for row in cursor.fetchall()]
    except pymysql.MySQLError as exc:
        raise ValueError(f"Unable to query the destination database: {exc}") from exc


def execute_live(
    sql: str,
    target_directory: Path | None,
    *,
    mode: str,
    database: dict[str, object],
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> None:
    if mode == "aio":
        if target_directory is None:
            raise ValueError("AIO mode requires the target deployment directory")
        _execute_aio(target_directory.resolve(), sql, runner)
    elif mode == "mariadb":
        _execute_mariadb(sql, database)
    else:
        raise ValueError("DRIVERSHUB_TARGET_MODE must be aio or mariadb")
