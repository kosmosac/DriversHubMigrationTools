"""Durable storage for resumable exports."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import secrets
import stat
from typing import Any


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing_mode = (
        stat.S_IMODE(path.stat().st_mode) if path.exists() else None
    )
    while True:
        temporary_name = path.parent / f".{path.name}.{secrets.token_hex(8)}"
        try:
            fd = os.open(
                temporary_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                existing_mode if existing_mode is not None else 0o666,
            )
            break
        except FileExistsError:
            continue
    try:
        if existing_mode is not None:
            os.fchmod(fd, existing_mode)
        with os.fdopen(fd, "wb") as temporary_file:
            temporary_file.write(data)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def write_json(path: Path, value: Any) -> None:
    atomic_write(path, (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode())


def read_object(path: Path, description: str) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Unable to read {description}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"The {description} is not an object")
    return value


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class WorkJournal:
    """Small JSON journal updated atomically after each completed request."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.path = root / "work-journal.json"
        self.root.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
        else:
            self.data = {"format_version": 1, "requests": {}}
            self.save()

    def completed(self, key: str) -> bool:
        return self.data["requests"].get(key, {}).get("state") == "complete"

    def entry(self, key: str) -> dict[str, Any] | None:
        value = self.data["requests"].get(key)
        return dict(value) if value is not None else None

    def record(self, key: str, value: dict[str, Any]) -> None:
        self.data["requests"][key] = value
        self.save()

    def save(self) -> None:
        write_json(self.path, self.data)
