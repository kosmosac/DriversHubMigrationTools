"""Validate the complete import against the destination without committing it."""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
from typing import Callable

from .account_import import build_account_stage
from .account_writer import _aio_command, _check_aio_writers
from .application_import import build_application_stage
from .configuration_plan import create_configuration_plan
from .configuration_writer import _database_sql, _merge_backend
from .content_import import build_content_stage
from .delivery_import import build_delivery_stage
from .economy_import import build_economy_stage
from .economy_inventory_import import build_economy_inventory_stage
from .event_challenge_import import build_event_challenge_stage
from .poll_task_import import build_poll_task_stage
from .relationship_import import build_relationship_stage
from .user_state_import import build_user_state_stage


TRANSACTIONAL_ENGINES = {"INNODB", "XTRADB"}


def _read_object(path: Path, description: str) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Unable to read {description}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"The {description} is not an object")
    return value


def _transaction_body(sql: str) -> list[str]:
    wrappers = {"SET time_zone = '+00:00';", "START TRANSACTION;", "COMMIT;"}
    return [line for line in sql.splitlines() if line.strip() and line.strip() not in wrappers]


def _configuration_validation(
    directory: Path, destination_config: Path
) -> tuple[dict[str, object], str]:
    target = _read_object(destination_config, "destination backend configuration")
    plan = create_configuration_plan(directory)
    backend = plan.get("backend", {})
    portable = backend.get("portable", {}) if isinstance(backend, dict) else {}
    if not isinstance(portable, dict):
        raise ValueError("The portable backend configuration is invalid")
    merged = _merge_backend(portable, target)
    # This also reads and compresses every selected branding asset. The SQL is
    # generated to validate its values but is not executed because the settings
    # insert uses an implicit auto-increment value that a rollback cannot undo.
    sql, assets = _database_sql(directory, plan, merged)
    json.dumps(merged, indent=4, ensure_ascii=False)
    return {
        "state": "ready",
        "portable_backend_values": len(portable),
        "branding_assets": assets,
    }, sql


def _stage_sql(
    directory: Path, convert_personal_notes: bool, configuration_sql: str
) -> tuple[str, dict[str, object]]:
    builders = (
        ("accounts", lambda: build_account_stage(directory)),
        ("user_state", lambda: build_user_state_stage(directory, convert_personal_notes_to_global=convert_personal_notes)),
        ("content", lambda: build_content_stage(directory)),
        ("applications", lambda: build_application_stage(directory)),
        ("events_challenges", lambda: build_event_challenge_stage(directory)),
        ("polls_tasks", lambda: build_poll_task_stage(directory)),
        ("economy", lambda: build_economy_stage(directory)),
        ("economy_inventory", lambda: build_economy_inventory_stage(directory)),
        ("deliveries", lambda: build_delivery_stage(directory)),
        ("relationships", lambda: build_relationship_stage(directory)),
    )
    statements = [
        "SET time_zone = '+00:00';",
        "CREATE TEMPORARY TABLE `_migration_settings` LIKE `settings`;",
        "CREATE TEMPORARY TABLE `_migration_ext_assets` LIKE `ext_assets`;",
        "START TRANSACTION;",
    ]
    configuration_body = _transaction_body(configuration_sql)
    statements.extend(
        line.replace("`settings`", "`_migration_settings`").replace(
            "`ext_assets`", "`_migration_ext_assets`"
        )
        for line in configuration_body
    )
    summaries: dict[str, object] = {}
    for name, builder in builders:
        sql, summary = builder()
        statements.extend(_transaction_body(sql))
        summaries[name] = summary
    statements.append("ROLLBACK;")
    return "\n".join(statements) + "\n", summaries


def _execute_aio_validation(
    target: Path,
    sql: str,
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> None:
    command = _aio_command(
        target, "exec", "-T", "mariadb", "sh", "-c",
        'exec mariadb --batch --raw --skip-column-names '
        '-u"$MARIADB_USER" -p"$MARIADB_PASSWORD" "$MARIADB_DATABASE"',
    )
    try:
        runner(command, input=sql, check=True, capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = exc.stderr.strip() if isinstance(exc, subprocess.CalledProcessError) and exc.stderr else str(exc)
        raise ValueError(f"The destination rejected the simulated import: {detail}") from exc


def _aio_rows(
    target: Path,
    query: str,
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> list[list[str]]:
    command = _aio_command(
        target, "exec", "-T", "mariadb", "sh", "-c",
        'exec mariadb --batch --raw --skip-column-names '
        '-u"$MARIADB_USER" -p"$MARIADB_PASSWORD" "$MARIADB_DATABASE" '
        f'-e "{query}"',
    )
    try:
        completed = runner(command, check=True, capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError("Unable to inspect destination transaction safety") from exc
    return [line.split("\t") for line in completed.stdout.splitlines() if line]


def _safety_queries(sql: str) -> tuple[str, str, set[str]]:
    tables = {
        match.group(1)
        for match in re.finditer(
            r"(?:INSERT INTO|UPDATE|DELETE FROM)\s+`([^`]+)`", sql,
            flags=re.IGNORECASE,
        )
        if not match.group(1).startswith("_migration_")
    } | {"settings", "ext_assets"}
    quoted = ",".join("'" + table.replace("'", "''") + "'" for table in sorted(tables))
    engines = (
        "SELECT TABLE_NAME,COALESCE(ENGINE,'') FROM information_schema.TABLES "
        "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_TYPE='BASE TABLE' "
        f"AND TABLE_NAME IN ({quoted}) ORDER BY TABLE_NAME;"
    )
    triggers = (
        "SELECT TRIGGER_NAME,EVENT_OBJECT_TABLE FROM information_schema.TRIGGERS "
        f"WHERE TRIGGER_SCHEMA=DATABASE() AND EVENT_OBJECT_TABLE IN ({quoted}) "
        "ORDER BY TRIGGER_NAME;"
    )
    return engines, triggers, tables


def _validate_safety_rows(
    engine_rows: list[list[str]], trigger_rows: list[list[str]], expected: set[str]
) -> dict[str, object]:
    engines = {row[0]: row[1].upper() for row in engine_rows if len(row) >= 2}
    missing = sorted(expected - set(engines))
    unsafe = {name: engine for name, engine in engines.items() if engine not in TRANSACTIONAL_ENGINES}
    if missing:
        raise ValueError("Destination schema is missing import tables: " + ", ".join(missing))
    if unsafe:
        detail = ", ".join(f"{name} ({engine or 'unknown'})" for name, engine in sorted(unsafe.items()))
        raise ValueError("Rollback validation requires transactional destination tables: " + detail)
    if trigger_rows:
        detail = ", ".join(f"{row[0]} on {row[1]}" for row in trigger_rows if len(row) >= 2)
        raise ValueError("Rollback validation does not support triggers on imported tables: " + detail)
    return {"state": "ready", "tables": len(expected), "engines": sorted(set(engines.values())), "triggers": 0}


def _inspect_aio_safety(
    target: Path, sql: str,
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> dict[str, object]:
    engine_query, trigger_query, tables = _safety_queries(sql)
    return _validate_safety_rows(
        _aio_rows(target, engine_query, runner),
        _aio_rows(target, trigger_query, runner),
        tables,
    )


def _execute_mariadb_validation(sql: str, database: dict[str, object]) -> dict[str, object]:
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
        "autocommit": False,
    }
    if database.get("unix_socket"):
        parameters["unix_socket"] = database["unix_socket"]
    if not parameters["user"] or not parameters["database"]:
        raise ValueError("Direct MariaDB mode requires a database user and database name")
    connection = None
    try:
        connection = pymysql.connect(**parameters)
        with connection.cursor() as cursor:
            engine_query, trigger_query, tables = _safety_queries(sql)
            cursor.execute(engine_query)
            engine_rows = [[str(value) for value in row] for row in cursor.fetchall()]
            cursor.execute(trigger_query)
            trigger_rows = [[str(value) for value in row] for row in cursor.fetchall()]
            safety = _validate_safety_rows(engine_rows, trigger_rows, tables)
            for statement in sql.splitlines():
                if statement.strip() not in {"START TRANSACTION;", "ROLLBACK;"}:
                    cursor.execute(statement)
        connection.rollback()
        return safety
    except (pymysql.MySQLError, ValueError) as exc:
        if connection is not None:
            connection.rollback()
        raise ValueError(f"The destination rejected the simulated import: {exc}") from exc
    finally:
        if connection is not None:
            connection.close()


def validate_import(
    directory: Path,
    target_directory: Path | None,
    *,
    mode: str,
    database: dict[str, object],
    config_path: Path | None,
    convert_personal_notes: bool,
    writers_stopped: bool,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, object]:
    if mode == "aio":
        if target_directory is None:
            raise ValueError("AIO mode requires the target deployment directory")
        target = target_directory.resolve()
        _check_aio_writers(target, runner)
        destination_config = target / "config" / "config.json"
    elif mode == "mariadb":
        target = None
        if not writers_stopped:
            raise ValueError("Direct MariaDB mode requires --writers-stopped")
        if config_path is None:
            raise ValueError("Direct MariaDB mode requires DRIVERSHUB_TARGET_CONFIG_PATH")
        destination_config = config_path.resolve()
    else:
        raise ValueError("DRIVERSHUB_TARGET_MODE must be aio or mariadb")

    configuration, configuration_sql = _configuration_validation(
        directory, destination_config
    )
    sql, stages = _stage_sql(
        directory, convert_personal_notes, configuration_sql
    )
    if mode == "aio":
        safety = _inspect_aio_safety(target, sql, runner)  # type: ignore[arg-type]
        _execute_aio_validation(target, sql, runner)  # type: ignore[arg-type]
    else:
        safety = _execute_mariadb_validation(sql, database)
    return {
        "state": "ready",
        "method": "full-transaction-rollback",
        "transaction_safety": safety,
        "configuration": configuration,
        "stages": stages,
        "committed_writes": 0,
    }
