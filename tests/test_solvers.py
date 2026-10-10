import sys
import threading
import time

import pytest

from ctfwb.config import AppConfig
from ctfwb.solvers import (
    EditorError,
    SolverOutcome,
    SolverService,
    list_templates,
)
from ctfwb.storage import DataFileError, DataStore, DataValidationError, utc_timestamp

CTF_ID = "a" * 32
CHALLENGE_ID = "b" * 32


@pytest.fixture
def workflow(tmp_path):
    config_file = tmp_path / "settings" / "config.toml"
    config_file.parent.mkdir()
    config_file.write_text(
        "[solver]\n"
        f'python_interpreter = "{sys.executable}"\n'
        "timeout_seconds = 2\n"
        "bash_execution_enabled = false\n",
        encoding="utf-8",
    )
    config = AppConfig.load(config_file)
    store = DataStore(tmp_path / "data with spaces")
    now = utc_timestamp()
    store.save_challenges(
        CTF_ID,
        [
            {
                "id": CHALLENGE_ID,
                "name": "Challenge",
                "status": "unsolved",
                "source": "manual",
                "created_at": now,
                "updated_at": now,
            }
        ],
    )
    warnings_seen = []
    service = SolverService(store, config, warning_callback=warnings_seen.append)
    return store, config, service, warnings_seen


def test_registry_contains_python_variants_and_separate_bash_template():
    templates = {template.template_id: template for template in list_templates()}

    assert {"python-artifacts", "python", "bash"} <= templates.keys()
    assert templates["python-artifacts"].file_type == "python"
    assert "sys.argv" in templates["python-artifacts"].contents
    assert templates["python"].file_type == "python"
    assert templates["bash"].file_type == "bash"
    assert "template only" in templates["bash"].display_name.lower()


def test_create_solver_and_run_with_spaced_paths_separate_streams_and_flags(
    workflow, tmp_path
):
    store, _, service, warnings_seen = workflow
    solver_path = service.create_solver(
        CTF_ID,
        CHALLENGE_ID,
        "python-artifacts",
        relative_path="nested dir/solve $'quote'.py",
    )
    solver_path.write_text(
        "import sys\n"
        "from pathlib import Path\n"
        "print('OUT:' + sys.argv[1])\n"
        "print('FLAG{not registered}', file=sys.stderr)\n"
        "print(Path.cwd().name)\n",
        encoding="utf-8",
    )
    artifact = tmp_path / "artifact with spaces; $'quote'.bin"
    artifact.write_bytes(b"artifact")

    result = service.run_solver(
        CTF_ID, CHALLENGE_ID, [artifact, "another artifact.bin"]
    )

    assert result.outcome is SolverOutcome.COMPLETED
    assert result.returncode == 0
    assert f"OUT:{artifact}" in result.stdout
    assert solver_path.parent.name in result.stdout
    assert "FLAG{not registered}" in result.stderr
    assert len(warnings_seen) == 2
    assert "not sandboxed" in warnings_seen[0]
    assert "sensitive data" in warnings_seen[1]
    challenge = store.load_challenges(CTF_ID)[0]
    assert challenge["flag"] is None
    assert challenge["solver"] == {
        "file_type": "python",
        "relative_path": "nested dir/solve $'quote'.py",
    }


def test_nonzero_exit_code_is_returned(workflow):
    _, _, service, _ = workflow
    script = service.create_solver(CTF_ID, CHALLENGE_ID, "python")
    script.write_text("import sys\nprint('failed')\nsys.exit(7)\n", encoding="utf-8")

    result = service.run_solver(CTF_ID, CHALLENGE_ID)

    assert result.outcome is SolverOutcome.COMPLETED
    assert result.returncode == 7
    assert result.stdout == "failed\n"


def test_timeout_is_a_distinct_outcome(workflow):
    _, _, service, _ = workflow
    script = service.create_solver(CTF_ID, CHALLENGE_ID, "python")
    script.write_text("import time\ntime.sleep(10)\n", encoding="utf-8")

    result = service.run_solver(CTF_ID, CHALLENGE_ID, timeout_seconds=0.1)

    assert result.outcome is SolverOutcome.TIMED_OUT
    assert result.returncode is not None


def test_cancellation_terminates_running_process(workflow, tmp_path):
    _, _, service, _ = workflow
    script = service.create_solver(CTF_ID, CHALLENGE_ID, "python")
    started = tmp_path / "process started"
    script.write_text(
        f"import time\nopen({str(started)!r}, 'w').close()\ntime.sleep(10)\n",
        encoding="utf-8",
    )
    cancel = threading.Event()
    results = []
    thread = threading.Thread(
        target=lambda: results.append(
            service.run_solver(
                CTF_ID, CHALLENGE_ID, timeout_seconds=5, cancel_event=cancel
            )
        )
    )
    thread.start()
    deadline = time.monotonic() + 2
    while not started.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert started.exists()
    cancel.set()
    thread.join(timeout=3)

    assert not thread.is_alive()
    assert results[0].outcome is SolverOutcome.CANCELLED


@pytest.mark.parametrize("path", ["../outside.py", "/tmp/outside.py", "a/../b.py"])
def test_solver_paths_reject_traversal_and_absolute_paths(workflow, path):
    store, _, _, _ = workflow

    with pytest.raises(DataValidationError):
        store.resolve_challenge_file(CTF_ID, CHALLENGE_ID, path)


def test_solver_path_rejects_symlink_escape(workflow, tmp_path):
    store, _, service, _ = workflow
    solver_path = service.create_solver(CTF_ID, CHALLENGE_ID, "python")
    outside = tmp_path / "outside.py"
    outside.write_text("print('unsafe')", encoding="utf-8")
    solver_path.unlink()
    solver_path.symlink_to(outside)

    with pytest.raises(DataFileError, match="symlink"):
        store.resolve_challenge_file(CTF_ID, CHALLENGE_ID, "solve.py", must_exist=True)


def test_solver_path_rejects_symlinked_challenge_directory(workflow, tmp_path):
    store, _, _, _ = workflow
    store.challenge_directory(CTF_ID, CHALLENGE_ID)
    challenge_path = store.data_dir / "ctfs" / CTF_ID / "challenges" / CHALLENGE_ID
    challenge_path.rmdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    challenge_path.symlink_to(outside, target_is_directory=True)

    with pytest.raises(DataFileError, match="symlink"):
        store.resolve_challenge_file(CTF_ID, CHALLENGE_ID, "solve.py")


def test_overwrite_requires_confirmation_and_preserves_existing_bytes(workflow):
    store, _, service, _ = workflow
    path = service.create_solver(CTF_ID, CHALLENGE_ID, "python")
    original = path.read_text(encoding="utf-8")

    with pytest.raises(DataFileError, match="confirmation"):
        store.create_solver_file(CTF_ID, CHALLENGE_ID, "solve.py", "python", "changed")
    assert path.read_text(encoding="utf-8") == original

    store.create_solver_file(
        CTF_ID,
        CHALLENGE_ID,
        "solve.py",
        "python",
        "confirmed replacement",
        overwrite_confirmed=True,
    )
    assert path.read_text(encoding="utf-8") == "confirmed replacement"


def test_editor_uses_argument_list_and_reports_launch_and_exit_errors(
    workflow, monkeypatch
):
    _, config, service, _ = workflow
    script = service.create_solver(CTF_ID, CHALLENGE_ID, "python")
    import ctfwb.solvers.service as service_module

    observed = []

    def editor(executable, arguments, path):
        observed.append((executable, arguments, path))
        return 0

    monkeypatch.setattr(service_module, "run_editor", editor)
    assert service.edit_solver(CTF_ID, CHALLENGE_ID) == 0
    assert observed == [(config.editor, config.editor_args, script)]

    monkeypatch.setattr(
        service_module,
        "run_editor",
        lambda *args: (_ for _ in ()).throw(FileNotFoundError("missing")),
    )
    with pytest.raises(EditorError, match="cannot launch"):
        service.edit_solver(CTF_ID, CHALLENGE_ID)

    monkeypatch.setattr(
        service_module,
        "run_editor",
        lambda *args: (_ for _ in ()).throw(ValueError("invalid argument")),
    )
    with pytest.raises(EditorError, match="cannot launch"):
        service.edit_solver(CTF_ID, CHALLENGE_ID)

    monkeypatch.setattr(service_module, "run_editor", lambda *args: 3)
    with pytest.raises(EditorError, match="status 3"):
        service.edit_solver(CTF_ID, CHALLENGE_ID)


def test_bash_template_can_be_created_but_execution_requires_configuration(
    workflow,
):
    _, config, service, warnings_seen = workflow
    script = service.create_solver(CTF_ID, CHALLENGE_ID, "bash")
    assert script.name == "solve.sh"
    assert script.exists()
    result = service.run_solver(CTF_ID, CHALLENGE_ID)
    assert result.outcome is SolverOutcome.LAUNCH_ERROR
    assert "disabled" in result.error
    assert warnings_seen == []

    enabled = SolverService(
        service.data_store,
        AppConfig(
            data_dir=config.data_dir,
            config_path=config.config_path,
            python_interpreter=config.python_interpreter,
            solver_timeout_seconds=config.solver_timeout_seconds,
            bash_execution_enabled=True,
        ),
        warning_callback=warnings_seen.append,
    )
    result = enabled.run_solver(CTF_ID, CHALLENGE_ID, ["artifact with spaces.bin"])
    assert result.outcome is SolverOutcome.COMPLETED
    assert "1 artifact argument(s)" in result.stdout
    assert len(warnings_seen) == 2


def test_default_warning_hook_warns_before_execution(workflow):
    store, config, _, _ = workflow
    service = SolverService(store, config)
    service.create_solver(CTF_ID, CHALLENGE_ID, "python")
    with pytest.warns(UserWarning) as recorded:
        result = service.run_solver(CTF_ID, CHALLENGE_ID)

    assert result.outcome is SolverOutcome.COMPLETED
    assert "not sandboxed" in str(recorded[0].message)
    assert "sensitive data" in str(recorded[1].message)
