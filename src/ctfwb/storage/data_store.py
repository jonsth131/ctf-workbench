"""Validated, atomic JSON persistence for CTF and challenge records."""

from __future__ import annotations

import json
import os
import shutil
import stat
import tempfile
import uuid
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from zipfile import ZIP_DEFLATED, ZipFile

from ctfwb.storage import schema as _schema
from ctfwb.storage.locking import DataDirectoryLock

# Keep the original storage module API, including schema helpers imported by tests.
SCHEMA_VERSION = _schema.SCHEMA_VERSION
_ID_RE = _schema._ID_RE
_CTF_SOURCES = _schema._CTF_SOURCES
_CHALLENGE_STATUSES = _schema._CHALLENGE_STATUSES
_CHALLENGE_SOURCES = _schema._CHALLENGE_SOURCES
_CTF_FIELDS = _schema._CTF_FIELDS
_CHALLENGE_FIELDS = _schema._CHALLENGE_FIELDS
generate_id = _schema.generate_id
utc_timestamp = _schema.utc_timestamp
DataStoreError = _schema.DataStoreError
DataValidationError = _schema.DataValidationError
DataFileError = _schema.DataFileError
LockError = _schema.LockError
_validation_error = _schema._validation_error
_check_fields = _schema._check_fields
_string = _schema._string
_optional_string = _schema._optional_string
_record_id = _schema._record_id
_timestamp = _schema._timestamp
_enum = _schema._enum
_validate_ctf = _schema._validate_ctf
_validate_artifact = _schema._validate_artifact
_validate_solver = _schema._validate_solver
_validate_challenge = _schema._validate_challenge


def normalize_ctfd_base_url(base_url: str) -> str:
    """Normalize an HTTPS base URL for matching stored CTFd credentials."""
    return base_url.strip().rstrip("/")


class DataStore:
    """Manage versioned CTF and challenge JSON beneath one data directory."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir).expanduser().resolve()
        self._lock: DataDirectoryLock | None = None

    @staticmethod
    def _excluded_from_export(path: Path, *, is_directory: bool) -> bool:
        name = path.name.casefold()
        if name == "token.json" or name.endswith(".lock") or name.endswith(".tmp"):
            return True
        if name.endswith(".log") or ".deleting-" in name:
            return True
        return is_directory and name == "logs"

    @staticmethod
    def _redact_export_information(path: Path, contents: bytes) -> bytes:
        try:
            document = json.loads(contents.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise DataFileError(
                path,
                f"malformed JSON at line {exc.lineno}, column {exc.colno}",
            ) from None
        except UnicodeDecodeError as exc:
            raise DataFileError(
                path, f"file is not valid UTF-8 at byte {exc.start}"
            ) from None

        if not isinstance(document, dict):
            raise DataValidationError(path, "document must be a JSON object")
        if set(document) == {"challenges"}:
            version = 0
        elif set(document) == {"schema_version", "challenges"}:
            version = document["schema_version"]
        else:
            raise DataValidationError(
                path,
                "document must contain only 'schema_version' and 'challenges'",
            )
        if type(version) is not int or not 0 <= version <= SCHEMA_VERSION:
            raise DataValidationError(
                path, f"unsupported schema_version; expected 0 or {SCHEMA_VERSION}"
            )
        challenges = document["challenges"]
        if not isinstance(challenges, list):
            raise DataValidationError(path, "'challenges' must be an array")

        seen_ids: set[str] = set()
        for index, record in enumerate(challenges):
            if not isinstance(record, Mapping):
                raise DataValidationError(
                    path, f"challenges[{index}] must be an object"
                )
            validated = _validate_challenge(record, path)
            challenge_id = str(validated["id"])
            if challenge_id in seen_ids:
                raise DataValidationError(
                    path, f"challenges[{index}] has a duplicate id"
                )
            seen_ids.add(challenge_id)
            if record.get("flag") is not None:
                # Do not mutate the parsed document until after validation.
                record.pop("flag", None)

        return (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode(
            "utf-8"
        )

    @staticmethod
    def _write_export_file(
        archive: ZipFile,
        path: Path,
        relative_name: str,
        *,
        redact_flags: bool,
    ) -> None:
        descriptor = -1
        try:
            descriptor = os.open(
                path,
                os.O_RDONLY
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_NONBLOCK", 0),
            )
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise DataFileError(path, "export input is not a regular file")
            with os.fdopen(descriptor, "rb") as stream:
                descriptor = -1
                if redact_flags:
                    contents = DataStore._redact_export_information(path, stream.read())
                    archive.writestr(relative_name, contents)
                else:
                    with archive.open(relative_name, "w") as output:
                        shutil.copyfileobj(stream, output)
        except DataStoreError:
            raise
        except OSError:
            raise DataFileError(path, "cannot read export input safely") from None
        finally:
            if descriptor >= 0:
                os.close(descriptor)

    def export_archive(self, destination: Path, *, include_flags: bool = False) -> Path:
        """Atomically export managed user data without credentials or transient files.

        Challenge flags are removed from exported ``information.json`` files
        unless explicitly opted in. Existing destinations are never replaced.
        """
        destination_path = Path(destination).expanduser()
        try:
            resolved_destination = destination_path.resolve()
        except (OSError, RuntimeError):
            raise DataFileError(
                destination_path, "cannot resolve export destination safely"
            ) from None
        if resolved_destination == self.data_dir or resolved_destination.is_relative_to(
            self.data_dir
        ):
            raise DataFileError(
                destination_path,
                "export destination must be outside the managed data directory",
            )
        try:
            source_mode = self.data_dir.lstat().st_mode
        except OSError:
            raise DataFileError(
                self.data_dir, "managed data directory is unavailable"
            ) from None
        if not stat.S_ISDIR(source_mode):
            raise DataFileError(self.data_dir, "managed data path is not a directory")
        if destination_path.is_symlink() or destination_path.exists():
            raise DataFileError(destination_path, "export destination already exists")

        temporary_path: Path | None = None
        try:
            resolved_destination.parent.mkdir(parents=True, exist_ok=True)
            # Re-resolve after creating parents to account for path aliases.
            resolved_destination = resolved_destination.resolve()
            if (
                resolved_destination == self.data_dir
                or resolved_destination.is_relative_to(self.data_dir)
            ):
                raise DataFileError(
                    destination_path,
                    "export destination must be outside the managed data directory",
                )
            if resolved_destination.exists() or resolved_destination.is_symlink():
                raise DataFileError(
                    destination_path, "export destination already exists"
                )

            with tempfile.NamedTemporaryFile(
                mode="w+b",
                dir=resolved_destination.parent,
                prefix=".ctfwb-export-",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)

            with ZipFile(temporary_path, "w", compression=ZIP_DEFLATED) as archive:

                def walk_error(error: OSError) -> None:
                    raise DataFileError(
                        Path(error.filename or self.data_dir),
                        "cannot inspect export directory safely",
                    ) from None

                for current, directories, filenames in os.walk(
                    self.data_dir,
                    topdown=True,
                    onerror=walk_error,
                    followlinks=False,
                ):
                    current_path = Path(current)
                    retained_directories: list[str] = []
                    for name in sorted(directories):
                        child = current_path / name
                        if self._excluded_from_export(child, is_directory=True):
                            continue
                        try:
                            mode = child.lstat().st_mode
                        except OSError:
                            raise DataFileError(
                                child, "cannot inspect export input safely"
                            ) from None
                        if stat.S_ISLNK(mode):
                            raise DataFileError(
                                child, "refusing to follow a symlink during export"
                            )
                        if not stat.S_ISDIR(mode):
                            raise DataFileError(
                                child, "export directory entry is not a directory"
                            )
                        retained_directories.append(name)
                        archive.writestr(
                            child.relative_to(self.data_dir).as_posix().rstrip("/")
                            + "/",
                            b"",
                        )
                    directories[:] = retained_directories

                    for name in sorted(filenames):
                        source = current_path / name
                        if self._excluded_from_export(source, is_directory=False):
                            continue
                        try:
                            mode = source.lstat().st_mode
                        except OSError:
                            raise DataFileError(
                                source, "cannot inspect export input safely"
                            ) from None
                        if stat.S_ISLNK(mode):
                            raise DataFileError(
                                source, "refusing to follow a symlink during export"
                            )
                        if not stat.S_ISREG(mode):
                            raise DataFileError(
                                source, "export input is not a regular file"
                            )
                        relative_name = source.relative_to(self.data_dir).as_posix()
                        self._write_export_file(
                            archive,
                            source,
                            relative_name,
                            redact_flags=(
                                source.name == "information.json" and not include_flags
                            ),
                        )

            # A same-directory hard link publishes the completed archive
            # atomically and fails rather than replacing a concurrent file.
            try:
                os.link(temporary_path, resolved_destination)
            except FileExistsError:
                raise DataFileError(
                    destination_path, "export destination already exists"
                ) from None
            completed_temporary = temporary_path
            temporary_path = None
            try:
                completed_temporary.unlink()
            except OSError:
                # The published archive is complete; a leftover staging link
                # must not turn a successful publication into a reported failure.
                pass
            return resolved_destination
        except DataStoreError:
            raise
        except Exception:
            raise DataFileError(
                destination_path, "cannot create export archive safely"
            ) from None
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink()
                except OSError:
                    pass

    def _managed_path(self, path: Path) -> Path:
        resolved = path.resolve()
        try:
            resolved.relative_to(self.data_dir)
        except ValueError as exc:
            raise DataFileError(
                path, "resolved path escapes the configured data directory"
            ) from exc
        return resolved

    @staticmethod
    def _make_directory(path: Path) -> None:
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise DataFileError(
                path, f"cannot create directory: {exc.strerror}"
            ) from exc

    def _ctfs_path(self) -> Path:
        return self._managed_path(self.data_dir / "ctfs.json")

    def _last_ctf_path(self) -> Path:
        return self._managed_path(self.data_dir / "last_ctf.json")

    def _challenges_path(self, ctf_id: str) -> Path:
        if not isinstance(ctf_id, str) or not _ID_RE.fullmatch(ctf_id):
            raise DataFileError(
                self.data_dir / "ctfs", "CTF ID is not a valid application-generated ID"
            )
        return self._managed_path(
            self.data_dir / "ctfs" / ctf_id / "challenges" / "information.json"
        )

    def _read_document(
        self, path: Path, key: str, validate: Any
    ) -> list[dict[str, object]]:
        try:
            with path.open("r", encoding="utf-8") as stream:
                document = json.load(stream)
        except json.JSONDecodeError as exc:
            raise DataFileError(
                path,
                f"malformed JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}",
            ) from exc
        except UnicodeDecodeError as exc:
            raise DataFileError(
                path, f"file is not valid UTF-8 at byte {exc.start}"
            ) from exc
        except OSError as exc:
            raise DataFileError(path, f"cannot read file: {exc.strerror}") from exc
        if not isinstance(document, dict):
            raise DataValidationError(path, "document must be a JSON object")
        versionless_legacy = set(document) == {key}
        if not versionless_legacy and set(document) != {"schema_version", key}:
            raise DataValidationError(
                path, f"document must contain only 'schema_version' and '{key}'"
            )
        version = 0 if versionless_legacy else document.get("schema_version")
        if type(version) is not int or not 0 <= version <= SCHEMA_VERSION:
            raise DataValidationError(
                path, f"unsupported schema_version; expected 0 or {SCHEMA_VERSION}"
            )
        records = document.get(key)
        if not isinstance(records, list):
            raise DataValidationError(path, f"'{key}' must be an array")
        result: list[dict[str, object]] = []
        ids: set[str] = set()
        for index, item in enumerate(records):
            if not isinstance(item, Mapping):
                raise DataValidationError(path, f"{key}[{index}] must be an object")
            record = validate(item, path)
            if record["id"] in ids:
                raise DataValidationError(path, f"{key}[{index}] has a duplicate id")
            ids.add(str(record["id"]))
            result.append(record)
        if version == 0:
            self._backup(path)
            self._atomic_write(path, key, result)
            self._remove_backups(path)
        return result

    @staticmethod
    def _atomic_write(
        path: Path, key: str, records: Sequence[Mapping[str, object]]
    ) -> None:
        document = {"schema_version": SCHEMA_VERSION, key: list(records)}
        DataStore._atomic_write_document(path, document)

    @staticmethod
    def _atomic_write_document(path: Path, document: Mapping[str, object]) -> None:
        temporary_name: str | None = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as stream:
                temporary_name = stream.name
                json.dump(document, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_name, path)
            temporary_name = None
            try:
                directory_fd = os.open(path.parent, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            except OSError:
                # Some filesystems do not support syncing directory metadata.
                pass
        except (OSError, TypeError, ValueError, UnicodeError) as exc:
            detail = exc.strerror if isinstance(exc, OSError) else None
            suffix = f": {detail}" if detail else ""
            raise DataFileError(path, f"cannot write file atomically{suffix}") from exc
        finally:
            if temporary_name is not None:
                try:
                    os.unlink(temporary_name)
                except OSError:
                    pass
        DataStore._verify_written_document(path, document)

    @staticmethod
    def _verify_written_document(path: Path, expected: Mapping[str, object]) -> None:
        try:
            with path.open("r", encoding="utf-8") as stream:
                written = json.load(stream)
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise DataFileError(path, "written JSON could not be verified") from exc
        if written != expected:
            raise DataFileError(path, "written JSON did not match the saved data")

    @staticmethod
    def _remove_backups(path: Path) -> None:
        for backup in path.parent.glob(f"{path.name}.*.bak"):
            try:
                backup.unlink()
            except FileNotFoundError:
                continue
            except OSError as exc:
                detail = exc.strerror or "filesystem operation failed"
                raise DataFileError(
                    path, f"save was verified but backup cleanup failed: {detail}"
                ) from exc

    @staticmethod
    def _backup(path: Path) -> Path:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup = path.with_name(f"{path.name}.{timestamp}.bak")
        try:
            shutil.copy2(path, backup)
        except OSError as exc:
            raise DataFileError(
                path, f"cannot create pre-update backup: {exc.strerror}"
            ) from exc
        return backup

    def load_ctfs(self) -> list[dict[str, object]]:
        path = self._ctfs_path()
        self._make_directory(self.data_dir)
        if not path.exists():
            self._atomic_write(path, "ctfs", [])
            return []
        return self._read_document(path, "ctfs", _validate_ctf)

    def load_last_ctf_id(self) -> str | None:
        """Load the previously opened CTF ID, if one has been recorded."""
        path = self._last_ctf_path()
        try:
            with path.open("r", encoding="utf-8") as stream:
                document = json.load(stream)
        except FileNotFoundError:
            return None
        except json.JSONDecodeError as exc:
            raise DataFileError(
                path,
                f"malformed JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}",
            ) from exc
        except UnicodeDecodeError as exc:
            raise DataFileError(
                path, f"file is not valid UTF-8 at byte {exc.start}"
            ) from exc
        except OSError as exc:
            raise DataFileError(path, f"cannot read file: {exc.strerror}") from exc
        if not isinstance(document, dict) or set(document) != {
            "schema_version",
            "last_ctf_id",
        }:
            raise DataValidationError(
                path, "document must contain only 'schema_version' and 'last_ctf_id'"
            )
        version = document["schema_version"]
        if type(version) is not int or version != SCHEMA_VERSION:
            raise DataValidationError(
                path, f"unsupported schema_version; expected {SCHEMA_VERSION}"
            )
        ctf_id = document["last_ctf_id"]
        if ctf_id is not None and (
            not isinstance(ctf_id, str) or not _ID_RE.fullmatch(ctf_id)
        ):
            raise DataValidationError(
                path, "'last_ctf_id' must be a valid CTF ID or null"
            )
        return ctf_id

    def save_last_ctf_id(self, ctf_id: str | None) -> None:
        """Atomically persist the last opened CTF ID."""
        if ctf_id is not None and (
            not isinstance(ctf_id, str) or not _ID_RE.fullmatch(ctf_id)
        ):
            raise DataValidationError(
                self._last_ctf_path(), "'last_ctf_id' must be a valid CTF ID or null"
            )
        path = self._last_ctf_path()
        self._make_directory(self.data_dir)
        self._atomic_write_document(
            path,
            {"schema_version": SCHEMA_VERSION, "last_ctf_id": ctf_id},
        )

    def save_ctfs(self, records: Sequence[Mapping[str, object]]) -> None:
        path = self._ctfs_path()
        self._make_directory(self.data_dir)
        validated = self._validate_collection(records, path, _validate_ctf)
        if path.exists():
            # Validate before backing up or replacing: invalid user data is never discarded.
            self._read_document(path, "ctfs", _validate_ctf)
            self._backup(path)
        self._atomic_write(path, "ctfs", validated)
        self._remove_backups(path)

    def delete_ctf(
        self, ctf_id: str, remaining_records: Sequence[Mapping[str, object]]
    ) -> Path | None:
        """Remove a CTF and its files, restoring them if the index update fails.

        Returns the staged directory path if final cleanup fails after the CTF
        has been removed from the index. The retained path is safe to remove
        manually and is reported to the caller.
        """
        ctf_directory = self._ctf_directory_path(ctf_id)
        current_records = self.load_ctfs()
        if not any(record["id"] == ctf_id for record in current_records):
            raise DataValidationError(
                self._ctfs_path(), f"CTF ID '{ctf_id}' does not exist"
            )
        if any(record.get("id") == ctf_id for record in remaining_records):
            raise DataValidationError(
                self._ctfs_path(),
                "remaining CTF records still contain the deleted CTF ID",
            )

        staged_directory = ctf_directory.with_name(
            f".{ctf_id}.deleting-{uuid.uuid4().hex}"
        )
        moved_directory = False
        try:
            if ctf_directory.is_symlink():
                raise DataFileError(
                    ctf_directory, "refusing to delete a symlinked CTF directory"
                )
            if ctf_directory.exists():
                if not ctf_directory.is_dir():
                    raise DataFileError(ctf_directory, "CTF path is not a directory")
                os.replace(ctf_directory, staged_directory)
                moved_directory = True
        except OSError as exc:
            raise DataFileError(
                ctf_directory,
                f"cannot stage CTF directory for deletion: {exc.strerror}",
            ) from exc

        try:
            self.save_ctfs(remaining_records)
        except DataStoreError:
            if moved_directory:
                try:
                    os.replace(staged_directory, ctf_directory)
                except OSError as exc:
                    raise DataFileError(
                        ctf_directory,
                        "CTF index update failed and the directory could not be restored; "
                        f"recover it from {staged_directory}",
                    ) from exc
            raise

        if not moved_directory:
            return None
        try:
            shutil.rmtree(staged_directory)
        except OSError:
            return staged_directory
        return None

    def delete_challenge(
        self,
        ctf_id: str,
        challenge_id: str,
        remaining_records: Sequence[Mapping[str, object]],
    ) -> Path | None:
        """Remove a challenge and its files, restoring them if collection save fails.

        Returns the staged challenge directory if final cleanup fails after the
        collection has been updated. The retained path is safe to remove
        manually and is reported to the caller.
        """
        collection_path = self._challenges_path(ctf_id)
        if not isinstance(challenge_id, str) or not _ID_RE.fullmatch(challenge_id):
            raise DataFileError(
                collection_path.parent,
                "challenge ID is not a valid application-generated ID",
            )

        current_records = self.load_challenges(ctf_id)
        if not any(record["id"] == challenge_id for record in current_records):
            raise DataValidationError(
                collection_path, f"challenge ID '{challenge_id}' does not exist"
            )

        validated_remaining = self._validate_collection(
            remaining_records, collection_path, _validate_challenge
        )
        if any(record["id"] == challenge_id for record in validated_remaining):
            raise DataValidationError(
                collection_path,
                "remaining challenge records still contain the deleted challenge ID",
            )

        challenges_directory = self._managed_path(collection_path.parent)
        challenge_directory = challenges_directory / challenge_id
        if challenge_directory.is_symlink():
            raise DataFileError(
                challenge_directory,
                "refusing to delete a symlinked challenge directory",
            )
        resolved_challenge_directory = self._managed_path(challenge_directory)
        if resolved_challenge_directory.parent != challenges_directory:
            raise DataFileError(
                challenge_directory,
                "challenge directory resolves outside its managed location",
            )

        staged_directory = challenges_directory / (
            f".{challenge_id}.deleting-{uuid.uuid4().hex}"
        )
        resolved_staged_directory = self._managed_path(staged_directory)
        if (
            resolved_staged_directory.parent != challenges_directory
            or resolved_staged_directory != staged_directory
            or staged_directory.is_symlink()
            or staged_directory.exists()
        ):
            raise DataFileError(
                staged_directory, "challenge deletion staging path is not safe to use"
            )
        moved_directory = False
        try:
            if challenge_directory.exists():
                if not challenge_directory.is_dir():
                    raise DataFileError(
                        challenge_directory, "challenge path is not a directory"
                    )
                os.replace(challenge_directory, staged_directory)
                moved_directory = True
        except OSError as exc:
            raise DataFileError(
                challenge_directory,
                f"cannot stage challenge directory for deletion: {exc.strerror}",
            ) from exc

        try:
            self.save_challenges(ctf_id, validated_remaining)
        except DataStoreError:
            if moved_directory:
                try:
                    os.replace(staged_directory, challenge_directory)
                except OSError as exc:
                    raise DataFileError(
                        challenge_directory,
                        "challenge collection update failed and the directory could "
                        f"not be restored; recover it from {staged_directory}",
                    ) from exc
            raise

        if not moved_directory:
            return None
        try:
            shutil.rmtree(staged_directory)
        except OSError:
            return staged_directory
        return None

    def load_challenges(self, ctf_id: str) -> list[dict[str, object]]:
        path = self._challenges_path(ctf_id)
        self._make_directory(path.parent)
        if not path.exists():
            self._atomic_write(path, "challenges", [])
            return []
        return self._read_document(path, "challenges", _validate_challenge)

    def challenge_directory(self, ctf_id: str, challenge_id: str) -> Path:
        """Return a validated challenge directory, creating it when absent."""
        if not isinstance(challenge_id, str) or not _ID_RE.fullmatch(challenge_id):
            raise DataFileError(
                self.data_dir / "ctfs",
                "challenge ID is not a valid application-generated ID",
            )
        if not any(
            record["id"] == challenge_id for record in self.load_challenges(ctf_id)
        ):
            raise DataValidationError(
                self._challenges_path(ctf_id),
                f"challenge ID '{challenge_id}' does not exist",
            )

        ctf_directory = self._ctf_directory_path(ctf_id)
        challenges_directory = ctf_directory / "challenges"
        if challenges_directory.is_symlink():
            raise DataFileError(
                challenges_directory, "refusing to use a symlinked challenges directory"
            )
        self._make_directory(challenges_directory)
        if self._managed_path(challenges_directory) != challenges_directory.resolve():
            raise DataFileError(
                challenges_directory,
                "challenges directory resolves outside its managed location",
            )
        challenge_directory = challenges_directory / challenge_id
        if challenge_directory.is_symlink():
            raise DataFileError(
                challenge_directory, "refusing to use a symlinked challenge directory"
            )
        self._make_directory(challenge_directory)
        resolved = self._managed_path(challenge_directory)
        if resolved.parent != challenges_directory.resolve():
            raise DataFileError(
                challenge_directory,
                "challenge directory resolves outside its managed location",
            )
        if not resolved.is_dir():
            raise DataFileError(
                challenge_directory, "challenge path is not a directory"
            )
        return resolved

    def challenge_artifacts_directory(self, ctf_id: str, challenge_id: str) -> Path:
        """Return a validated, created artifacts directory for one challenge."""
        challenge_directory = self.challenge_directory(ctf_id, challenge_id)
        artifacts_directory = challenge_directory / "artifacts"
        if artifacts_directory.is_symlink():
            raise DataFileError(
                artifacts_directory, "refusing to use a symlinked artifacts directory"
            )
        self._make_directory(artifacts_directory)
        resolved = self._managed_path(artifacts_directory)
        if resolved != artifacts_directory or resolved.parent != challenge_directory:
            raise DataFileError(
                artifacts_directory,
                "artifacts directory resolves outside its managed location",
            )
        if not resolved.is_dir():
            raise DataFileError(
                artifacts_directory, "artifacts path is not a directory"
            )
        return resolved

    def resolve_challenge_file(
        self,
        ctf_id: str,
        challenge_id: str,
        relative_path: str,
        *,
        create_parent: bool = False,
        must_exist: bool = False,
    ) -> Path:
        """Resolve a solver path beneath a challenge, rejecting traversal/symlinks."""
        if (
            not isinstance(relative_path, str)
            or not relative_path
            or relative_path.startswith("/")
            or "\\" in relative_path
            or ":" in relative_path
            or "\x00" in relative_path
            or any(part in {"", ".", ".."} for part in relative_path.split("/"))
        ):
            raise DataValidationError(
                self._challenges_path(ctf_id),
                "solver path must be a safe relative path within the challenge directory",
            )
        challenge_directory = self.challenge_directory(ctf_id, challenge_id)
        candidate = challenge_directory.joinpath(*relative_path.split("/"))
        parent = candidate.parent
        if create_parent:
            current = challenge_directory
            for component in relative_path.split("/")[:-1]:
                current = current / component
                if current.is_symlink():
                    raise DataFileError(
                        current, "refusing to follow a symlink in solver path"
                    )
                self._make_directory(current)
        current = challenge_directory
        for component in relative_path.split("/"):
            current = current / component
            if current.is_symlink():
                raise DataFileError(
                    current, "refusing to follow a symlink in solver path"
                )
        resolved = self._managed_path(candidate)
        if (
            resolved != candidate
            or resolved.parent != self._managed_path(parent)
            or not resolved.is_relative_to(challenge_directory)
        ):
            raise DataFileError(
                candidate, "solver path resolves outside the challenge directory"
            )
        if must_exist and not resolved.is_file():
            raise DataFileError(
                resolved, "solver file does not exist or is not a regular file"
            )
        return resolved

    def create_solver_file(
        self,
        ctf_id: str,
        challenge_id: str,
        relative_path: str,
        file_type: str,
        contents: str,
        *,
        overwrite_confirmed: bool = False,
    ) -> Path:
        """Atomically create a solver and persist its relative-path metadata."""
        if not isinstance(file_type, str) or file_type not in {"python", "bash"}:
            raise DataValidationError(
                self._challenges_path(ctf_id),
                "solver file type must be 'python' or 'bash'",
            )
        if not isinstance(contents, str):
            raise DataValidationError(
                self._challenges_path(ctf_id), "solver contents must be text"
            )
        target = self.resolve_challenge_file(
            ctf_id, challenge_id, relative_path, create_parent=True
        )
        exists = target.exists()
        if exists and not overwrite_confirmed:
            raise DataFileError(
                target, "solver file already exists; explicit confirmation is required"
            )
        if exists and not target.is_file():
            raise DataFileError(target, "solver destination is not a regular file")

        challenges = self.load_challenges(ctf_id)
        updated = [dict(record) for record in challenges]
        challenge = next(record for record in updated if record["id"] == challenge_id)
        challenge["solver"] = {"file_type": file_type, "relative_path": relative_path}

        temporary_name: str | None = None
        metadata_saved = False
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=target.parent,
                prefix=f".{target.name}.",
                suffix=".tmp",
                delete=False,
            ) as stream:
                temporary_name = stream.name
                stream.write(contents)
                stream.flush()
                os.fsync(stream.fileno())
            self.save_challenges(ctf_id, updated)
            metadata_saved = True
            if overwrite_confirmed:
                os.replace(temporary_name, target)
            else:
                os.link(temporary_name, target)
                os.unlink(temporary_name)
            temporary_name = None
        except FileExistsError as exc:
            if metadata_saved:
                self.save_challenges(ctf_id, challenges)
            raise DataFileError(
                target,
                "solver file already exists; explicit confirmation is required",
            ) from exc
        except OSError as exc:
            if metadata_saved:
                self.save_challenges(ctf_id, challenges)
            if not exists and target.exists() and not target.is_symlink():
                target.unlink()
            detail = exc.strerror or "filesystem operation failed"
            raise DataFileError(target, f"cannot create solver file: {detail}") from exc
        except Exception:
            if metadata_saved:
                self.save_challenges(ctf_id, challenges)
            if not exists and target.exists() and not target.is_symlink():
                target.unlink()
            raise
        finally:
            if temporary_name is not None:
                try:
                    os.unlink(temporary_name)
                except OSError:
                    pass
        return target

    def save_ctfd_token(self, ctf_id: str, base_url: str, token: str) -> None:
        """Store a CTFd token bound to one HTTPS base URL without making backups."""
        if not isinstance(base_url, str) or not isinstance(token, str) or not token:
            raise DataValidationError(
                self.data_dir / "ctfs" / str(ctf_id) / "token.json",
                "CTFd credentials require an HTTPS base URL and non-empty token",
            )
        normalized_url = normalize_ctfd_base_url(base_url)
        try:
            parsed = urlsplit(normalized_url)
            valid_url = (
                parsed.scheme == "https"
                and bool(parsed.hostname)
                and parsed.username is None
                and parsed.password is None
                and not parsed.query
                and not parsed.fragment
                and not any(character.isspace() for character in normalized_url)
            )
            _ = parsed.port
        except ValueError:
            valid_url = False
        path = self._ctf_directory_path(ctf_id) / "token.json"
        if not valid_url:
            raise DataValidationError(path, "CTFd base URL must be a valid HTTPS URL")
        if any(ord(character) < 32 or ord(character) == 127 for character in token):
            raise DataValidationError(
                path, "CTFd token contains invalid control characters"
            )
        if not any(record["id"] == ctf_id for record in self.load_ctfs()):
            raise DataValidationError(path, f"CTF ID '{ctf_id}' does not exist")
        if path.is_symlink():
            raise DataFileError(path, "refusing to replace a symlinked CTFd token file")
        self._make_directory(path.parent)
        path = self._managed_path(path)
        content = (
            json.dumps(
                {"base_url": normalized_url, "token": token},
                ensure_ascii=False,
                separators=(",", ":"),
            )
            + "\n"
        )
        temporary_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=".token.",
                suffix=".tmp",
                delete=False,
            ) as stream:
                temporary_name = stream.name
                os.chmod(temporary_name, 0o600)
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_name, path)
            temporary_name = None
            os.chmod(path, 0o600)
        except OSError as exc:
            raise DataFileError(path, "cannot securely save CTFd credentials") from exc
        finally:
            if temporary_name is not None:
                try:
                    os.unlink(temporary_name)
                except OSError:
                    pass

    def load_ctfd_token(self, ctf_id: str, base_url: str) -> str | None:
        """Return a stored token only when its configured HTTPS URL matches."""
        path = self._ctf_directory_path(ctf_id) / "token.json"
        if path.is_symlink():
            raise DataFileError(path, "refusing to read a symlinked CTFd token file")
        path = self._managed_path(path)
        if not path.exists():
            return None
        try:
            with path.open("r", encoding="utf-8") as stream:
                document = json.load(stream)
        except json.JSONDecodeError as exc:
            raise DataFileError(
                path,
                f"malformed CTFd credential JSON at line {exc.lineno}, column {exc.colno}",
            ) from exc
        except (UnicodeDecodeError, OSError) as exc:
            raise DataFileError(path, "cannot read CTFd credentials") from exc
        if (
            not isinstance(document, dict)
            or set(document) != {"base_url", "token"}
            or not isinstance(document["base_url"], str)
            or not isinstance(document["token"], str)
            or not document["token"]
        ):
            raise DataValidationError(path, "invalid CTFd credential document")
        requested_url = (
            normalize_ctfd_base_url(base_url) if isinstance(base_url, str) else ""
        )
        if document["base_url"] != requested_url:
            return None
        return document["token"]

    def ensure_challenge_notes_file(self, ctf_id: str, challenge_id: str) -> Path:
        """Return a safely managed Markdown notes file for an existing challenge.

        The notes file is created empty only when absent. Existing content is
        never opened for writing or replaced.
        """
        try:
            collection_path = self._challenges_path(ctf_id)
        except OSError as exc:
            detail = exc.strerror or "filesystem operation failed"
            raise DataFileError(
                self.data_dir / "ctfs", f"cannot resolve challenge collection: {detail}"
            ) from exc
        if not isinstance(challenge_id, str) or not _ID_RE.fullmatch(challenge_id):
            raise DataFileError(
                collection_path.parent,
                "challenge ID is not a valid application-generated ID",
            )

        try:
            challenges = self.load_challenges(ctf_id)
        except OSError as exc:
            detail = exc.strerror or "filesystem operation failed"
            raise DataFileError(
                collection_path, f"cannot load challenge collection: {detail}"
            ) from exc
        if not any(record["id"] == challenge_id for record in challenges):
            raise DataValidationError(
                collection_path, f"challenge ID '{challenge_id}' does not exist"
            )

        notes_path = collection_path.parent / challenge_id / "notes.md"
        try:
            challenges_directory = self._managed_path(collection_path.parent)
            challenge_directory = challenges_directory / challenge_id
            notes_path = challenge_directory / "notes.md"
            managed_notes_path = self._managed_path(notes_path)
            if (
                managed_notes_path.parent != challenge_directory
                or managed_notes_path != notes_path
            ):
                raise DataFileError(
                    notes_path, "notes path resolves outside its managed location"
                )

            if challenge_directory.is_symlink():
                raise DataFileError(
                    challenge_directory,
                    "refusing to use a symlinked challenge directory",
                )
            try:
                challenge_mode = challenge_directory.lstat().st_mode
            except FileNotFoundError:
                challenge_directory.mkdir(parents=True, exist_ok=True)
                challenge_mode = challenge_directory.lstat().st_mode
            if not stat.S_ISDIR(challenge_mode):
                raise DataFileError(
                    challenge_directory, "challenge path is not a directory"
                )
            # Re-resolve after creation to catch path changes and verify
            # containment against the configured data directory.
            managed_notes_path = self._managed_path(notes_path)
            if managed_notes_path.parent != challenge_directory:
                raise DataFileError(
                    notes_path, "notes path resolves outside its managed location"
                )

            def validate_existing_notes() -> None:
                if notes_path.is_symlink():
                    raise DataFileError(
                        notes_path, "refusing to use a symlinked notes file"
                    )
                descriptor = os.open(
                    notes_path,
                    os.O_RDONLY
                    | getattr(os, "O_NOFOLLOW", 0)
                    | getattr(os, "O_NONBLOCK", 0),
                )
                try:
                    if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                        raise DataFileError(
                            notes_path, "existing notes path is not a regular file"
                        )
                finally:
                    os.close(descriptor)

            try:
                notes_mode = notes_path.lstat().st_mode
            except FileNotFoundError:
                notes_mode = None
            if notes_mode is not None:
                if stat.S_ISLNK(notes_mode):
                    raise DataFileError(
                        notes_path, "refusing to use a symlinked notes file"
                    )
                if not stat.S_ISREG(notes_mode):
                    raise DataFileError(
                        notes_path, "existing notes path is not a regular file"
                    )
                validate_existing_notes()
                return notes_path

            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            flags |= getattr(os, "O_NOFOLLOW", 0)
            try:
                descriptor = os.open(notes_path, flags, 0o666)
            except FileExistsError:
                # Another creator may have won the exclusive-create race;
                # accept only a regular, non-symlink file.
                validate_existing_notes()
            else:
                os.close(descriptor)
            return notes_path
        except DataStoreError:
            raise
        except OSError as exc:
            detail = exc.strerror or "filesystem operation failed"
            raise DataFileError(
                notes_path, f"cannot ensure notes file: {detail}"
            ) from exc

    def read_challenge_notes(self, ctf_id: str, challenge_id: str) -> str:
        """Read a challenge's notes without creating a missing notes file."""
        collection_path = self._challenges_path(ctf_id)
        if not isinstance(challenge_id, str) or not _ID_RE.fullmatch(challenge_id):
            raise DataFileError(
                collection_path.parent,
                "challenge ID is not a valid application-generated ID",
            )

        try:
            challenges = self.load_challenges(ctf_id)
        except OSError as exc:
            detail = exc.strerror or "filesystem operation failed"
            raise DataFileError(
                collection_path, f"cannot load challenge collection: {detail}"
            ) from exc
        if not any(record["id"] == challenge_id for record in challenges):
            raise DataValidationError(
                collection_path, f"challenge ID '{challenge_id}' does not exist"
            )

        challenge_directory = collection_path.parent / challenge_id
        notes_path = challenge_directory / "notes.md"
        try:
            managed_challenges = self._managed_path(collection_path.parent)
            challenge_directory = managed_challenges / challenge_id
            notes_path = challenge_directory / "notes.md"
            if challenge_directory.is_symlink():
                raise DataFileError(
                    challenge_directory,
                    "refusing to use a symlinked challenge directory",
                )
            if self._managed_path(challenge_directory) != challenge_directory:
                raise DataFileError(
                    challenge_directory,
                    "challenge directory resolves outside its managed location",
                )
            try:
                challenge_mode = challenge_directory.lstat().st_mode
            except FileNotFoundError:
                return ""
            if not stat.S_ISDIR(challenge_mode):
                raise DataFileError(
                    challenge_directory, "challenge path is not a directory"
                )

            if self._managed_path(notes_path) != notes_path:
                raise DataFileError(
                    notes_path, "notes path resolves outside its managed location"
                )
            try:
                notes_mode = notes_path.lstat().st_mode
            except FileNotFoundError:
                return ""
            if stat.S_ISLNK(notes_mode):
                raise DataFileError(
                    notes_path, "refusing to use a symlinked notes file"
                )
            if not stat.S_ISREG(notes_mode):
                raise DataFileError(
                    notes_path, "existing notes path is not a regular file"
                )

            descriptor = os.open(
                notes_path,
                os.O_RDONLY
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_NONBLOCK", 0),
            )
            try:
                if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                    raise DataFileError(
                        notes_path, "existing notes path is not a regular file"
                    )
                with os.fdopen(descriptor, "r", encoding="utf-8") as stream:
                    descriptor = -1
                    return stream.read()
            finally:
                if descriptor >= 0:
                    os.close(descriptor)
        except DataStoreError:
            raise
        except UnicodeDecodeError as exc:
            raise DataFileError(
                notes_path, f"notes file is not valid UTF-8 at byte {exc.start}"
            ) from exc
        except OSError as exc:
            detail = exc.strerror or "filesystem operation failed"
            raise DataFileError(
                notes_path, f"cannot read notes file: {detail}"
            ) from exc

    def is_artifact_downloaded(
        self, ctf_id: str, challenge_id: str, filename: str
    ) -> bool:
        """Check whether a challenge's managed artifact file exists safely."""
        collection_path = self._challenges_path(ctf_id)
        if not isinstance(challenge_id, str) or not _ID_RE.fullmatch(challenge_id):
            raise DataFileError(
                collection_path.parent,
                "challenge ID is not a valid application-generated ID",
            )
        _validate_artifact({"filename": filename}, collection_path, 0)

        challenge_directory = collection_path.parent / challenge_id
        artifacts_directory = challenge_directory / "artifacts"
        artifact_path = artifacts_directory / filename
        try:
            if challenge_directory.is_symlink():
                raise DataFileError(
                    challenge_directory,
                    "refusing to use a symlinked challenge directory",
                )
            if self._managed_path(challenge_directory) != challenge_directory:
                raise DataFileError(
                    challenge_directory,
                    "challenge directory resolves outside its managed location",
                )
            try:
                challenge_mode = challenge_directory.lstat().st_mode
            except FileNotFoundError:
                return False
            if not stat.S_ISDIR(challenge_mode):
                raise DataFileError(
                    challenge_directory, "challenge path is not a directory"
                )

            if artifacts_directory.is_symlink():
                raise DataFileError(
                    artifacts_directory,
                    "refusing to use a symlinked artifacts directory",
                )
            if self._managed_path(artifacts_directory) != artifacts_directory:
                raise DataFileError(
                    artifacts_directory,
                    "artifacts directory resolves outside its managed location",
                )
            try:
                artifacts_mode = artifacts_directory.lstat().st_mode
            except FileNotFoundError:
                return False
            if not stat.S_ISDIR(artifacts_mode):
                raise DataFileError(
                    artifacts_directory, "artifacts path is not a directory"
                )

            if self._managed_path(artifact_path) != artifact_path:
                raise DataFileError(
                    artifact_path, "artifact path resolves outside its managed location"
                )
            try:
                artifact_mode = artifact_path.lstat().st_mode
            except FileNotFoundError:
                return False
            if stat.S_ISLNK(artifact_mode):
                raise DataFileError(
                    artifact_path, "refusing to use a symlinked artifact file"
                )
            if not stat.S_ISREG(artifact_mode):
                raise DataFileError(
                    artifact_path, "artifact path is not a regular file"
                )
            return True
        except DataStoreError:
            raise
        except OSError as exc:
            detail = exc.strerror or "filesystem operation failed"
            raise DataFileError(
                artifact_path, f"cannot check artifact file: {detail}"
            ) from exc

    def save_artifact(
        self,
        ctf_id: str,
        challenge_id: str,
        filename: str,
        chunks: Iterable[bytes],
        *,
        overwrite: bool = False,
    ) -> Path:
        """Atomically save a registered artifact beneath its challenge directory."""
        collection_path = self._challenges_path(ctf_id)
        if not isinstance(challenge_id, str) or not _ID_RE.fullmatch(challenge_id):
            raise DataFileError(
                collection_path.parent,
                "challenge ID is not a valid application-generated ID",
            )
        _validate_artifact({"filename": filename}, collection_path, 0)
        if not isinstance(overwrite, bool):
            raise DataValidationError(collection_path, "overwrite must be a boolean")

        ctf_directory = self._ctf_directory_path(ctf_id)
        challenges_directory = ctf_directory / "challenges"
        if challenges_directory.is_symlink():
            raise DataFileError(
                challenges_directory,
                "refusing to use a symlinked challenges directory",
            )
        if self._managed_path(challenges_directory) != challenges_directory:
            raise DataFileError(
                challenges_directory,
                "challenges directory resolves outside its managed location",
            )
        challenge = next(
            (
                record
                for record in self.load_challenges(ctf_id)
                if record["id"] == challenge_id
            ),
            None,
        )
        if challenge is None:
            raise DataFileError(collection_path, "challenge does not exist")
        if not any(
            isinstance(artifact, Mapping) and artifact.get("filename") == filename
            for artifact in challenge["artifacts"]
        ):
            raise DataFileError(
                collection_path,
                "artifact filename is not registered for this challenge",
            )

        challenge_directory = challenges_directory / challenge_id
        artifacts_directory = challenge_directory / "artifacts"
        artifact_path = artifacts_directory / filename
        temporary_name: str | None = None
        try:
            if challenge_directory.is_symlink():
                raise DataFileError(
                    challenge_directory,
                    "refusing to use a symlinked challenge directory",
                )
            if self._managed_path(challenge_directory) != challenge_directory:
                raise DataFileError(
                    challenge_directory,
                    "challenge directory resolves outside its managed location",
                )
            self._make_directory(challenge_directory)
            if self._managed_path(challenge_directory) != challenge_directory:
                raise DataFileError(
                    challenge_directory,
                    "challenge directory resolves outside its managed location",
                )
            if artifacts_directory.is_symlink():
                raise DataFileError(
                    artifacts_directory,
                    "refusing to use a symlinked artifacts directory",
                )
            if self._managed_path(artifacts_directory) != artifacts_directory:
                raise DataFileError(
                    artifacts_directory,
                    "artifacts directory resolves outside its managed location",
                )
            self._make_directory(artifacts_directory)
            if self._managed_path(artifacts_directory) != artifacts_directory:
                raise DataFileError(
                    artifacts_directory,
                    "artifacts directory resolves outside its managed location",
                )
            if self._managed_path(artifact_path) != artifact_path:
                raise DataFileError(
                    artifact_path,
                    "artifact path resolves outside its managed location",
                )
            try:
                artifact_mode = artifact_path.lstat().st_mode
            except FileNotFoundError:
                artifact_mode = None
            if artifact_mode is not None:
                if stat.S_ISLNK(artifact_mode):
                    raise DataFileError(
                        artifact_path, "refusing to use a symlinked artifact file"
                    )
                if not stat.S_ISREG(artifact_mode):
                    raise DataFileError(
                        artifact_path, "artifact path is not a regular file"
                    )
                if not overwrite:
                    raise DataFileError(
                        artifact_path,
                        "artifact already exists; explicit overwrite confirmation is required",
                    )

            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=artifacts_directory,
                prefix=".ctfwb-artifact-",
                suffix=".tmp",
                delete=False,
            ) as stream:
                temporary_name = stream.name
                os.chmod(temporary_name, 0o600)
                for chunk in chunks:
                    if not isinstance(chunk, bytes):
                        raise DataFileError(
                            artifact_path, "artifact download returned invalid data"
                        )
                    stream.write(chunk)
                stream.flush()
                os.fsync(stream.fileno())

            if artifact_path.is_symlink():
                raise DataFileError(
                    artifact_path, "refusing to replace a symlinked artifact file"
                )
            if overwrite:
                os.replace(temporary_name, artifact_path)
                temporary_name = None
            else:
                os.link(temporary_name, artifact_path)
                os.unlink(temporary_name)
                temporary_name = None
            try:
                directory_fd = os.open(artifacts_directory, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            except OSError:
                pass
            return artifact_path
        except DataStoreError:
            raise
        except OSError as exc:
            detail = exc.strerror or "filesystem operation failed"
            raise DataFileError(
                artifact_path, f"cannot save artifact atomically: {detail}"
            ) from exc
        finally:
            if temporary_name is not None:
                try:
                    os.unlink(temporary_name)
                except OSError:
                    pass

    def save_challenges(
        self, ctf_id: str, records: Sequence[Mapping[str, object]]
    ) -> None:
        path = self._challenges_path(ctf_id)
        self._make_directory(path.parent)
        validated = self._validate_collection(records, path, _validate_challenge)
        if path.exists():
            self._read_document(path, "challenges", _validate_challenge)
            self._backup(path)
        self._atomic_write(path, "challenges", validated)
        self._remove_backups(path)

    @staticmethod
    def _validate_collection(
        records: Sequence[Mapping[str, object]], path: Path, validator: Any
    ) -> list[dict[str, object]]:
        if isinstance(records, (str, bytes)) or not isinstance(records, Sequence):
            raise DataValidationError(path, "records must be a sequence of objects")
        validated: list[dict[str, object]] = []
        ids: set[str] = set()
        for index, record in enumerate(records):
            if not isinstance(record, Mapping):
                raise DataValidationError(path, f"record {index} must be an object")
            normalized = validator(record, path)
            if normalized["id"] in ids:
                raise DataValidationError(path, f"record {index} has a duplicate id")
            ids.add(str(normalized["id"]))
            validated.append(normalized)
        return validated

    def _ctf_directory_path(self, ctf_id: str) -> Path:
        if not isinstance(ctf_id, str) or not _ID_RE.fullmatch(ctf_id):
            raise DataFileError(
                self.data_dir / "ctfs", "CTF ID is not a valid application-generated ID"
            )
        ctfs_directory = self._managed_path(self.data_dir / "ctfs")
        path = ctfs_directory / ctf_id
        if path.is_symlink():
            raise DataFileError(path, "refusing to follow a symlinked CTF directory")
        resolved = self._managed_path(path)
        if resolved.parent != ctfs_directory:
            raise DataFileError(
                path, "CTF directory resolves outside its managed location"
            )
        return resolved

    def lock(self) -> DataDirectoryLock:
        """Return the data-directory lock as a context manager."""
        return DataDirectoryLock(self.data_dir)

    def acquire(self) -> None:
        """Acquire and retain this store's lock until :meth:`release`."""
        if self._lock is not None and self._lock.acquired:
            raise LockError(
                f"data directory is already locked by this DataStore: {self.data_dir}"
            )
        self._lock = self.lock()
        self._lock.acquire()

    def release(self) -> None:
        """Release a lock acquired through :meth:`acquire`."""
        if self._lock is not None:
            self._lock.release()
            self._lock = None
