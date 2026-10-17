"""ExifTool helper for solver metadata extraction."""

from __future__ import annotations

import json
from pathlib import Path

from ctfwb.tools.external import ExternalToolHelper

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
