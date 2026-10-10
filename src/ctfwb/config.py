"""Application settings and operating-system-aware user directories."""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib  # type: ignore[no-redef]


class ConfigError(Exception):
    """A configuration file could not be read or validated."""

    def __init__(self, path: Path, message: str) -> None:
        self.path = path
        super().__init__(f"{path}: {message}")


def _user_config_dir() -> Path:
    if os.name == "nt":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming"))
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support"
    default = Path.home() / ".config"
    candidate = Path(os.environ.get("XDG_CONFIG_HOME", default))
    return candidate if candidate.is_absolute() else default


def _user_data_dir() -> Path:
    if os.name == "nt":
        fallback = os.environ.get("APPDATA", Path.home() / "AppData/Local")
        return Path(os.environ.get("LOCALAPPDATA", fallback))
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support"
    default = Path.home() / ".local" / "share"
    candidate = Path(os.environ.get("XDG_DATA_HOME", default))
    return candidate if candidate.is_absolute() else default


@dataclass(frozen=True)
class AppConfig:
    """Resolved configuration paths for the application.

    The data directory can be set by top-level ``data_dir`` or
    ``[paths].data_dir``. Editor and solver options use ``[editor]`` and
    ``[solver]`` tables. Relative data paths resolve from the config file.
    """

    data_dir: Path
    config_path: Path
    editor: str = "nvim"
    editor_args: tuple[str, ...] = ()
    python_interpreter: str | None = None
    solver_timeout_seconds: float = 30.0
    bash_execution_enabled: bool = False

    @classmethod
    def load(cls, config_path: Path | None = None) -> AppConfig:
        """Load optional TOML settings and resolve user data/config paths."""
        config_file = (
            Path(config_path).expanduser()
            if config_path is not None
            else _user_config_dir() / "ctf-workbench" / "config.toml"
        )
        config_file = config_file.resolve()
        data_dir = _user_data_dir() / "ctf-workbench"

        try:
            with config_file.open("rb") as stream:
                settings: Any = tomllib.load(stream)
        except FileNotFoundError:
            settings = {}
        except tomllib.TOMLDecodeError as exc:
            line = getattr(exc, "lineno", None)
            column = getattr(exc, "colno", None)
            if not (line and column):
                match = re.search(r"\(at line ([0-9]+), column ([0-9]+)\)$", str(exc))
                if match:
                    line, column = int(match.group(1)), int(match.group(2))
            location = f" at line {line}, column {column}" if line and column else ""
            raise ConfigError(config_file, f"invalid TOML syntax{location}") from exc
        except OSError as exc:
            raise ConfigError(
                config_file, f"cannot read configuration: {exc.strerror}"
            ) from exc

        if not isinstance(settings, dict):
            raise ConfigError(config_file, "configuration must be a TOML table")
        paths = settings.get("paths", {})
        if not isinstance(paths, dict):
            raise ConfigError(config_file, "'paths' must be a TOML table")
        override = paths.get("data_dir", settings.get("data_dir"))
        if override is not None:
            if not isinstance(override, str) or not override.strip():
                raise ConfigError(
                    config_file, "'data_dir' must be a non-empty path string"
                )
            candidate = Path(override).expanduser()
            data_dir = (
                candidate if candidate.is_absolute() else config_file.parent / candidate
            )

        editor_section = settings.get("editor", {})
        if not isinstance(editor_section, dict):
            raise ConfigError(config_file, "'editor' must be a TOML table")
        editor = editor_section.get("executable")
        if editor is not None and (not isinstance(editor, str) or not editor.strip()):
            raise ConfigError(
                config_file, "'editor.executable' must be a non-empty string"
            )
        editor_args = editor_section.get("args", [])
        if not isinstance(editor_args, list) or any(
            not isinstance(argument, str) for argument in editor_args
        ):
            raise ConfigError(config_file, "'editor.args' must be an array of strings")

        solver_section = settings.get("solver", {})
        if not isinstance(solver_section, dict):
            raise ConfigError(config_file, "'solver' must be a TOML table")
        python_interpreter = solver_section.get("python_interpreter")
        if python_interpreter is not None and (
            not isinstance(python_interpreter, str) or not python_interpreter.strip()
        ):
            raise ConfigError(
                config_file,
                "'solver.python_interpreter' must be a non-empty string",
            )
        timeout = solver_section.get("timeout_seconds", 30.0)
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not isfinite(timeout)
            or timeout <= 0
        ):
            raise ConfigError(
                config_file, "'solver.timeout_seconds' must be a positive number"
            )
        bash_enabled = solver_section.get("bash_execution_enabled", False)
        if not isinstance(bash_enabled, bool):
            raise ConfigError(
                config_file, "'solver.bash_execution_enabled' must be a boolean"
            )

        return cls(
            data_dir=data_dir.resolve(),
            config_path=config_file,
            editor=editor.strip() if isinstance(editor, str) else "nvim",
            editor_args=tuple(editor_args),
            python_interpreter=(
                python_interpreter.strip()
                if isinstance(python_interpreter, str)
                else None
            ),
            solver_timeout_seconds=float(timeout),
            bash_execution_enabled=bash_enabled,
        )
