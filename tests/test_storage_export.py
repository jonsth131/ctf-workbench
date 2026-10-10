import json
from zipfile import ZipFile

import pytest

from ctfwb.storage import DataFileError, DataStore, generate_id, utc_timestamp


@pytest.fixture
def store(tmp_path):
    return DataStore(tmp_path / "managed-data")


def _ctf():
    return {
        "id": generate_id(),
        "name": "Archive test",
        "year": 2026,
        "platform_url": None,
        "description": "",
        "source": "manual",
        "created_at": utc_timestamp(),
        "updated_at": utc_timestamp(),
    }


def _challenge(flag="flag{private}"):
    return {
        "id": generate_id(),
        "name": "Archive challenge",
        "category": "misc",
        "points": 50,
        "description": "A challenge",
        "artifacts": [],
        "status": "solved",
        "flag": flag,
        "source": "manual",
        "remote_id": None,
        "solver": None,
        "created_at": utc_timestamp(),
        "updated_at": utc_timestamp(),
    }


def _create_challenge_tree(store, *, flag="flag{private}"):
    ctf = _ctf()
    challenge = _challenge(flag)
    store.save_ctfs([ctf])
    store.save_challenges(ctf["id"], [challenge])
    directory = store.challenge_directory(ctf["id"], challenge["id"])
    return ctf, challenge, directory


def test_export_excludes_token_files_logs_locks_and_temporary_files(store, tmp_path):
    ctf, _, challenge_directory = _create_challenge_tree(store)
    token_files = [
        store.data_dir / "token.json",
        store.data_dir / "ctfs" / "token.json",
        store.data_dir / "ctfs" / ctf["id"] / "token.json",
        challenge_directory / "token.json",
    ]
    for path in token_files:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"token":"private"}', encoding="utf-8")

    (store.data_dir / ".ctf-workbench.lock").write_text("lock", encoding="utf-8")
    (store.data_dir / ".ctfs.json.transient.tmp").write_text("temp", encoding="utf-8")
    (store.data_dir / "logs").mkdir()
    (store.data_dir / "logs" / "ctf-workbench.log").write_text("log", encoding="utf-8")
    (store.data_dir / "extra.log").write_text("log", encoding="utf-8")

    archive_path = store.export_archive(tmp_path / "backup.zip")

    with ZipFile(archive_path) as archive:
        names = archive.namelist()
    assert not any(name.casefold().endswith("token.json") for name in names)
    assert not any("/logs/" in f"/{name}" for name in names)
    assert not any(name.endswith((".lock", ".tmp", ".log")) for name in names)


def test_export_redacts_flags_unless_explicitly_included(store, tmp_path):
    ctf, challenge, _ = _create_challenge_tree(store)
    redacted_path = store.export_archive(tmp_path / "redacted.zip")
    included_path = store.export_archive(
        tmp_path / "with-flags.zip", include_flags=True
    )
    information_name = f"ctfs/{ctf['id']}/challenges/information.json"

    with ZipFile(redacted_path) as archive:
        exported = json.loads(archive.read(information_name))
    assert "flag" not in exported["challenges"][0]

    with ZipFile(included_path) as archive:
        exported = json.loads(archive.read(information_name))
    assert exported["challenges"][0]["flag"] == challenge["flag"]


def test_export_preserves_user_notes_solver_and_artifact_content(store, tmp_path):
    _, _, challenge_directory = _create_challenge_tree(store)
    notes = "Important local notes."
    solver = "print('solver')\n"
    artifact = b"\x00artifact contents"
    (challenge_directory / "notes.md").write_text(notes, encoding="utf-8")
    (challenge_directory / "solve.py").write_text(solver, encoding="utf-8")
    artifacts_directory = challenge_directory / "artifacts"
    artifacts_directory.mkdir()
    (artifacts_directory / "download.bin").write_bytes(artifact)

    archive_path = store.export_archive(tmp_path / "preserved.zip")

    with ZipFile(archive_path) as archive:
        files = archive.namelist()
        assert any(name.endswith("/notes.md") for name in files)
        assert any(name.endswith("/solve.py") for name in files)
        assert any(name.endswith("/artifacts/download.bin") for name in files)
        assert next(
            archive.read(name) for name in files if name.endswith("/notes.md")
        ) == (notes.encode())
        assert next(
            archive.read(name) for name in files if name.endswith("/solve.py")
        ) == (solver.encode())
        assert (
            next(
                archive.read(name)
                for name in files
                if name.endswith("/artifacts/download.bin")
            )
            == artifact
        )


def test_export_never_overwrites_existing_archive(store, tmp_path):
    _create_challenge_tree(store)
    destination = tmp_path / "existing.zip"
    destination.write_bytes(b"keep this file")

    with pytest.raises(DataFileError, match="already exists"):
        store.export_archive(destination)

    assert destination.read_bytes() == b"keep this file"


def test_export_rejects_recursive_destination_and_symlink_inputs(store, tmp_path):
    _create_challenge_tree(store)
    with pytest.raises(DataFileError, match="outside"):
        store.export_archive(store.data_dir / "nested" / "backup.zip")

    outside_file = tmp_path / "outside.txt"
    outside_file.write_text("do not follow", encoding="utf-8")
    (store.data_dir / "linked.txt").symlink_to(outside_file)
    destination = tmp_path / "unsafe.zip"

    with pytest.raises(DataFileError, match="symlink"):
        store.export_archive(destination)

    assert not destination.exists()


def test_export_failure_is_sanitized_and_leaves_no_archive(
    store, tmp_path, monkeypatch
):
    _create_challenge_tree(store)
    sensitive_error = "flag{do-not-leak-this}"

    def fail_write(*args, **kwargs):
        raise PermissionError(sensitive_error)

    monkeypatch.setattr(DataStore, "_write_export_file", staticmethod(fail_write))
    destination = tmp_path / "failed.zip"

    with pytest.raises(DataFileError) as error:
        store.export_archive(destination)

    assert sensitive_error not in str(error.value)
    assert not destination.exists()
