# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write_bytes(path: Path, data: bytes, mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    with temporary.open("wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    if mode is not None:
        os.chmod(temporary, mode)
    os.replace(temporary, path)


def atomic_write_json(path: Path, value: Any) -> None:
    payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    atomic_write_bytes(path, payload)


def mirrored_path(root: Path, absolute_target: str) -> Path:
    if not absolute_target.startswith("/"):
        raise ValueError(f"target must be absolute: {absolute_target!r}")
    relative = absolute_target.lstrip("/")
    if not relative or ".." in Path(relative).parts:
        raise ValueError(f"invalid target path: {absolute_target!r}")
    return root / relative


def stat_metadata(path: Path) -> dict[str, Any]:
    stat_result = path.stat()
    selinux = None
    try:
        raw = os.getxattr(path, "security.selinux")
        selinux = raw.decode("utf-8", errors="replace").rstrip("\x00")
    except (AttributeError, OSError):
        pass
    return {
        "mode": oct(stat_result.st_mode & 0o7777),
        "uid": stat_result.st_uid,
        "gid": stat_result.st_gid,
        "size": stat_result.st_size,
        "selinux": selinux,
    }
