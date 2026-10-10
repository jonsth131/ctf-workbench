"""Versioned record schemas and normalization helpers."""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1
_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_CTF_SOURCES = {"manual", "ctfd", "json_import"}
_CHALLENGE_STATUSES = {"unsolved", "in_progress", "solved", "skipped"}
_CHALLENGE_SOURCES = _CTF_SOURCES
_CTF_FIELDS = {
    "id",
    "name",
    "year",
    "platform_url",
    "description",
    "source",
    "created_at",
    "updated_at",
}
_CHALLENGE_FIELDS = {
    "id",
    "name",
    "category",
    "points",
    "description",
    "artifacts",
    "status",
    "flag",
    "source",
    "remote_id",
    "solver",
    "created_at",
    "updated_at",
}


def generate_id() -> str:
    """Return a path-safe, application-generated stable record ID."""
    return uuid.uuid4().hex


def utc_timestamp() -> str:
    """Return a UTC ISO-8601 timestamp suitable for record timestamps."""
    return (
        datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    )


class DataStoreError(Exception):
    """Base error for data-directory operations."""


class DataValidationError(DataStoreError):
    """A JSON document or record violates the supported schema."""

    def __init__(self, path: Path, message: str) -> None:
        self.path = path
        super().__init__(f"{path}: {message}")


class DataFileError(DataStoreError):
    """A JSON file could not be parsed or accessed safely."""

    def __init__(self, path: Path, message: str) -> None:
        self.path = path
        super().__init__(f"{path}: {message}")


class LockError(DataStoreError):
    """The data directory lock could not be acquired or released."""


def _validation_error(path: Path, field: str, expected: str) -> DataValidationError:
    return DataValidationError(path, f"field '{field}' {expected}")


def _check_fields(
    record: Mapping[str, object], allowed: set[str], required: set[str], path: Path
) -> None:
    if any(not isinstance(field, str) for field in record):
        raise DataValidationError(path, "record field names must be strings")
    extra = set(record) - allowed
    missing = required - set(record)
    if extra:
        raise DataValidationError(
            path, f"record contains unsupported field '{sorted(extra)[0]}'"
        )
    if missing:
        raise DataValidationError(
            path, f"record is missing required field '{sorted(missing)[0]}'"
        )


def _string(
    record: Mapping[str, object],
    field: str,
    path: Path,
    *,
    default: str | None = None,
    nonempty: bool = False,
) -> str:
    value = record.get(field, default)
    if not isinstance(value, str):
        raise _validation_error(path, field, "must be a string")
    normalized = value.strip() if nonempty else value
    if nonempty and not normalized:
        raise _validation_error(path, field, "must not be empty")
    return normalized


def _optional_string(
    record: Mapping[str, object], field: str, path: Path
) -> str | None:
    value = record.get(field)
    if value is not None and not isinstance(value, str):
        raise _validation_error(path, field, "must be a string or null")
    return value


def _record_id(record: Mapping[str, object], path: Path) -> str:
    value = _string(record, "id", path)
    if not _ID_RE.fullmatch(value):
        raise _validation_error(
            path,
            "id",
            "must be an application-generated 32-character lowercase hexadecimal ID",
        )
    return value


def _timestamp(record: Mapping[str, object], field: str, path: Path) -> str:
    value = record.get(field)
    if not isinstance(value, str):
        raise _validation_error(path, field, "must be a UTC ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(
            value[:-1] + "+00:00" if value.endswith("Z") else value
        )
    except ValueError as exc:
        raise _validation_error(
            path, field, "must be a valid UTC ISO-8601 timestamp"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise _validation_error(path, field, "must include a UTC timezone")
    return (
        parsed.astimezone(timezone.utc)
        .isoformat(timespec="auto")
        .replace("+00:00", "Z")
    )


def _enum(
    record: Mapping[str, object], field: str, values: set[str], path: Path
) -> str:
    value = _string(record, field, path)
    if value not in values:
        raise _validation_error(
            path, field, f"must be one of {', '.join(sorted(values))}"
        )
    return value


def _validate_ctf(record: Mapping[str, object], path: Path) -> dict[str, object]:
    _check_fields(
        record, _CTF_FIELDS, {"id", "name", "source", "created_at", "updated_at"}, path
    )
    year = record.get("year")
    if year is not None:
        if type(year) is not int or not 1900 <= year <= 2100:
            raise _validation_error(
                path, "year", "must be null or an integer from 1900 to 2100"
            )
    platform_url = _optional_string(record, "platform_url", path)
    description = _string(record, "description", path, default="")
    return {
        "id": _record_id(record, path),
        "name": _string(record, "name", path, nonempty=True),
        "year": year,
        "platform_url": platform_url,
        "description": description,
        "source": _enum(record, "source", _CTF_SOURCES, path),
        "created_at": _timestamp(record, "created_at", path),
        "updated_at": _timestamp(record, "updated_at", path),
    }


def _validate_artifact(value: object, path: Path, index: int) -> dict[str, object]:
    field = f"artifacts[{index}]"
    if not isinstance(value, Mapping):
        raise _validation_error(path, field, "must be an artifact record")
    allowed = {"filename", "original_filename", "source_url"}
    extra = set(value) - allowed
    if extra:
        raise DataValidationError(
            path, f"field '{field}' contains unsupported field '{sorted(extra)[0]}'"
        )
    filename = value.get("filename")
    if not isinstance(filename, str) or not filename.strip():
        raise _validation_error(
            path, f"{field}.filename", "must be a non-empty stored filename"
        )
    invalid_filename_chars = '<>:"|?*'
    windows_reserved_stem = filename.rstrip(" .").split(".", 1)[0].upper()
    if (
        Path(filename).name != filename
        or filename in {".", ".."}
        or any(ord(char) < 32 or char in invalid_filename_chars for char in filename)
        or "/" in filename
        or "\\" in filename
        or filename.endswith((" ", "."))
        or windows_reserved_stem in {"CON", "PRN", "AUX", "NUL"}
        or re.fullmatch(r"(?:COM|LPT)[1-9]", windows_reserved_stem)
    ):
        raise _validation_error(
            path, f"{field}.filename", "must be a filename, not a path"
        )
    result: dict[str, object] = {"filename": filename}
    for optional_field in ("original_filename", "source_url"):
        optional_value = value.get(optional_field)
        if optional_value is not None and not isinstance(optional_value, str):
            raise _validation_error(
                path, f"{field}.{optional_field}", "must be a string or null"
            )
        if optional_value is not None:
            result[optional_field] = optional_value
    return result


def _validate_solver(value: object, path: Path) -> dict[str, object] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise _validation_error(path, "solver", "must be a solver record or null")
    allowed = {"file_type", "relative_path"}
    _check_fields(value, allowed, allowed, path)
    file_type = value.get("file_type")
    relative_path = value.get("relative_path")
    if not isinstance(file_type, str) or file_type not in {"python", "bash"}:
        raise _validation_error(path, "solver.file_type", "must be 'python' or 'bash'")
    if not isinstance(relative_path, str) or not relative_path:
        raise _validation_error(
            path, "solver.relative_path", "must be a non-empty relative path"
        )
    relative = Path(relative_path)
    if (
        relative.is_absolute()
        or "\\" in relative_path
        or ":" in relative_path
        or "\x00" in relative_path
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise _validation_error(
            path, "solver.relative_path", "must remain within the challenge directory"
        )
    return {"file_type": file_type, "relative_path": relative_path}


def _validate_challenge(record: Mapping[str, object], path: Path) -> dict[str, object]:
    _check_fields(
        record,
        _CHALLENGE_FIELDS | {"hints"},
        {"id", "name", "status", "source", "created_at", "updated_at"},
        path,
    )
    points = record.get("points")
    if points is not None and type(points) is not int:
        raise _validation_error(path, "points", "must be an integer or null")
    artifacts = record.get("artifacts", [])
    if not isinstance(artifacts, list):
        raise _validation_error(
            path, "artifacts", "must be an array of artifact records"
        )
    category = _optional_string(record, "category", path)
    flag = _optional_string(record, "flag", path)
    remote_id = _optional_string(record, "remote_id", path)
    return {
        "id": _record_id(record, path),
        "name": _string(record, "name", path, nonempty=True),
        "category": category,
        "points": points,
        "description": _string(record, "description", path, default=""),
        "artifacts": [
            _validate_artifact(item, path, index)
            for index, item in enumerate(artifacts)
        ],
        "status": _enum(record, "status", _CHALLENGE_STATUSES, path),
        "flag": flag,
        "source": _enum(record, "source", _CHALLENGE_SOURCES, path),
        "remote_id": remote_id,
        "solver": _validate_solver(record.get("solver"), path),
        "created_at": _timestamp(record, "created_at", path),
        "updated_at": _timestamp(record, "updated_at", path),
    }
