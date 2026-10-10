"""Registered wrappers for optional external tools used by solvers."""

from __future__ import annotations

import json
import math
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ExternalToolHelper:
    """An external executable exposed through a solver helper."""

    name: str
    executable: str

    def find_executable(self) -> str | None:
        """Return the executable path when it is available on ``PATH``."""
        return shutil.which(self.executable)

    def run(self, *arguments: str | Path, timeout: float = 30.0) -> str:
        """Run the tool without a shell and return its standard output."""
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be a finite positive number")
        result = subprocess.run(
            [self.executable, *(str(argument) for argument in arguments)],
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.stdout


EXIFTOOL = ExternalToolHelper(name="exiftool", executable="exiftool")
TOOL_HELPERS: tuple[ExternalToolHelper, ...] = (EXIFTOOL,)


def exiftool(path: str | Path, *, timeout: float = 30.0) -> dict[str, object]:
    """Return ExifTool's JSON metadata for one file."""
    result = json.loads(EXIFTOOL.run("-json", "--", path, timeout=timeout))
    if (
        not isinstance(result, list)
        or len(result) != 1
        or not isinstance(result[0], dict)
        or not all(isinstance(key, str) for key in result[0])
    ):
        raise ValueError("exiftool returned an unexpected JSON result")
    return result[0]
