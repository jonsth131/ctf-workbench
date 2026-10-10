"""Safe solver-file workflows and bounded subprocess execution."""

from __future__ import annotations

import shutil
import subprocess
import sys
import threading
import time
import warnings
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from ctfwb.config import AppConfig
from ctfwb.editor import run_editor
from ctfwb.solvers.templates import SolverTemplate, get_template, list_templates
from ctfwb.storage import DataStore, DataStoreError

UNSANDBOXED_WARNING = (
    "Solver execution is not sandboxed: it runs code with your permissions and "
    "may access your files or network."
)
SENSITIVE_OUTPUT_WARNING = (
    "Solver output may contain flags or other sensitive data. Review it before "
    "sharing; output is never parsed or registered as a flag."
)
WarningCallback = Callable[[str], None]


class SolverError(Exception):
    """A solver file or workflow could not be handled."""


class EditorError(SolverError):
    """The configured editor was unavailable or failed."""


class SolverOutcome(str, Enum):
    COMPLETED = "completed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"
    LAUNCH_ERROR = "launch_error"


@dataclass(frozen=True)
class SolverResult:
    """Separate process output and the reason a solver stopped."""

    outcome: SolverOutcome
    returncode: int | None
    stdout: str
    stderr: str
    error: str | None = None


class SolverService:
    """Service API for creating, editing, and running challenge solvers."""

    def __init__(
        self,
        data_store: DataStore,
        config: AppConfig,
        *,
        warning_callback: WarningCallback | None = None,
    ) -> None:
        self.data_store = data_store
        self.config = config
        self.warning_callback = warning_callback

    @staticmethod
    def templates() -> tuple[SolverTemplate, ...]:
        """Expose the immutable template registry."""
        return list_templates()

    def create_solver(
        self,
        ctf_id: str,
        challenge_id: str,
        template_id: str,
        *,
        relative_path: str | None = None,
        overwrite_confirmed: bool = False,
    ) -> Path:
        """Create a solver template and persist its validated relative path."""
        try:
            template = get_template(template_id)
        except KeyError as error:
            raise SolverError(str(error)) from error
        return self.data_store.create_solver_file(
            ctf_id,
            challenge_id,
            relative_path if relative_path is not None else template.filename,
            template.file_type,
            template.contents,
            overwrite_confirmed=overwrite_confirmed,
        )

    def _solver(self, ctf_id: str, challenge_id: str) -> tuple[dict[str, object], Path]:
        challenge = next(
            (
                record
                for record in self.data_store.load_challenges(ctf_id)
                if record["id"] == challenge_id
            ),
            None,
        )
        if challenge is None:
            raise SolverError("challenge does not exist")
        solver = challenge.get("solver")
        if not isinstance(solver, dict):
            raise SolverError("challenge has no solver configured")
        relative_path = solver.get("relative_path")
        if not isinstance(relative_path, str):
            raise SolverError("solver metadata has an invalid relative path")
        path = self.data_store.resolve_challenge_file(
            ctf_id, challenge_id, relative_path, must_exist=True
        )
        return solver, path

    def edit_solver(self, ctf_id: str, challenge_id: str) -> int:
        """Open a validated solver with the configured editor; never use a shell."""
        try:
            _, path = self._solver(ctf_id, challenge_id)
            returncode = run_editor(self.config.editor, self.config.editor_args, path)
        except (OSError, ValueError, DataStoreError) as error:
            raise EditorError(f"cannot launch configured editor: {error}") from error
        if returncode != 0:
            raise EditorError(f"configured editor exited with status {returncode}")
        return returncode

    @staticmethod
    def _validate_timeout(timeout: float) -> float:
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
            raise ValueError("timeout must be a positive finite number")
        value = float(timeout)
        if not 0 < value < float("inf"):
            raise ValueError("timeout must be a positive finite number")
        return value

    @staticmethod
    def _stop_process(process: subprocess.Popen[str]) -> tuple[str, str]:
        if process.poll() is None:
            try:
                process.terminate()
            except ProcessLookupError:
                pass
        try:
            stdout, stderr = process.communicate(timeout=1.0)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
        return stdout or "", stderr or ""

    def run_solver(
        self,
        ctf_id: str,
        challenge_id: str,
        artifact_paths: Sequence[str | Path] = (),
        *,
        timeout_seconds: float | None = None,
        cancel_event: threading.Event | None = None,
    ) -> SolverResult:
        """Run a configured solver and return separate, uncategorized streams.

        Each valid launch emits both safety warnings before spawning. A TUI or
        other caller can display these through ``warning_callback`` and decide
        how to present stdout/stderr; this service never inspects output for flags.
        """
        try:
            solver, path = self._solver(ctf_id, challenge_id)
            file_type = solver.get("file_type")
            if file_type == "bash":
                if not self.config.bash_execution_enabled:
                    raise SolverError(
                        "Bash execution is disabled; enable solver.bash_execution_enabled explicitly"
                    )
                executable = shutil.which("bash")
                if executable is None:
                    raise SolverError(
                        "Bash execution is enabled but Bash is unavailable"
                    )
            elif file_type == "python":
                executable = self.config.python_interpreter or sys.executable
            else:
                raise SolverError("solver metadata has an unsupported file type")

            timeout = self._validate_timeout(
                timeout_seconds
                if timeout_seconds is not None
                else self.config.solver_timeout_seconds
            )
        except (SolverError, DataStoreError, ValueError) as error:
            return SolverResult(SolverOutcome.LAUNCH_ERROR, None, "", "", str(error))

        warn = self.warning_callback or (
            lambda message: warnings.warn(message, UserWarning, stacklevel=2)
        )
        warn(UNSANDBOXED_WARNING)
        warn(SENSITIVE_OUTPUT_WARNING)
        arguments = [executable, str(path), *(str(item) for item in artifact_paths)]
        try:
            process = subprocess.Popen(
                arguments,
                cwd=path.parent,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except (OSError, ValueError) as error:
            return SolverResult(
                SolverOutcome.LAUNCH_ERROR,
                None,
                "",
                "",
                f"cannot launch solver: {error}",
            )

        deadline = time.monotonic() + timeout
        while True:
            if process.poll() is not None:
                stdout, stderr = process.communicate()
                return SolverResult(
                    SolverOutcome.COMPLETED, process.returncode, stdout, stderr
                )
            if cancel_event is not None and cancel_event.is_set():
                stdout, stderr = self._stop_process(process)
                return SolverResult(
                    SolverOutcome.CANCELLED, process.returncode, stdout, stderr
                )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                stdout, stderr = self._stop_process(process)
                return SolverResult(
                    SolverOutcome.TIMED_OUT, process.returncode, stdout, stderr
                )
            try:
                stdout, stderr = process.communicate(timeout=min(0.05, remaining))
                return SolverResult(
                    SolverOutcome.COMPLETED, process.returncode, stdout, stderr
                )
            except subprocess.TimeoutExpired:
                continue
