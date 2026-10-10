"""Private rotating file logging for CTF Workbench."""

from __future__ import annotations

import logging
import os
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path

APP_LOGGER = logging.getLogger("ctfwb")


class _PrivateRotatingFileHandler(RotatingFileHandler):
    """Create log files with owner-only permissions on POSIX systems."""

    def _open(self):
        if os.name == "nt":
            return super()._open()

        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(self.baseFilename, flags, 0o600)
        try:
            os.fchmod(descriptor, 0o600)
            return os.fdopen(
                descriptor,
                self.mode,
                encoding=self.encoding,
                errors=self.errors,
            )
        except Exception:
            os.close(descriptor)
            raise


def configure_file_logging(log_directory: Path, *, debug: bool) -> Path:
    """Configure a bounded application log and return its path."""
    log_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    log_path = log_directory / "ctf-workbench.log"

    for handler in APP_LOGGER.handlers[:]:
        APP_LOGGER.removeHandler(handler)
        handler.close()

    APP_LOGGER.setLevel(logging.DEBUG)
    APP_LOGGER.propagate = False
    handler = _PrivateRotatingFileHandler(
        log_path,
        maxBytes=1_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    handler.setLevel(logging.DEBUG if debug else logging.ERROR)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    APP_LOGGER.addHandler(handler)
    return log_path


def close_file_logging() -> None:
    """Flush and close configured application log files."""
    for handler in APP_LOGGER.handlers[:]:
        APP_LOGGER.removeHandler(handler)
        handler.close()


def log_debug_exception(message: str, error: BaseException) -> None:
    """Log exception type and traceback frames only when debug logging is active.

    Exception messages are deliberately omitted because network and subprocess
    errors can echo credentials or other sensitive request data.
    """
    if not any(handler.level <= logging.DEBUG for handler in APP_LOGGER.handlers):
        return
    stack = "".join(traceback.format_tb(error.__traceback__)).rstrip()
    details = f"{message} ({type(error).__name__})"
    if stack:
        details = f"{details}\n{stack}"
    APP_LOGGER.debug("%s", details)
