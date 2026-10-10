"""Helpers for inspecting and extracting individual ZIP archive members."""

from __future__ import annotations

import stat
import zipfile
from pathlib import Path


def list_zip_files(archive_path: str | Path) -> list[str]:
    """Return non-directory, non-symlink member names from a ZIP archive."""
    with zipfile.ZipFile(archive_path) as archive:
        return [
            member.filename
            for member in archive.infolist()
            if not member.is_dir() and _is_regular_file(member)
        ]


def extract_zip_member(
    archive_path: str | Path,
    member_name: str,
) -> bytes:
    """Read one regular member from a ZIP archive and return its bytes."""
    with zipfile.ZipFile(archive_path) as archive:
        matches = [
            member for member in archive.infolist() if member.filename == member_name
        ]
        if len(matches) != 1:
            raise ValueError(f"ZIP member must occur exactly once: {member_name!r}")
        member = matches[0]
        if member.is_dir() or _is_symlink(member) or not _is_regular_file(member):
            raise ValueError(f"ZIP member is not a regular file: {member_name!r}")
        return archive.read(member)


def _is_symlink(member: zipfile.ZipInfo) -> bool:
    return stat.S_ISLNK(member.external_attr >> 16)


def _is_regular_file(member: zipfile.ZipInfo) -> bool:
    file_type = stat.S_IFMT(member.external_attr >> 16)
    return file_type in {0, stat.S_IFREG}
