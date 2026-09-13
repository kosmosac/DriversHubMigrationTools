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


def _manifest_states(value: object, counts: dict[str, int]) -> None:
    if isinstance(value, dict):
        state = value.get("state")
        if isinstance(state, str):
            counts[state] = counts.get(state, 0) + 1
        for child in value.values():
            _manifest_states(child, counts)
    elif isinstance(value, list):
        for child in value:
            _manifest_states(child, counts)


def verify_export(directory: Path) -> dict[str, object]:
    manifest_path = directory / "export.json"
    failures: list[dict[str, object]] = []
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {
            "integrity": "invalid",
            "export": "unknown",
            "directory": str(directory),
            "checked_files": 0,
            "manifest_states": {},
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

    manifest_states: dict[str, int] = {}
    _manifest_states(manifest, manifest_states)
    incomplete_states = {
        state: manifest_states[state]
        for state in ("failed", "incomplete", "inconsistent")
        if manifest_states.get(state, 0) > 0
    }
    return {
        "integrity": "valid" if not failures else "invalid",
        "export": "incomplete" if incomplete_states else "complete",
        "directory": str(directory),
        "checked_files": len(checked),
        "manifest_states": dict(sorted(manifest_states.items())),
        "export_issues": incomplete_states,
        "failures": failures,
    }
