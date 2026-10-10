"""Helpers for launching the configured text editor."""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path


def run_editor(executable: str, arguments: Sequence[str], file_path: Path) -> int:
    """Run an editor on a file and return its exit status.

    Launch errors such as a missing executable are intentionally allowed to
    propagate to the caller.
    """
    result = subprocess.run(
        [executable, *arguments, str(file_path)],
        check=False,
    )
    return result.returncode
