"""Exclusive data-directory locking and conservative stale-lock recovery."""

from __future__ import annotations

import errno
import json
import os
import socket
import stat
import uuid
from pathlib import Path

from ctfwb.storage.schema import LockError, utc_timestamp


class DataDirectoryLock:
    """Exclusive per-data-directory lock with conservative stale-PID recovery."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir).resolve()
        self.path = self.data_dir / ".ctf-workbench.lock"
        self._token = uuid.uuid4().hex
        self._acquired = False

    @property
    def acquired(self) -> bool:
        return self._acquired

    def _payload(self) -> bytes:
        return (
            json.dumps(
                {
                    "pid": os.getpid(),
                    "host": socket.gethostname(),
                    "token": self._token,
                    "created_at": utc_timestamp(),
                }
            ).encode("utf-8")
            + b"\n"
        )

    @staticmethod
    def _pid_is_alive(pid: object) -> bool:
        if type(pid) is not int or pid <= 0:
            return True  # Unknown/malformed owners are not safe to evict.
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError as exc:
            return exc.errno != errno.ESRCH
        return True

    def _is_stale_same_host(self, contents: bytes) -> bool:
        try:
            details = json.loads(contents.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return False
        return (
            isinstance(details, dict)
            and details.get("host") == socket.gethostname()
            and not self._pid_is_alive(details.get("pid"))
        )

    def _remove_if_stale(self) -> None:
        recovery_path = self.path.with_name(self.path.name + ".recovery")
        try:
            recovery_fd = os.open(
                recovery_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600
            )
        except FileExistsError:
            try:
                before_recovery = recovery_path.lstat()
                if not stat.S_ISREG(before_recovery.st_mode):
                    return
                existing = recovery_path.read_bytes()
                if not self._is_stale_same_host(existing):
                    return
                current_recovery = recovery_path.lstat()
                if stat.S_ISREG(current_recovery.st_mode) and (
                    before_recovery.st_dev,
                    before_recovery.st_ino,
                ) == (current_recovery.st_dev, current_recovery.st_ino):
                    recovery_path.unlink()
            except (FileNotFoundError, OSError):
                return
            try:
                recovery_fd = os.open(
                    recovery_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600
                )
            except FileExistsError:
                return
        try:
            recovery_token = uuid.uuid4().hex
            recovery_payload = json.dumps(
                {
                    "pid": os.getpid(),
                    "host": socket.gethostname(),
                    "token": recovery_token,
                }
            ).encode("utf-8")
            with os.fdopen(recovery_fd, "wb") as recovery_stream:
                recovery_stream.write(recovery_payload)
                recovery_stream.flush()
                os.fsync(recovery_stream.fileno())
            try:
                before = self.path.lstat()
                if not stat.S_ISREG(before.st_mode):
                    return
                contents = self.path.read_bytes()
            except FileNotFoundError:
                return
            if not self._is_stale_same_host(contents):
                return
            try:
                current = self.path.lstat()
                if stat.S_ISREG(current.st_mode) and (before.st_dev, before.st_ino) == (
                    current.st_dev,
                    current.st_ino,
                ):
                    self.path.unlink()
            except FileNotFoundError:
                pass
        finally:
            try:
                owner = json.loads(recovery_path.read_text(encoding="utf-8"))
                if isinstance(owner, dict) and owner.get("token") == recovery_token:
                    recovery_path.unlink()
            except FileNotFoundError:
                pass
            except (
                OSError,
                json.JSONDecodeError,
                UnicodeDecodeError,
                UnboundLocalError,
            ):
                pass

    def acquire(self) -> None:
        if self._acquired:
            return
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise LockError(
                f"cannot create data directory {self.data_dir}: {exc.strerror}"
            ) from exc
        try:
            descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            try:
                self._remove_if_stale()
            except OSError as exc:
                raise LockError(
                    f"cannot inspect stale data directory lock {self.path}: {exc.strerror}"
                ) from exc
            try:
                descriptor = os.open(
                    self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600
                )
            except FileExistsError as exc:
                raise LockError(
                    f"another application instance holds the data directory lock: {self.path}"
                ) from exc
        except OSError as exc:
            raise LockError(
                f"cannot create data directory lock {self.path}: {exc.strerror}"
            ) from exc
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(self._payload())
                stream.flush()
                os.fsync(stream.fileno())
        except OSError as exc:
            try:
                self.path.unlink()
            except OSError:
                pass
            raise LockError(
                f"cannot write data directory lock {self.path}: {exc.strerror}"
            ) from exc
        self._acquired = True

    def release(self) -> None:
        if not self._acquired:
            return
        try:
            before = self.path.lstat()
            if not stat.S_ISREG(before.st_mode):
                raise LockError(
                    f"data directory lock was replaced unexpectedly: {self.path}"
                )
            owner = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(owner, dict) and owner.get("token") == self._token:
                current = self.path.lstat()
                if stat.S_ISREG(current.st_mode) and (before.st_dev, before.st_ino) == (
                    current.st_dev,
                    current.st_ino,
                ):
                    self.path.unlink()
        except FileNotFoundError:
            pass
        except LockError:
            raise
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise LockError(
                f"cannot safely release data directory lock {self.path}: {exc}"
            ) from exc
        finally:
            self._acquired = False

    def __enter__(self) -> DataDirectoryLock:
        self.acquire()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.release()
