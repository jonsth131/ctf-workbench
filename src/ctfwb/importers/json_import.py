"""JSON validation and preview planning for CTFd imports.

Supported JSON input follows the CTFd v1 challenge model: a bare array of
challenge objects, the API envelope ``{"success": true, "data": [...]}``, or
an export object containing ``{"challenges": [...]}``. CTFd's documented
challenge fields ``id``, ``name``, ``category``, ``value``, ``description``,
and ``files`` are mapped into import records. File entries remain
metadata; this module does not download them.

This module never writes data: a caller must explicitly confirm a returned
plan and apply it through persistence.
"""

from __future__ import annotations

import json
import re
import unicodedata
import urllib.parse
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


class ImportErrorBase(Exception):
    """Base class for safe, user-displayable import errors."""


class ImportValidationError(ImportErrorBase):
    """An imported JSON document or challenge record is unsupported."""


class CTFdError(ImportErrorBase):
    """A CTFd request failed or returned an invalid response."""


class CTFdAuthenticationError(CTFdError):
    """CTFd rejected the configured token."""


class CTFdRateLimitError(CTFdError):
    """CTFd rate-limited the request."""


_INVALID_FILENAME_CHARS = set('<>:"|?*')
_WINDOWS_RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL"}


def _safe_artifact_from_url(
    file_url: object, index: int, challenge_name: str
) -> dict[str, str]:
    """Validate a CTFd file reference and map it to a storage-safe record."""
    if not isinstance(file_url, str) or not file_url.strip():
        raise ImportValidationError(
            f"challenge '{challenge_name}' file at index {index} must be a non-empty URL"
        )
    file_url = file_url.strip()
    if any(ord(char) < 32 or ord(char) == 127 for char in file_url):
        raise ImportValidationError(
            f"challenge '{challenge_name}' file at index {index} has an invalid URL"
        )
    # Reject malformed percent escapes instead of silently changing a URL.
    if re.search(r"%(?![0-9a-fA-F]{2})", file_url):
        raise ImportValidationError(
            f"challenge '{challenge_name}' file at index {index} has an invalid URL"
        )
    try:
        parsed = urllib.parse.urlsplit(file_url)
        _ = parsed.port
    except ValueError:
        raise ImportValidationError(
            f"challenge '{challenge_name}' file at index {index} has an invalid URL"
        ) from None
    if parsed.scheme:
        if (
            parsed.scheme.lower() not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ImportValidationError(
                f"challenge '{challenge_name}' file at index {index} has an unsupported URL"
            )
    elif (
        not parsed.path.startswith("/") or parsed.path.startswith("//") or parsed.netloc
    ):
        raise ImportValidationError(
            f"challenge '{challenge_name}' file at index {index} must be an absolute URL or root-relative path"
        )

    # CTFd file references are URLs, not trusted paths. Use only their final
    # URL path component as a display/original name, then make a separate safe
    # stored name suitable for DataStore's artifact schema.
    original_name = urllib.parse.unquote(parsed.path.rsplit("/", 1)[-1])
    if (
        not original_name
        or original_name in {".", ".."}
        or any(ord(char) < 32 or ord(char) == 127 for char in original_name)
    ):
        raise ImportValidationError(
            f"challenge '{challenge_name}' file at index {index} has an invalid filename"
        )
    stored_name = (
        "".join(
            "_"
            if char in {"/", "\\"}
            or char in _INVALID_FILENAME_CHARS
            or unicodedata.category(char) == "Cc"
            else char
            for char in original_name
        )
        .strip()
        .rstrip(" .")
    )
    if stored_name in {"", ".", ".."}:
        stored_name = f"artifact-{index + 1}"
    reserved_stem = stored_name.split(".", 1)[0].upper()
    if reserved_stem in _WINDOWS_RESERVED_NAMES or re.fullmatch(
        r"(?:COM|LPT)[1-9]", reserved_stem
    ):
        stored_name = f"_{stored_name}"
    return {
        "filename": stored_name,
        "original_filename": original_name,
        "source_url": file_url,
    }


def _validate_normalized_artifact(
    artifact: object, index: int, challenge_name: str
) -> dict[str, str | None]:
    """Ensure an already-normalized artifact matches the persisted schema."""
    if not isinstance(artifact, Mapping):
        raise ImportValidationError(
            f"challenge '{challenge_name}' artifact at index {index} must be an object"
        )
    filename = artifact.get("filename")
    if not isinstance(filename, str) or not filename.strip():
        raise ImportValidationError(
            f"challenge '{challenge_name}' artifact at index {index} needs a stored filename"
        )
    reserved_stem = filename.rstrip(" .").split(".", 1)[0].upper()
    if (
        filename in {".", ".."}
        or "/" in filename
        or "\\" in filename
        or filename.endswith((" ", "."))
        or any(ord(char) < 32 or char in _INVALID_FILENAME_CHARS for char in filename)
        or reserved_stem in _WINDOWS_RESERVED_NAMES
        or re.fullmatch(r"(?:COM|LPT)[1-9]", reserved_stem)
    ):
        raise ImportValidationError(
            f"challenge '{challenge_name}' artifact at index {index} has an unsafe stored filename"
        )
    original = artifact.get("original_filename")
    source_url = artifact.get("source_url")
    if original is not None and not isinstance(original, str):
        raise ImportValidationError(
            f"challenge '{challenge_name}' artifact at index {index} has an invalid original filename"
        )
    if source_url is not None and not isinstance(source_url, str):
        raise ImportValidationError(
            f"challenge '{challenge_name}' artifact at index {index} has an invalid source URL"
        )
    result: dict[str, str | None] = {"filename": filename}
    if original is not None:
        result["original_filename"] = original
    if source_url is not None:
        result["source_url"] = source_url
    return result


def _unique_artifact_filenames(
    artifacts: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    """Make stored names unique without losing their original-name metadata."""
    result: list[dict[str, object]] = []
    used: set[str] = set()
    for artifact in artifacts:
        normalized = dict(artifact)
        filename = str(normalized["filename"])
        candidate = filename
        stem, separator, extension = filename.rpartition(".")
        if not separator or not stem:
            stem, extension = filename, ""
        number = 2
        while candidate.casefold() in used:
            suffix = f"-{number}"
            candidate = (
                f"{stem}{suffix}.{extension}" if extension else f"{stem}{suffix}"
            )
            number += 1
        normalized["filename"] = candidate
        used.add(candidate.casefold())
        result.append(normalized)
    return result


@dataclass(frozen=True)
class ImportPlan:
    """Read-only preview of proposed additions and possible existing matches.

    ``remote_matches`` contains records matched by exact ``remote_id``.
    ``name_only_matches`` contains no-ID records that share a name with one
    or more local records; these are suggestions only and are never silently
    selected. ``additions`` contains records with no available candidate.
    Call :meth:`confirm` to produce a confirmation marker for a caller's
    persistence workflow; confirmation does not perform writes.
    """

    additions: tuple[dict[str, Any], ...]
    remote_matches: tuple[tuple[dict[str, Any], dict[str, Any]], ...]
    name_only_matches: tuple[tuple[dict[str, Any], tuple[dict[str, Any], ...]], ...]

    def confirm(self) -> "ConfirmedImportPlan":
        """Return an explicit confirmation marker without applying changes."""
        return ConfirmedImportPlan(self)

    @property
    def ambiguous_name_matches(
        self,
    ) -> tuple[tuple[dict[str, Any], tuple[dict[str, Any], ...]], ...]:
        """Return name-only suggestions with multiple possible local records."""
        return tuple(item for item in self.name_only_matches if len(item[1]) > 1)


@dataclass(frozen=True)
class ConfirmedImportPlan:
    """A caller-confirmed preview; it still has no persistence side effects."""

    plan: ImportPlan


@dataclass(frozen=True)
class RefreshPlan:
    """Preview of remote additions and changes without mutating local records."""

    additions: tuple[dict[str, Any], ...]
    updates: tuple[tuple[dict[str, Any], dict[str, Any], dict[str, Any]], ...]
    unchanged: tuple[tuple[dict[str, Any], dict[str, Any]], ...]
    missing: tuple[dict[str, Any], ...]


def _nonempty_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ImportValidationError(
            f"challenge field '{field}' must be a non-empty string"
        )
    return value.strip()


def _normalize_challenge(value: object, index: int) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ImportValidationError(f"challenge at index {index} must be an object")

    name = _nonempty_string(value.get("name"), "name")
    remote_id_value = value.get("id", value.get("remote_id"))
    if remote_id_value is None:
        remote_id = None
    elif type(remote_id_value) is int or isinstance(remote_id_value, str):
        remote_id = str(remote_id_value).strip()
        if not remote_id:
            raise ImportValidationError(f"challenge at index {index} has an empty id")
    else:
        raise ImportValidationError(f"challenge at index {index} has an invalid id")

    category = value.get("category")
    if category is not None and not isinstance(category, str):
        raise ImportValidationError(
            f"challenge '{name}' category must be a string or null"
        )
    points = value.get("value", value.get("points"))
    if points is not None and type(points) is not int:
        raise ImportValidationError(
            f"challenge '{name}' points/value must be an integer or null"
        )
    description = value.get("description", "")
    if not isinstance(description, str):
        raise ImportValidationError(f"challenge '{name}' description must be a string")
    files = value.get("files", [])
    artifacts = value.get("artifacts")
    if artifacts is not None:
        if not isinstance(artifacts, list):
            raise ImportValidationError(
                f"challenge '{name}' artifacts must be an array of objects"
            )
        normalized_artifacts = _unique_artifact_filenames(
            [
                _validate_normalized_artifact(item, artifact_index, name)
                for artifact_index, item in enumerate(artifacts)
            ]
        )
    else:
        if not isinstance(files, list):
            raise ImportValidationError(
                f"challenge '{name}' files must be an array of URLs"
            )
        normalized_artifacts = _unique_artifact_filenames(
            [
                _safe_artifact_from_url(item, file_index, name)
                for file_index, item in enumerate(files)
            ]
        )

    return {
        "remote_id": remote_id,
        "name": name,
        "category": category,
        "points": points,
        "description": description,
        "artifacts": normalized_artifacts,
    }


def _extract_challenges(document: object) -> list[object]:
    """Extract challenge records from the accepted API and export envelopes."""
    if isinstance(document, list):
        return document
    if not isinstance(document, Mapping):
        raise ImportValidationError(
            "JSON import must be a challenge array, CTFd API response, or CTFd export object"
        )

    if "success" in document:
        if document.get("success") is not True:
            raise ImportValidationError(
                "CTFd response reports an unsuccessful operation"
            )
        data = document.get("data")
        if isinstance(data, list):
            return data
        if isinstance(data, Mapping) and isinstance(data.get("challenges"), list):
            return data["challenges"]
        raise ImportValidationError("CTFd response data must contain a challenge array")

    if isinstance(document.get("challenges"), list):
        return document["challenges"]
    raise ImportValidationError(
        "JSON import must be a challenge array, CTFd API response, or CTFd export object"
    )


def validate_challenge_json(document: str | bytes | object) -> list[dict[str, Any]]:
    """Parse and validate a supported CTFd challenge response/export.

    Accepted shapes are a bare challenge array, a CTFd API envelope with
    ``success`` and array ``data``, or an export object with array
    ``challenges``. Raises :class:`ImportValidationError` for malformed JSON,
    unsupported envelopes, or invalid challenge fields.
    """
    if isinstance(document, (str, bytes)):
        try:
            parsed = json.loads(document)
        except json.JSONDecodeError as exc:
            raise ImportValidationError(
                "invalid challenge JSON at "
                f"line {exc.lineno}, column {exc.colno}: {exc.msg}"
            ) from None
        except UnicodeDecodeError:
            raise ImportValidationError("invalid challenge JSON encoding") from None
    else:
        parsed = document
    records = _extract_challenges(parsed)
    normalized = [
        _normalize_challenge(record, index) for index, record in enumerate(records)
    ]
    _ensure_unique_remote_ids(normalized)
    return normalized


def _ensure_unique_remote_ids(records: Sequence[Mapping[str, object]]) -> None:
    seen: set[str] = set()
    for record in records:
        remote_id = record.get("remote_id")
        if remote_id is None:
            continue
        normalized_id = str(remote_id)
        if normalized_id in seen:
            raise ImportValidationError(
                f"import contains duplicate remote challenge ID '{normalized_id}'"
            )
        seen.add(normalized_id)


def create_import_plan(
    imported: str | bytes | object | Sequence[Mapping[str, object]],
    existing: Sequence[Mapping[str, object]],
) -> ImportPlan:
    """Validate imported records and create an additions/matches preview.

    Stable remote IDs are matched exactly. Records without an ID are never
    auto-matched; exact name collisions are returned as unresolved suggestions
    (including multiple, ambiguous candidates) for explicit caller review.
    Input may be one of the documented JSON forms or already validated
    normalized challenge records. The function has no storage side effects.
    """
    if (
        isinstance(imported, Sequence)
        and not isinstance(imported, (str, bytes, bytearray))
        and (not imported or all(isinstance(row, Mapping) for row in imported))
    ):
        normalized = [
            _normalize_challenge(row, index) for index, row in enumerate(imported)
        ]
    else:
        normalized = validate_challenge_json(imported)
    _ensure_unique_remote_ids(normalized)

    remote_index: dict[str, dict[str, Any]] = {}
    name_index: dict[str, list[dict[str, Any]]] = {}
    for record in existing:
        if not isinstance(record, Mapping):
            raise ImportValidationError("existing challenge records must be objects")
        remote_id = record.get("remote_id")
        if remote_id is not None:
            remote_index.setdefault(str(remote_id), dict(record))
        name = record.get("name")
        if isinstance(name, str):
            name_index.setdefault(name.strip().casefold(), []).append(dict(record))

    additions: list[dict[str, Any]] = []
    remote_matches: list[tuple[dict[str, Any], dict[str, Any]]] = []
    name_matches: list[tuple[dict[str, Any], tuple[dict[str, Any], ...]]] = []
    for record in normalized:
        remote_id = record["remote_id"]
        if remote_id is not None and remote_id in remote_index:
            remote_matches.append((record, remote_index[remote_id]))
        elif remote_id is None and record["name"].casefold() in name_index:
            name_matches.append((record, tuple(name_index[record["name"].casefold()])))
        else:
            additions.append(record)
    return ImportPlan(tuple(additions), tuple(remote_matches), tuple(name_matches))


def create_refresh_plan(
    imported: str | bytes | object | Sequence[Mapping[str, object]],
    existing: Sequence[Mapping[str, object]],
    *,
    source: str = "ctfd",
) -> RefreshPlan:
    """Plan a CTFd or JSON refresh, preserving local-only fields and absent challenges."""
    if source not in {"ctfd", "json_import"}:
        raise ImportValidationError("refresh source must be 'ctfd' or 'json_import'")
    if (
        isinstance(imported, Sequence)
        and not isinstance(imported, (str, bytes, bytearray))
        and (not imported or all(isinstance(row, Mapping) for row in imported))
    ):
        normalized = [
            _normalize_challenge(row, index) for index, row in enumerate(imported)
        ]
    else:
        normalized = validate_challenge_json(imported)
    _ensure_unique_remote_ids(normalized)

    remote_index: dict[str, dict[str, Any]] = {}
    for record in existing:
        if not isinstance(record, Mapping):
            raise ImportValidationError("existing challenge records must be objects")
        if record.get("source") == source and isinstance(record.get("remote_id"), str):
            remote_index.setdefault(str(record["remote_id"]), dict(record))

    incoming_ids: set[str] = set()
    additions: list[dict[str, Any]] = []
    updates: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = []
    unchanged: list[tuple[dict[str, Any], dict[str, Any]]] = []
    remote_fields = ("name", "category", "points", "description")

    for record in normalized:
        remote_id = record["remote_id"]
        if remote_id is None:
            raise ImportValidationError(
                "refresh requires a stable remote ID for every challenge"
            )
        incoming_ids.add(remote_id)
        local = remote_index.get(remote_id)
        if local is None:
            additions.append(record)
            continue

        merged = dict(local)
        for field in remote_fields:
            merged[field] = record[field]
        merged["artifacts"] = _merge_refresh_artifacts(
            local.get("artifacts", []), record["artifacts"]
        )
        changed = any(local.get(field) != merged.get(field) for field in remote_fields)
        changed = changed or local.get("artifacts", []) != merged["artifacts"]
        if changed:
            updates.append((record, local, merged))
        else:
            unchanged.append((record, local))

    missing = [
        record
        for remote_id, record in remote_index.items()
        if remote_id not in incoming_ids
    ]
    return RefreshPlan(
        tuple(additions), tuple(updates), tuple(unchanged), tuple(missing)
    )


def _merge_refresh_artifacts(
    local_artifacts: object, remote_artifacts: object
) -> list[dict[str, Any]]:
    """Refresh remote metadata by filename while retaining absent local artifacts."""
    local = (
        [dict(item) for item in local_artifacts if isinstance(item, Mapping)]
        if isinstance(local_artifacts, list)
        else []
    )
    remote = (
        [dict(item) for item in remote_artifacts if isinstance(item, Mapping)]
        if isinstance(remote_artifacts, list)
        else []
    )
    result = list(local)
    for artifact in remote:
        filename = artifact.get("filename")
        if not isinstance(filename, str):
            continue
        existing_index = next(
            (
                index
                for index, existing in enumerate(result)
                if existing.get("filename") == filename
            ),
            None,
        )
        if existing_index is None:
            result.append(artifact)
        elif result[existing_index].get("source_url") is not None:
            result[existing_index] = artifact
    return result
