"""Convenience helpers for solvers; these APIs are not a security boundary."""

from ctfwb.tools.external import ExternalToolHelper
from ctfwb.tools.files import read_bytes, read_text, sha256_file
from ctfwb.tools.general import EXIFTOOL, exiftool
from ctfwb.tools.general import TOOL_HELPERS as GENERAL_TOOL_HELPERS
from ctfwb.tools.network import TOOL_HELPERS as NETWORK_TOOL_HELPERS
from ctfwb.tools.network import TSHARK
from ctfwb.tools.steg import STEGHIDE, ZSTEG
from ctfwb.tools.steg import TOOL_HELPERS as STEG_TOOL_HELPERS
from ctfwb.tools.zipfiles import extract_zip_member, list_zip_files

TOOL_HELPERS = (
    *GENERAL_TOOL_HELPERS,
    *STEG_TOOL_HELPERS,
    *NETWORK_TOOL_HELPERS,
)

__all__ = [
    "EXIFTOOL",
    "STEGHIDE",
    "TSHARK",
    "TOOL_HELPERS",
    "ExternalToolHelper",
    "ZSTEG",
    "exiftool",
    "read_bytes",
    "read_text",
    "sha256_file",
    "extract_zip_member",
    "list_zip_files",
]
