"""Build imports for self-contained Hub content resources."""

from __future__ import annotations

from base64 import b64encode
import json
from pathlib import Path

from .account_import import _integer, _sql_value


def _records(directory: Path, name: str) -> list[dict[str, object]]:
    path = directory / "normalized" / f"{name}.json"
    if not path.exists():
        return []
    try:
        value = json.loads(path.read_text(encoding="utf-8"))["records"]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ValueError(f"Unable to read normalized {name}") from exc
    if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
        raise ValueError(f"The normalized {name} records are invalid")
    return value


def _compressed(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} is not a string")
    if not value:
        return ""
    try:
        import zstandard
    except ImportError as exc:
        raise ValueError("Install project dependencies to import compressed content") from exc
    return b64encode(zstandard.ZstdCompressor().compress(value.encode())).decode()


def _nested_id(row: dict[str, object], key: str, field: str) -> int:
    nested = row.get(key)
    if not isinstance(nested, dict):
        raise ValueError(f"{key} is not an object")
    return _integer(nested.get(field), f"{key}.{field}")


def _timestamp(value: object, field: str) -> int:
    result = _integer(value, field)
    if result < 0:
        raise ValueError(f"{field} must be Unix seconds")
    return result


def build_content_stage(directory: Path) -> tuple[str, dict[str, object]]:
    """Import resources whose API representation maps losslessly to one table."""
    statements = ["SET time_zone = '+00:00';", "START TRANSACTION;"]
    counts: dict[str, int] = {}

    announcements = _records(directory, "announcements")
    for row in announcements:
        kind = row.get("type")
        if not isinstance(kind, dict):
            raise ValueError("announcement type is not an object")
        values = [
            _integer(row.get("announcementid"), "announcementid"),
            _nested_id(row, "author", "userid"),
            row.get("title") if isinstance(row.get("title"), str) else "",
            _compressed(row.get("content"), "announcement content"),
            _integer(kind.get("id"), "announcement type id"),
            _timestamp(row.get("timestamp"), "announcement timestamp"),
            bool(row.get("is_private")),
            _integer(row.get("orderid"), "announcement orderid"),
            bool(row.get("is_pinned")),
        ]
        statements.append("INSERT INTO `announcement` (`announcementid`,`userid`,`title`,`content`,`announcement_type`,`timestamp`,`is_private`,`orderid`,`is_pinned`) VALUES (" + ",".join(_sql_value(value) for value in values) + ");")
    counts["announcements"] = len(announcements)

    downloads = _records(directory, "downloads")
    for row in downloads:
        values = [
            _integer(row.get("downloadsid"), "downloadsid"),
            _nested_id(row, "creator", "userid"),
            row.get("title") if isinstance(row.get("title"), str) else "",
            _compressed(row.get("description"), "download description"),
            row.get("link") if isinstance(row.get("link"), str) else "",
            _integer(row.get("orderid"), "download orderid"),
            bool(row.get("is_pinned")),
            _timestamp(row.get("timestamp"), "download timestamp"),
            _integer(row.get("click_count"), "download click_count"),
        ]
        statements.append("INSERT INTO `downloads` (`downloadsid`,`userid`,`title`,`description`,`link`,`orderid`,`is_pinned`,`timestamp`,`click_count`) VALUES (" + ",".join(_sql_value(value) for value in values) + ");")
    counts["downloads"] = len(downloads)
    statements.append("COMMIT;")
    return "\n".join(statements) + "\n", {
        "state": "ready",
        "resources": counts,
        "records": sum(counts.values()),
        "database_time_zone": "+00:00",
    }
