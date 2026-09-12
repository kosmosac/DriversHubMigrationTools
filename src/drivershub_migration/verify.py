"""Validate a completed migration directory without contacting the source."""

from __future__ import annotations

import json
from pathlib import Path

from .storage import sha256


def _file_references(value: object, location: str = "export"):
    if isinstance(value, dict):
        if isinstance(value.get("path"), str) and isinstance(value.get("sha256"), str):
            yield location, value["path"], value["sha256"]
        if isinstance(value.get("normalized_path"), str) and isinstance(
            value.get("normalized_sha256"), str
        ):
            yield location + ".normalized", value["normalized_path"], value["normalized_sha256"]
        for key, child in value.items():
            yield from _file_references(child, f"{location}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _file_references(child, f"{location}[{index}]")


def verify_export(directory: Path) -> dict[str, object]:
    manifest_path = directory / "export.json"
    failures: list[dict[str, object]] = []
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {
            "state": "failed",
            "directory": str(directory),
            "checked_files": 0,
            "failures": [{"path": "export.json", "error": str(exc)}],
        }
    if not isinstance(manifest, dict) or manifest.get("format_version") != 1:
        failures.append(
            {"path": "export.json", "error": "Unsupported or missing format_version"}
        )

    checked: set[str] = set()
    root = directory.resolve()
    for location, relative, expected in _file_references(manifest):
        if relative in checked:
            continue
        checked.add(relative)
        path = (directory / relative).resolve()
        if path != root and root not in path.parents:
            failures.append(
                {"location": location, "path": relative, "error": "Path leaves migration directory"}
            )
            continue
        if not path.is_file():
            failures.append(
                {"location": location, "path": relative, "error": "File is missing"}
            )
            continue
        observed = sha256(path.read_bytes())
        if observed != expected:
            failures.append(
                {
                    "location": location,
                    "path": relative,
                    "error": "Checksum mismatch",
                    "expected": expected,
                    "observed": observed,
                }
            )

    return {
        "state": "complete" if not failures else "failed",
        "directory": str(directory),
        "checked_files": len(checked),
        "failures": failures,
    }
