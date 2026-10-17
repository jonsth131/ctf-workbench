import json
import stat
import zipfile

import pytest

from ctfwb.tools import (
    EXIFTOOL,
    STEGHIDE,
    TOOL_HELPERS,
    TSHARK,
    ZSTEG,
    ExternalToolHelper,
    exiftool,
    extract_zip_member,
    list_zip_files,
)
from ctfwb.tools.external import subprocess as exiftool_subprocess
from ctfwb.tools.network import TSHARK as TSHARK_CATEGORY_HELPER
from ctfwb.tools.steg import STEGHIDE as STEGHIDE_CATEGORY_HELPER
from ctfwb.tools.steg import ZSTEG as ZSTEG_CATEGORY_HELPER


def test_exiftool_is_registered():
    assert EXIFTOOL in TOOL_HELPERS
    assert EXIFTOOL.name == "exiftool"


def test_steghide_is_registered_in_steg_category():
    assert STEGHIDE is STEGHIDE_CATEGORY_HELPER
    assert STEGHIDE in TOOL_HELPERS
    assert STEGHIDE.name == "steghide"
    assert STEGHIDE.executable == "steghide"


def test_zsteg_is_registered_in_steg_category():
    assert ZSTEG is ZSTEG_CATEGORY_HELPER
    assert ZSTEG in TOOL_HELPERS
    assert ZSTEG.name == "zsteg"
    assert ZSTEG.executable == "zsteg"


def test_tshark_is_registered_in_network_category():
    assert TSHARK is TSHARK_CATEGORY_HELPER
    assert TSHARK in TOOL_HELPERS
    assert TSHARK.name == "tshark"
    assert TSHARK.executable == "tshark"


def test_exiftool_parses_metadata_and_passes_path_as_argument(monkeypatch, tmp_path):
    path = tmp_path / "--image with spaces.jpg"
    observed = []

    def run(arguments, **kwargs):
        observed.append((arguments, kwargs))
        return exiftool_subprocess.CompletedProcess(
            arguments,
            0,
            stdout=json.dumps([{"FileName": path.name, "ImageWidth": 640}]),
            stderr="",
        )

    monkeypatch.setattr(exiftool_subprocess, "run", run)

    assert exiftool(path) == {"FileName": path.name, "ImageWidth": 640}
    assert observed == [
        (
            ["exiftool", "-json", "--", str(path)],
            {
                "check": True,
                "capture_output": True,
                "text": True,
                "timeout": 30.0,
            },
        )
    ]


@pytest.mark.parametrize("output", ["{}", "[]", "[null]", '[{"valid": true}, null]'])
def test_exiftool_rejects_unexpected_json_result(monkeypatch, output):
    monkeypatch.setattr(
        ExternalToolHelper,
        "run",
        lambda self, *args, **kwargs: output,
    )

    with pytest.raises(ValueError, match="unexpected JSON result"):
        exiftool("image.jpg")


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan")])
def test_external_tool_timeout_must_be_finite_and_positive(timeout):
    with pytest.raises(ValueError, match="finite positive"):
        EXIFTOOL.run("version", timeout=timeout)


def test_list_zip_files_excludes_directories_and_symlinks(tmp_path):
    archive_path = tmp_path / "files.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("folder/", "")
        archive.writestr("folder/image with spaces.bin", b"contents")
        symlink = zipfile.ZipInfo("link")
        symlink.create_system = 3
        symlink.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(symlink, "target")

    assert list_zip_files(archive_path) == ["folder/image with spaces.bin"]


def test_extract_zip_member_returns_bytes_without_writing_files(tmp_path):
    archive_path = tmp_path / "files.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("nested/file with spaces.bin", b"contents")

    extracted = extract_zip_member(archive_path, "nested/file with spaces.bin")

    assert extracted == b"contents"
    assert list(tmp_path.iterdir()) == [archive_path]


def test_extract_zip_member_rejects_duplicate_names(tmp_path):
    archive_path = tmp_path / "files.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("file.txt", b"one")
        with pytest.warns(UserWarning, match="Duplicate name"):
            archive.writestr("file.txt", b"two")

    with pytest.raises(ValueError, match="exactly once"):
        extract_zip_member(archive_path, "file.txt")


def test_extract_zip_member_rejects_symlink_archive_member(tmp_path):
    archive_path = tmp_path / "files.zip"
    symlink = zipfile.ZipInfo("link")
    symlink.create_system = 3
    symlink.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(symlink, "target")

    with pytest.raises(ValueError, match="not a regular file"):
        extract_zip_member(archive_path, "link")
