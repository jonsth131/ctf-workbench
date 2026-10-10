import json
import os
import socket

import pytest

from ctfwb.storage import (
    DataDirectoryLock,
    DataFileError,
    DataStore,
    DataValidationError,
    LockError,
    generate_id,
    utc_timestamp,
)


@pytest.fixture
def store(tmp_path):
    return DataStore(tmp_path / "user-data")


def ctf_record(**overrides):
    return {
        "id": generate_id(),
        "name": "  DEF CON quals  ",
        "year": 2025,
        "platform_url": None,
        "description": "",
        "source": "manual",
        "created_at": utc_timestamp(),
        "updated_at": utc_timestamp(),
        **overrides,
    }


def challenge_record(**overrides):
    return {
        "id": generate_id(),
        "name": "Warmup",
        "category": "web",
        "points": 0,
        "description": "",
        "artifacts": [
            {
                "filename": "challenge.zip",
                "original_filename": "../download.zip",
                "source_url": "https://example.test/file",
            }
        ],
        "status": "in_progress",
        "flag": None,
        "source": "json_import",
        "remote_id": "44",
        "solver": {"file_type": "python", "relative_path": "solve.py"},
        "created_at": utc_timestamp(),
        "updated_at": utc_timestamp(),
        **overrides,
    }


def test_missing_files_initialize_valid_empty_documents(store):
    assert store.load_ctfs() == []
    ctf_id = generate_id()
    assert store.load_challenges(ctf_id) == []

    assert json.loads((store.data_dir / "ctfs.json").read_text()) == {
        "schema_version": 1,
        "ctfs": [],
    }
    assert json.loads(
        (
            store.data_dir / "ctfs" / ctf_id / "challenges" / "information.json"
        ).read_text()
    ) == {"schema_version": 1, "challenges": []}


def test_last_ctf_id_roundtrips_and_can_be_cleared(store):
    ctf_id = generate_id()

    assert store.load_last_ctf_id() is None
    store.save_last_ctf_id(ctf_id)
    assert store.load_last_ctf_id() == ctf_id
    store.save_last_ctf_id(None)
    assert store.load_last_ctf_id() is None


def test_last_ctf_id_rejects_invalid_ids(store):
    with pytest.raises(DataValidationError):
        store.save_last_ctf_id("../outside")

    store.data_dir.mkdir(parents=True)
    path = store.data_dir / "last_ctf.json"
    path.write_text(
        json.dumps({"schema_version": 1, "last_ctf_id": "../outside"}),
        encoding="utf-8",
    )
    with pytest.raises(DataValidationError):
        store.load_last_ctf_id()


def test_ctf_and_challenge_roundtrip_with_defaults(store):
    ctf = ctf_record()
    challenge = challenge_record()

    store.save_ctfs([ctf])
    store.save_challenges(ctf["id"], [challenge])

    loaded_ctf = store.load_ctfs()[0]
    loaded_challenge = store.load_challenges(ctf["id"])[0]
    assert loaded_ctf["name"] == "DEF CON quals"
    assert loaded_ctf["year"] == 2025
    assert loaded_challenge == challenge

    minimal = challenge_record(
        name="minimal",
        category=None,
        points=None,
        description="",
        artifacts=[],
        flag=None,
        source="manual",
        remote_id=None,
        solver=None,
    )
    store.save_challenges(ctf["id"], [minimal])
    assert store.load_challenges(ctf["id"])[0] == minimal


def test_legacy_challenge_hint_data_is_ignored_without_rewriting_file(store):
    ctf_id = generate_id()
    path = store.data_dir / "ctfs" / ctf_id / "challenges" / "information.json"
    path.parent.mkdir(parents=True)
    record = challenge_record()
    record["hints"] = ["old hint"]
    original = {"schema_version": 1, "challenges": [record]}
    path.write_text(json.dumps(original), encoding="utf-8")

    loaded = store.load_challenges(ctf_id)

    assert len(loaded) == 1
    assert "hints" not in loaded[0]
    assert json.loads(path.read_text(encoding="utf-8")) == original


@pytest.mark.parametrize(
    ("record_factory", "overrides", "message"),
    [
        (ctf_record, {"id": "../bad"}, "id"),
        (ctf_record, {"name": "  "}, "name"),
        (ctf_record, {"year": True}, "year"),
        (ctf_record, {"year": 1800}, "year"),
        (ctf_record, {"source": "remote"}, "source"),
        (ctf_record, {"created_at": "2025-01-01T01:00:00+01:00"}, "created_at"),
        (challenge_record, {"status": "complete"}, "status"),
        (challenge_record, {"source": "external"}, "source"),
        (challenge_record, {"points": True}, "points"),
        (
            challenge_record,
            {"artifacts": [{"filename": "../outside"}]},
            "filename",
        ),
        (
            challenge_record,
            {"solver": {"file_type": "python", "relative_path": "../solve.py"}},
            "relative_path",
        ),
    ],
)
def test_record_validation(store, record_factory, overrides, message):
    record = record_factory(**overrides)
    if record_factory is ctf_record:

        def operation():
            return store.save_ctfs([record])
    else:

        def operation():
            return store.save_challenges(generate_id(), [record])

    with pytest.raises(DataValidationError, match=message):
        operation()


def test_challenge_artifacts_directory_is_created_and_contained(store):
    ctf_id = generate_id()
    challenge = challenge_record()
    store.save_challenges(ctf_id, [challenge])

    artifacts_directory = store.challenge_artifacts_directory(ctf_id, challenge["id"])

    assert artifacts_directory.is_dir()
    assert artifacts_directory.is_relative_to(store.data_dir)


def test_challenge_artifacts_directory_rejects_symlinks(store, tmp_path):
    ctf_id = generate_id()
    challenge = challenge_record()
    store.save_challenges(ctf_id, [challenge])
    challenge_directory = store.challenge_directory(ctf_id, challenge["id"])
    artifacts_directory = challenge_directory / "artifacts"
    outside = tmp_path / "outside"
    outside.mkdir()
    artifacts_directory.symlink_to(outside, target_is_directory=True)

    with pytest.raises(DataFileError, match="symlinked artifacts directory"):
        store.challenge_artifacts_directory(ctf_id, challenge["id"])


def test_ctf_id_is_validated_before_path_use(store):
    for unsafe in ("../outside", "x" * 32, "a" * 31, "A" * 32):
        with pytest.raises(DataFileError, match="CTF ID"):
            store.load_challenges(unsafe)
    assert not (store.data_dir.parent / "outside").exists()


def test_ctfd_credentials_are_host_bound_and_private(store):
    ctf = ctf_record()
    store.save_ctfs([ctf])
    store.save_ctfd_token(
        ctf["id"], "https://ctfd.example/events/season/", "secret-token"
    )

    token_path = store.data_dir / "ctfs" / ctf["id"] / "token.json"
    document = json.loads(token_path.read_text(encoding="utf-8"))
    assert document == {
        "base_url": "https://ctfd.example/events/season",
        "token": "secret-token",
    }
    assert (
        store.load_ctfd_token(ctf["id"], "https://ctfd.example/events/season")
        == "secret-token"
    )
    assert (
        store.load_ctfd_token(ctf["id"], "https://ctfd.example/events/season/")
        == "secret-token"
    )
    assert store.load_ctfd_token(ctf["id"], "https://other.example") is None
    assert token_path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize(
    "base_url",
    [
        "http://ctfd.example",
        "https://user:password@ctfd.example",
        "https://ctfd.example?next=other",
        "https://ctfd.example/#fragment",
    ],
)
def test_ctfd_credentials_reject_unsafe_base_urls(store, base_url):
    ctf = ctf_record()
    store.save_ctfs([ctf])

    with pytest.raises(DataValidationError, match="HTTPS URL"):
        store.save_ctfd_token(ctf["id"], base_url, "secret-token")


def test_ctfd_credentials_reject_control_characters_in_token(store):
    ctf = ctf_record()
    store.save_ctfs([ctf])

    with pytest.raises(DataValidationError, match="control characters"):
        store.save_ctfd_token(
            ctf["id"], "https://ctfd.example", "token\r\nX-Injected: yes"
        )


def test_malformed_ctfd_credentials_are_reported_without_token_contents(store):
    ctf = ctf_record()
    store.save_ctfs([ctf])
    token_path = store.data_dir / "ctfs" / ctf["id"] / "token.json"
    token_path.parent.mkdir(parents=True)
    token_path.write_text(
        '{"base_url": "https://ctfd.example", "token": "secret"', encoding="utf-8"
    )

    with pytest.raises(DataFileError) as error:
        store.load_ctfd_token(ctf["id"], "https://ctfd.example")

    assert "secret" not in str(error.value)
    assert "line 1, column" in str(error.value)


def test_symlinked_ctf_directory_cannot_escape_data_dir(store, tmp_path):
    store.data_dir.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (store.data_dir / "ctfs").mkdir()
    (store.data_dir / "ctfs" / generate_id()).symlink_to(
        outside, target_is_directory=True
    )
    ctf_id = next(path.name for path in (store.data_dir / "ctfs").iterdir())

    with pytest.raises(DataFileError, match="escapes"):
        store.load_challenges(ctf_id)
    assert list(outside.iterdir()) == []


def test_malformed_json_reports_path_and_location_without_replacement(store):
    store.data_dir.mkdir(parents=True)
    path = store.data_dir / "ctfs.json"
    contents = '{"schema_version": 1,\n "ctfs": [}\n'
    path.write_text(contents, encoding="utf-8")

    with pytest.raises(DataFileError) as exc:
        store.load_ctfs()

    message = str(exc.value)
    assert str(path) in message
    assert "line 2, column" in message
    assert path.read_text(encoding="utf-8") == contents


def test_invalid_existing_json_is_not_replaced_by_save(store):
    store.data_dir.mkdir(parents=True)
    path = store.data_dir / "ctfs.json"
    contents = '{"schema_version": 99, "ctfs": []}'
    path.write_text(contents, encoding="utf-8")

    with pytest.raises(DataValidationError):
        store.save_ctfs([ctf_record()])

    assert path.read_text(encoding="utf-8") == contents
    assert list(store.data_dir.glob("*.bak")) == []


def test_verified_update_removes_backups_of_previous_valid_document(store):
    first = ctf_record()
    store.save_ctfs([first])
    path = store.data_dir / "ctfs.json"
    original = path.read_bytes()
    stale_backup = path.with_name("ctfs.json.previous.bak")
    stale_backup.write_bytes(original)
    updated = ctf_record(name="Updated")

    store.save_ctfs([updated])

    assert list(store.data_dir.glob("ctfs.json.*.bak")) == []
    assert store.load_ctfs()[0]["name"] == "Updated"


def test_versionless_ctf_migration_removes_backup_after_verification(store):
    path = store.data_dir / "ctfs.json"
    path.parent.mkdir(parents=True)
    original = json.dumps({"ctfs": [ctf_record()]}, indent=2).encode("utf-8")
    path.write_bytes(original)

    assert len(store.load_ctfs()) == 1

    migrated = json.loads(path.read_text(encoding="utf-8"))
    assert migrated["schema_version"] == 1
    assert list(store.data_dir.glob("ctfs.json.*.bak")) == []


def test_verified_challenge_update_removes_pre_update_backup(store):
    ctf_id = generate_id()
    store.save_challenges(ctf_id, [challenge_record()])
    path = store.data_dir / "ctfs" / ctf_id / "challenges" / "information.json"

    store.save_challenges(ctf_id, [challenge_record(name="Updated")])

    assert list(path.parent.glob("information.json.*.bak")) == []


def test_delete_ctf_removes_its_directory_without_index_backup(store):
    ctf = ctf_record()
    store.save_ctfs([ctf])
    store.load_challenges(ctf["id"])
    ctf_directory = store.data_dir / "ctfs" / ctf["id"]
    challenge_file = (
        ctf_directory / "challenges" / generate_id() / "artifacts" / "payload.bin"
    )
    challenge_file.parent.mkdir(parents=True)
    challenge_file.write_bytes(b"artifact")

    retained = store.delete_ctf(ctf["id"], [])

    assert retained is None
    assert store.load_ctfs() == []
    assert not ctf_directory.exists()
    assert list(store.data_dir.glob("ctfs.json.*.bak")) == []


def test_artifact_download_status_checks_managed_files_safely(store, tmp_path):
    ctf_id = generate_id()
    challenge = challenge_record()
    store.save_challenges(ctf_id, [challenge])

    assert (
        store.is_artifact_downloaded(ctf_id, challenge["id"], "challenge.zip") is False
    )

    artifact_path = (
        store.data_dir
        / "ctfs"
        / ctf_id
        / "challenges"
        / challenge["id"]
        / "artifacts"
        / "challenge.zip"
    )
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_bytes(b"artifact")
    assert (
        store.is_artifact_downloaded(ctf_id, challenge["id"], "challenge.zip") is True
    )

    assert store.is_artifact_downloaded(ctf_id, challenge["id"], "other.zip") is False
    with pytest.raises(DataValidationError, match="filename"):
        store.is_artifact_downloaded(ctf_id, challenge["id"], "../outside")

    artifact_path.unlink()
    outside_path = tmp_path / "outside.zip"
    outside_path.write_bytes(b"outside")
    artifact_path.symlink_to(outside_path)
    with pytest.raises(DataFileError, match="escapes the configured data directory"):
        store.is_artifact_downloaded(ctf_id, challenge["id"], "challenge.zip")
    with pytest.raises(DataFileError, match="escapes the configured data directory"):
        store.save_artifact(
            ctf_id,
            challenge["id"],
            "challenge.zip",
            [b"replacement"],
            overwrite=True,
        )


def test_save_artifact_rejects_symlinked_artifacts_directory(store, tmp_path):
    ctf_id = generate_id()
    challenge = challenge_record(source="ctfd")
    store.save_challenges(ctf_id, [challenge])
    challenge_directory = (
        store.data_dir / "ctfs" / ctf_id / "challenges" / challenge["id"]
    )
    challenge_directory.mkdir(parents=True)
    outside_directory = tmp_path / "outside-artifacts"
    outside_directory.mkdir()
    (challenge_directory / "artifacts").symlink_to(
        outside_directory, target_is_directory=True
    )

    with pytest.raises(DataFileError, match="symlinked artifacts directory"):
        store.save_artifact(
            ctf_id, challenge["id"], "challenge.zip", [b"must not be written"]
        )

    assert list(outside_directory.iterdir()) == []


def test_save_artifact_is_atomic_and_overwrites_only_when_confirmed(store):
    ctf_id = generate_id()
    challenge = challenge_record(source="ctfd")
    store.save_challenges(ctf_id, [challenge])

    artifact_path = store.save_artifact(
        ctf_id, challenge["id"], "challenge.zip", [b"artifact ", b"bytes"]
    )
    assert artifact_path.read_bytes() == b"artifact bytes"
    assert store.is_artifact_downloaded(ctf_id, challenge["id"], "challenge.zip")
    with pytest.raises(DataFileError, match="explicit overwrite confirmation"):
        store.save_artifact(
            ctf_id, challenge["id"], "challenge.zip", [b"not confirmed"]
        )

    def broken_download():
        yield b"partial replacement"
        raise RuntimeError("network interrupted")

    with pytest.raises(RuntimeError, match="network interrupted"):
        store.save_artifact(
            ctf_id,
            challenge["id"],
            "challenge.zip",
            broken_download(),
            overwrite=True,
        )
    assert artifact_path.read_bytes() == b"artifact bytes"
    assert list(artifact_path.parent.glob(".ctfwb-artifact-*.tmp")) == []

    store.save_artifact(
        ctf_id,
        challenge["id"],
        "challenge.zip",
        [b"replacement"],
        overwrite=True,
    )
    assert artifact_path.read_bytes() == b"replacement"
    assert len(list(artifact_path.parent.iterdir())) == 1


def test_delete_ctf_restores_directory_when_index_save_fails(store, monkeypatch):
    ctf = ctf_record()
    store.save_ctfs([ctf])
    store.load_challenges(ctf["id"])
    ctf_directory = store.data_dir / "ctfs" / ctf["id"]

    def fail_save(_records):
        raise DataFileError(store.data_dir / "ctfs.json", "simulated save failure")

    monkeypatch.setattr(store, "save_ctfs", fail_save)

    with pytest.raises(DataFileError, match="simulated save failure"):
        store.delete_ctf(ctf["id"], [])

    assert ctf_directory.is_dir()
    assert store.load_ctfs()[0]["id"] == ctf["id"]
    assert not list((store.data_dir / "ctfs").glob(f".{ctf['id']}.deleting-*"))


def test_delete_ctf_refuses_symlinked_directory(store, tmp_path):
    ctf = ctf_record()
    store.save_ctfs([ctf])
    ctf_root = store.data_dir / "ctfs"
    ctf_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (ctf_root / ctf["id"]).symlink_to(outside, target_is_directory=True)

    with pytest.raises(DataFileError, match="symlink"):
        store.delete_ctf(ctf["id"], [])

    assert outside.is_dir()
    assert store.load_ctfs()[0]["id"] == ctf["id"]


def test_delete_challenge_removes_only_selected_directory_without_collection_backup(
    store,
):
    ctf_id = generate_id()
    selected = challenge_record(name="Selected")
    sibling = challenge_record(name="Sibling")
    store.save_challenges(ctf_id, [selected, sibling])

    challenges_directory = store.data_dir / "ctfs" / ctf_id / "challenges"
    selected_directory = challenges_directory / selected["id"]
    sibling_directory = challenges_directory / sibling["id"]
    selected_artifact = selected_directory / "artifacts" / "selected.bin"
    sibling_artifact = sibling_directory / "artifacts" / "sibling.bin"
    selected_artifact.parent.mkdir(parents=True)
    sibling_artifact.parent.mkdir(parents=True)
    selected_artifact.write_bytes(b"selected challenge data")
    sibling_artifact.write_bytes(b"sibling challenge data")
    retained = store.delete_challenge(ctf_id, selected["id"], [sibling])

    assert retained is None
    assert not selected_directory.exists()
    assert sibling_artifact.read_bytes() == b"sibling challenge data"
    assert [record["id"] for record in store.load_challenges(ctf_id)] == [sibling["id"]]
    assert list(challenges_directory.glob("information.json.*.bak")) == []


def test_delete_challenge_restores_directory_and_records_when_collection_save_fails(
    store, monkeypatch
):
    ctf_id = generate_id()
    selected = challenge_record(name="Selected")
    sibling = challenge_record(name="Sibling")
    store.save_challenges(ctf_id, [selected, sibling])

    challenges_directory = store.data_dir / "ctfs" / ctf_id / "challenges"
    selected_directory = challenges_directory / selected["id"]
    payload = selected_directory / "artifacts" / "payload.bin"
    payload.parent.mkdir(parents=True)
    payload.write_bytes(b"keep me")
    collection_path = challenges_directory / "information.json"
    original_collection = collection_path.read_bytes()

    def fail_save(_ctf_id, _records):
        raise DataFileError(collection_path, "simulated collection save failure")

    monkeypatch.setattr(store, "save_challenges", fail_save)

    with pytest.raises(DataFileError, match="simulated collection save failure"):
        store.delete_challenge(ctf_id, selected["id"], [sibling])

    assert selected_directory.is_dir()
    assert payload.read_bytes() == b"keep me"
    assert collection_path.read_bytes() == original_collection
    assert [record["id"] for record in store.load_challenges(ctf_id)] == [
        selected["id"],
        sibling["id"],
    ]
    assert not list(challenges_directory.glob(f".{selected['id']}.deleting-*"))


def test_delete_challenge_refuses_symlinked_challenge_directory(store, tmp_path):
    ctf_id = generate_id()
    challenge = challenge_record()
    store.save_challenges(ctf_id, [challenge])

    challenges_directory = store.data_dir / "ctfs" / ctf_id / "challenges"
    outside = tmp_path / "outside"
    outside.mkdir()
    outside_file = outside / "keep.bin"
    outside_file.write_bytes(b"outside data")
    (challenges_directory / challenge["id"]).symlink_to(
        outside, target_is_directory=True
    )

    with pytest.raises(DataFileError, match="symlink"):
        store.delete_challenge(ctf_id, challenge["id"], [])

    assert outside_file.read_bytes() == b"outside data"
    assert store.load_challenges(ctf_id)[0]["id"] == challenge["id"]


def test_delete_challenge_refuses_non_directory_challenge_path(store):
    ctf_id = generate_id()
    challenge = challenge_record()
    store.save_challenges(ctf_id, [challenge])

    challenges_directory = store.data_dir / "ctfs" / ctf_id / "challenges"
    challenge_path = challenges_directory / challenge["id"]
    challenge_path.write_text("not a directory", encoding="utf-8")

    with pytest.raises(DataFileError, match="not a directory"):
        store.delete_challenge(ctf_id, challenge["id"], [])

    assert challenge_path.read_text(encoding="utf-8") == "not a directory"
    assert store.load_challenges(ctf_id)[0]["id"] == challenge["id"]


@pytest.mark.parametrize("challenge_id", ["../outside", "x" * 32, None])
def test_delete_challenge_rejects_unsafe_ids_before_path_use(store, challenge_id):
    ctf_id = generate_id()
    challenge = challenge_record()
    store.save_challenges(ctf_id, [challenge])

    with pytest.raises(DataFileError, match="challenge ID"):
        store.delete_challenge(ctf_id, challenge_id, [])

    assert store.load_challenges(ctf_id)[0]["id"] == challenge["id"]
    assert not (store.data_dir.parent / "outside").exists()


def test_delete_challenge_rejects_nonexistent_id(store):
    ctf_id = generate_id()
    challenge = challenge_record()
    store.save_challenges(ctf_id, [challenge])

    with pytest.raises(DataValidationError, match="does not exist"):
        store.delete_challenge(ctf_id, generate_id(), [])

    assert store.load_challenges(ctf_id)[0]["id"] == challenge["id"]


@pytest.mark.parametrize(
    ("remaining_kind", "message"),
    [
        ("deleted_challenge", "still contain the deleted challenge ID"),
        ("invalid_record", "id"),
        ("duplicate_id", "duplicate id"),
    ],
)
def test_delete_challenge_validates_remaining_records_before_staging(
    store, remaining_kind, message
):
    ctf_id = generate_id()
    selected = challenge_record(name="Selected")
    sibling = challenge_record(name="Sibling")
    store.save_challenges(ctf_id, [selected, sibling])

    challenges_directory = store.data_dir / "ctfs" / ctf_id / "challenges"
    selected_directory = challenges_directory / selected["id"]
    selected_directory.mkdir()
    (selected_directory / "keep.txt").write_text("keep me", encoding="utf-8")
    collection_path = challenges_directory / "information.json"
    original_collection = collection_path.read_bytes()
    if remaining_kind == "deleted_challenge":
        remaining = [selected, sibling]
    elif remaining_kind == "invalid_record":
        remaining = [challenge_record(id="../bad")]
    else:
        remaining = [sibling, sibling]

    with pytest.raises(DataValidationError, match=message):
        store.delete_challenge(ctf_id, selected["id"], remaining)

    assert (selected_directory / "keep.txt").read_text(encoding="utf-8") == "keep me"
    assert collection_path.read_bytes() == original_collection
    assert not list(challenges_directory.glob(f".{selected['id']}.deleting-*"))


def test_atomic_replace_failure_keeps_canonical_file_and_cleans_temp(
    store, monkeypatch
):
    store.save_ctfs([ctf_record()])
    path = store.data_dir / "ctfs.json"
    original = path.read_bytes()
    monkeypatch.setattr(
        "ctfwb.storage.data_store.os.replace",
        lambda *_args: (_ for _ in ()).throw(OSError("blocked")),
    )

    with pytest.raises(DataFileError, match="atomically"):
        store.save_ctfs([ctf_record(name="not saved")])

    assert path.read_bytes() == original
    backups = list(store.data_dir.glob("ctfs.json.*.bak"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == original
    assert list(store.data_dir.glob(".ctfs.json.*.tmp")) == []


def test_verification_failure_retains_backup(store, monkeypatch):
    store.save_ctfs([ctf_record()])
    path = store.data_dir / "ctfs.json"
    original = path.read_bytes()

    def fail_verification(file_path, _expected):
        raise DataFileError(file_path, "simulated verification failure")

    monkeypatch.setattr(
        DataStore, "_verify_written_document", staticmethod(fail_verification)
    )

    with pytest.raises(DataFileError, match="simulated verification failure"):
        store.save_ctfs([ctf_record(name="not verified")])

    backups = list(store.data_dir.glob("ctfs.json.*.bak"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == original


def test_lock_context_contention_and_release(store):
    first = store.lock()
    second = DataDirectoryLock(store.data_dir)

    with first:
        assert first.acquired
        with pytest.raises(LockError, match="another application"):
            second.acquire()
    assert not first.acquired
    assert not (store.data_dir / ".ctf-workbench.lock").exists()


def test_stale_same_host_pid_lock_is_recovered(store, monkeypatch):
    store.data_dir.mkdir(parents=True)
    lock_path = store.data_dir / ".ctf-workbench.lock"
    lock_path.write_text(
        json.dumps({"host": socket.gethostname(), "pid": 918273645, "token": "stale"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "ctfwb.storage.data_store.os.kill",
        lambda _pid, _signal: (_ for _ in ()).throw(ProcessLookupError()),
    )
    lock = store.lock()

    with lock:
        owner = json.loads(lock_path.read_text(encoding="utf-8"))
        assert owner["token"] != "stale"
        assert owner["pid"] == os.getpid()

    assert not lock_path.exists()


def test_lock_does_not_recover_other_host_or_malformed_owner(store):
    store.data_dir.mkdir(parents=True)
    lock_path = store.data_dir / ".ctf-workbench.lock"
    lock_path.write_text(
        json.dumps({"host": "another-host", "pid": 918273645, "token": "remote"}),
        encoding="utf-8",
    )

    with pytest.raises(LockError):
        store.lock().acquire()
    assert json.loads(lock_path.read_text(encoding="utf-8"))["token"] == "remote"


def test_symlinked_lock_is_not_followed_or_recovered(store, tmp_path):
    store.data_dir.mkdir(parents=True)
    external_lock = tmp_path / "external-lock"
    contents = json.dumps(
        {
            "host": socket.gethostname(),
            "pid": 918273645,
            "token": "external",
        }
    )
    external_lock.write_text(contents, encoding="utf-8")
    (store.data_dir / ".ctf-workbench.lock").symlink_to(external_lock)

    with pytest.raises(LockError):
        store.lock().acquire()

    assert external_lock.read_text(encoding="utf-8") == contents
