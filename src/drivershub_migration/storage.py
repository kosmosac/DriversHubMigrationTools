"""Durable storage for resumable exports."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        os.fchmod(fd, 0o600)
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


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class WorkJournal:
    """Small JSON journal updated atomically after each completed request."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.path = root / "work-journal.json"
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.root, 0o700)
        if self.path.exists():
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
        else:
            self.data = {"format_version": 1, "requests": {}}
            self.save()

    def completed(self, key: str) -> bool:
        return self.data["requests"].get(key, {}).get("state") == "complete"

    def record(self, key: str, value: dict[str, Any]) -> None:
        self.data["requests"][key] = value
        self.save()

    def save(self) -> None:
        write_json(self.path, self.data)
