"""The CTF challenge list, details, and persistent activity log screen."""

from __future__ import annotations

import asyncio
import threading
from dataclasses import replace
from math import ceil
from pathlib import Path
from typing import Mapping, Sequence

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.screen import Screen
from textual.widgets import (
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    Static,
)

from ctfwb.importers import (
    CTFdError,
    ImportErrorBase,
    ImportPlan,
    RefreshPlan,
    create_import_plan,
    create_refresh_plan,
    download_ctfd_artifact,
    fetch_ctfd_challenges,
    submit_ctfd_flag,
)
from ctfwb.solvers import (
    EditorError,
    SolverError,
    SolverOutcome,
    get_template,
)
from ctfwb.storage import (
    DataStore,
    DataStoreError,
    utc_timestamp,
)
from ctfwb.ui.artifact_directory import (
    open_directory_in_file_explorer,
    open_directory_in_terminal,
)
from ctfwb.ui.dialogs import (
    AddChallengeDialog,
    ArtifactDownloadDialog,
    ConfirmDeleteChallengeDialog,
    ConfirmOverwriteSolverDialog,
    CTFdImportDialog,
    CTFdImportResult,
    CTFdRefreshPreviewDialog,
    EditChallengeDialog,
    EditFlagDialog,
    ExportArchiveDialog,
    ImportJSONDialog,
    ImportPreviewDialog,
    ImportSourceDialog,
    OpenArtifactsDirectoryDialog,
    RefreshSourceDialog,
    SelectChallengeStatusDialog,
    SelectSolverTemplateDialog,
    SolverOutputDialog,
)
from ctfwb.ui.models import (
    CTF,
    Challenge,
    _challenge_from_record,
    _challenge_record,
    _ctf_record,
)


class ResponsiveChallengeFooter(Footer):
    """Wrap challenge commands onto extra rows when the terminal is narrow."""

    def compose(self) -> ComposeResult:
        yield from super().compose()
        self._update_command_layout()

    def on_resize(self, _event: object) -> None:
        self._update_command_layout()

    def _update_command_layout(self) -> None:
        if not self.is_attached:
            return
        actions: dict[str, Binding] = {}
        active_bindings = self.screen.active_bindings
        for _node, binding, _enabled, _tooltip in active_bindings.values():
            if binding.show:
                actions.setdefault(binding.action, binding)
        command_widths = [
            len(str(self.app.get_key_display(binding))) + len(binding.description) + 2
            for binding in actions.values()
        ]
        command_palette = active_bindings.get(self.app.COMMAND_PALETTE_BINDING)
        if (
            self.show_command_palette
            and self.app.ENABLE_COMMAND_PALETTE
            and command_palette is not None
        ):
            binding = command_palette.binding
            command_widths.append(
                len(str(self.app.get_key_display(binding)))
                + len(binding.description)
                + 2
            )
        if not command_widths:
            self.styles.height = 1
            self.styles.grid_size_columns = 1
            return

        available_width = self.size.width or self.app.size.width
        row_count = min(3, len(command_widths))
        column_count = ceil(len(command_widths) / row_count)
        for candidate_rows in range(1, row_count + 1):
            candidate_columns = ceil(len(command_widths) / candidate_rows)
            column_widths = [0] * candidate_columns
            for index, width in enumerate(command_widths):
                column = index % candidate_columns
                column_widths[column] = max(column_widths[column], width)
            required_width = sum(column_widths)
            if required_width <= available_width:
                row_count = candidate_rows
                column_count = candidate_columns
                break

        self.styles.height = row_count
        self.styles.grid_size_columns = column_count


class CTFChallengeScreen(Screen[None]):
    """Challenge list and details for one in-memory CTF."""

    BINDINGS = [
        Binding("escape", "back", "CTFs", priority=True),
        Binding("a", "add_challenge", "Add"),
        Binding("m", "import_challenges", "Import"),
        Binding("x", "download_artifacts", "Download"),
        Binding("o", "open_artifacts_directory", "Folder"),
        Binding("r", "refresh_ctfd_challenges", "Refresh"),
        Binding("e", "edit_challenge", "Edit"),
        Binding("d", "delete_challenge", "Delete"),
        Binding("t", "set_challenge_status", "Status"),
        Binding("f", "edit_flag", "Flag"),
        Binding("n", "note", "Note"),
        Binding("s", "create_solver", "Solver"),
        Binding("v", "edit_solver", "Edit Solver"),
        Binding("g", "run_solver", "Run"),
        Binding("c", "cancel_solver", "Cancel Solver"),
        Binding("b", "export_backup", "Backup"),
        Binding("/", "filter_challenges", "Filter"),
        Binding("tab", "toggle_panel", "Switch"),
        Binding("h", "focus_challenge_list", show=False),
        Binding("l", "focus_challenge_details", show=False),
        Binding("ctrl+d", "challenge_page_down", "Page Down", show=False),
        Binding("ctrl+u", "challenge_page_up", "Page Up", show=False),
        Binding("up", "challenge_up", "Prev"),
        Binding("down", "challenge_down", "Next"),
        Binding("j", "challenge_down", "Next"),
        Binding("k", "challenge_up", "Prev"),
    ]

    STATUS_LABELS = {
        "unsolved": "UNSOLVED",
        "in_progress": "IN PROG",
        "solved": "SOLVED",
        "skipped": "SKIPPED",
    }
    STATUS_COLORS = {
        "unsolved": "#9cb8b2",
        "in_progress": "#e7c66a",
        "solved": "#71d6bc",
        "skipped": "#82919a",
    }
    DESCRIPTION_COLOR = "#7dcfff"
    NOTE_COLOR = "#e7c66a"
    CHALLENGE_NAME_COLOR = "#71d6bc"
    DETAIL_LABEL_COLOR = "#d7e4df"

    CSS = """
    CTFChallengeScreen {
        background: #07131c;
        color: #d7e4df;
    }

    #challenge-command-bar {
        layout: grid;
        grid-columns: auto;
        grid-gutter: 0 1;
        height: 1;
        scrollbar-size: 0 0;
    }

    #challenge-command-bar FooterKey {
        margin-right: 0;
    }

    #challenge-command-bar FooterKey.-command-palette {
        dock: none;
        border-left: none;
    }

    #challenge-workspace {
        height: 1fr;
        padding: 1 2;
    }

    #challenge-panel {
        width: 1fr;
        min-width: 24;
        border: round #397a78;
        padding: 0 1;
    }

    #challenge-panel:focus-within {
        border: round #56a9a3;
    }

    #challenge-detail-panel {
        width: 2fr;
        min-width: 30;
        border: round #397a78;
        padding: 0 2;
        margin-left: 1;
    }

    #challenge-detail-panel:focus-within {
        border: round #56a9a3;
    }

    #selected-ctf-name {
        height: 1;
        color: #71d6bc;
        text-style: bold;
        margin: 1 2 0 2;
    }

    .challenge-panel-title {
        height: 1;
        color: #71d6bc;
        text-style: bold;
        margin-bottom: 1;
    }

    #challenge-list, #challenge-details {
        height: 1fr;
        color: #9cb8b2;
    }

    #challenge-filter-row {
        height: 1;
        display: none;
    }

    #challenge-filter-label {
        color: #e7c66a;
        width: auto;
        height: 1;
    }

    #challenge-filter-query {
        width: 1fr;
        height: 1;
        border: none;
        background: transparent;
        padding: 0 1;
    }

    #challenge-details {
        scrollbar-gutter: auto;
    }

    #challenge-details-content {
        width: 1fr;
    }

    #challenge-list {
        border: none;
        background: transparent;
        scrollbar-gutter: stable;
    }

    #challenge-list > ListItem {
        height: 1;
        padding: 0 1;
        color: #d7e4df;
    }

    .challenge-list-row {
        width: 1fr;
        height: 1;
    }

    .challenge-name {
        width: 1fr;
        height: 1;
        overflow: hidden;
    }

    .challenge-status-indicator {
        width: 9;
        height: 1;
        color: #71d6bc;
        text-style: bold;
        text-align: right;
    }

    #challenge-list > ListItem.--highlight {
        background: #176b66;
        color: #ffffff;
        text-style: bold;
    }

    #challenge-list.challenge-empty {
        content-align: center middle;
        color: #9cb8b2;
    }

    #challenge-log-panel {
        height: 7;
        border-top: solid #397a78;
        padding: 0 2;
        color: #9cb8b2;
    }

    #log-message {
        height: 5;
        overflow-y: auto;
    }

    #challenge-log-title {
        color: #71d6bc;
        text-style: bold;
    }
    """

    def __init__(
        self,
        ctf: CTF,
        log_message: str,
        challenges: list[Challenge],
    ) -> None:
        super().__init__()
        self.ctf = ctf
        self._log_message = log_message
        self.challenges = challenges
        self._filter_query = ""
        self._filter_active = False
        self._solver_cancel_event: threading.Event | None = None
        self._artifact_download_active = False

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(
            f"CTF // {self.ctf.name}",
            id="selected-ctf-name",
            markup=False,
        )
        with Horizontal(id="challenge-workspace"):
            with Vertical(id="challenge-panel"):
                yield Label("CHALLENGES", classes="challenge-panel-title")
                with Horizontal(id="challenge-filter-row"):
                    yield Static("FILTER:", id="challenge-filter-label", markup=False)
                    yield Input(disabled=True, id="challenge-filter-query")
                if self.challenges:
                    yield self.make_challenge_list()
                else:
                    yield Static(
                        "No challenges yet.\n\nPress A to add a challenge.",
                        id="challenge-list",
                        classes="challenge-empty",
                        markup=False,
                    )
            with Vertical(id="challenge-detail-panel"):
                yield Label("CHALLENGE DETAILS", classes="challenge-panel-title")
                with VerticalScroll(id="challenge-details"):
                    yield Static(
                        "No challenge selected.",
                        id="challenge-details-content",
                        markup=False,
                    )
        with Vertical(id="challenge-log-panel"):
            yield Label("LOG", id="challenge-log-title")
            yield Static(self._log_message, id="log-message", markup=False)
        yield ResponsiveChallengeFooter(
            id="challenge-command-bar",
            compact=True,
        )

    def on_mount(self) -> None:
        self.refresh_bindings()
        if self.challenges:
            self.query_one("#challenge-list", ListView).focus()
            self.render_challenge_details(0)

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action in {"create_solver", "edit_solver", "run_solver"}:
            if (
                not self.challenges
                or self.app._data_store is None
                or self.ctf.id is None
            ):
                return False
            try:
                selected = self.query_one("#challenge-list", ListView).index
            except NoMatches:
                return False
            if selected is None:
                return False
            challenge_index = self._challenge_index_at(selected)
            if challenge_index is None:
                return False
            challenge = self.challenges[challenge_index]
            if challenge.id is None:
                return False
            if action == "edit_solver":
                return challenge.solver is not None
            if action == "run_solver":
                return (
                    challenge.solver is not None
                    and self._solver_cancel_event is None
                    and self.app._solver_service is not None
                )
            return (
                self.app._solver_service is not None
                and self._solver_cancel_event is None
            )
        if action == "cancel_solver":
            return self._solver_cancel_event is not None
        if action == "download_artifacts":
            if self._artifact_download_active or not self.challenges:
                return False
            try:
                challenge_list = self.query_one("#challenge-list", ListView)
            except NoMatches:
                return False
            index = challenge_list.index
            challenge_index = (
                self._challenge_index_at(index) if index is not None else None
            )
            return (
                challenge_index is not None
                and self.challenges[challenge_index].source == "ctfd"
                and self.challenges[challenge_index].remote_id is not None
            )
        if action == "open_artifacts_directory":
            if (
                not self.challenges
                or self.app._data_store is None
                or self.ctf.id is None
            ):
                return False
            try:
                challenge_list = self.query_one("#challenge-list", ListView)
            except NoMatches:
                return False
            index = challenge_list.index
            challenge_index = (
                self._challenge_index_at(index) if index is not None else None
            )
            return (
                challenge_index is not None
                and self.challenges[challenge_index].id is not None
            )
        if action == "refresh_ctfd_challenges":
            return any(
                challenge.source in {"ctfd", "json_import"}
                and challenge.remote_id is not None
                for challenge in self.challenges
            )
        return super().check_action(action, parameters)

    def action_export_backup(self) -> None:
        """Open the same global export flow used from the CTF browser."""
        self.app.push_screen(ExportArchiveDialog(), self.app.export_archive)

    def action_create_solver(self) -> None:
        index = self._selected_challenge_index("create a solver for")
        if index is None:
            return
        challenge = self.challenges[index]
        if self.app._data_store is None or self.ctf.id is None or challenge.id is None:
            self.app.log_error("Cannot create solver without managed storage IDs.")
            return
        self.app.push_screen(
            SelectSolverTemplateDialog(),
            lambda template_id: self._solver_template_selected(index, template_id),
        )

    def _solver_template_selected(self, index: int, template_id: str | None) -> None:
        if template_id is None:
            return
        challenge = self.challenges[index]
        data_store = self.app._data_store
        if data_store is None or self.ctf.id is None or challenge.id is None:
            self.app.log_error("Cannot create solver without managed storage IDs.")
            return
        try:
            template = get_template(template_id)
            solver = challenge.solver
            relative_path = (
                solver.get("relative_path") if solver is not None else template.filename
            )
            if not isinstance(relative_path, str):
                raise SolverError("saved solver path is invalid")
            target = data_store.resolve_challenge_file(
                self.ctf.id, challenge.id, relative_path
            )
        except (KeyError, SolverError, DataStoreError) as error:
            self._log_solver_error(challenge.name, "prepare solver", error)
            return
        if target.exists():
            self.app.push_screen(
                ConfirmOverwriteSolverDialog(challenge.name, relative_path),
                lambda confirmed: self._create_solver(
                    index,
                    template_id,
                    relative_path,
                    True if confirmed else None,
                ),
            )
        else:
            self._create_solver(index, template_id, relative_path, False)

    def _create_solver(
        self,
        index: int,
        template_id: str,
        relative_path: str,
        overwrite_confirmed: bool | None,
    ) -> None:
        if overwrite_confirmed is None:
            self.app.log_message("Solver replacement cancelled; existing file kept.")
            return
        challenge = self.challenges[index]
        data_store = self.app._data_store
        service = self.app._solver_service
        if (
            data_store is None
            or service is None
            or self.ctf.id is None
            or challenge.id is None
        ):
            self.app.log_error("Cannot create solver without managed storage IDs.")
            return
        try:
            service.create_solver(
                self.ctf.id,
                challenge.id,
                template_id,
                relative_path=relative_path,
                overwrite_confirmed=overwrite_confirmed,
            )
            refreshed = next(
                record
                for record in data_store.load_challenges(self.ctf.id)
                if record["id"] == challenge.id
            )
            self.challenges[index] = _challenge_from_record(refreshed)
        except (
            StopIteration,
            SolverError,
            DataStoreError,
            OSError,
            ValueError,
        ) as error:
            self._log_solver_error(challenge.name, "create solver", error)
            return
        self.render_challenge_details(index)
        self.app.log_message(
            f"[{challenge.name}] Solver template created at {relative_path}."
        )

    def action_edit_solver(self) -> None:
        index = self._selected_challenge_index("edit the solver for")
        if index is None:
            return
        challenge = self.challenges[index]
        if challenge.solver is None:
            self.app.log_message(f"[{challenge.name}] No solver is configured.")
            return
        if (
            self.app._solver_service is None
            or self.ctf.id is None
            or challenge.id is None
        ):
            self.app.log_error("Cannot edit solver without managed storage IDs.")
            return
        self.app.log_message(f"[{challenge.name}] Opening solver in configured editor.")
        self.run_worker(
            self._edit_solver_in_editor(challenge),
            group="solver-editor",
            exclusive=True,
        )

    async def _edit_solver_in_editor(self, challenge: Challenge) -> None:
        service = self.app._solver_service
        if service is None or self.ctf.id is None or challenge.id is None:
            return
        try:
            # Give interactive editors ownership of the terminal while the UI is suspended.
            with self.app.suspend():
                await asyncio.to_thread(service.edit_solver, self.ctf.id, challenge.id)
        except (EditorError, SolverError, DataStoreError, OSError, ValueError) as error:
            self._log_solver_error(challenge.name, "open editor", error)
        else:
            self.app.log_message(f"[{challenge.name}] Editor session finished.")

    def action_run_solver(self) -> None:
        index = self._selected_challenge_index("run a solver for")
        if index is None:
            return
        if self._solver_cancel_event is not None:
            self.app.log_message("A solver is already running.")
            return
        challenge = self.challenges[index]
        if (
            self.app._solver_service is None
            or self.app._data_store is None
            or self.ctf.id is None
            or challenge.id is None
        ):
            self.app.log_error("Cannot run solver without managed storage IDs.")
            return
        if challenge.solver is None:
            self.app.log_message(
                f"[{challenge.name}] Create a solver before running it."
            )
            return
        try:
            artifact_paths = self._managed_artifact_paths(challenge)
        except (DataStoreError, SolverError, ValueError) as error:
            self._log_solver_error(challenge.name, "resolve artifacts", error)
            return
        cancel_event = threading.Event()
        self._solver_cancel_event = cancel_event
        self.refresh_bindings()
        self.app.log_message(
            f"[{challenge.name}] Solver running with {len(artifact_paths)} "
            "managed artifact argument(s)..."
        )
        self.run_worker(
            self._run_solver_worker(challenge, artifact_paths, cancel_event),
            group="challenge-solver",
            exclusive=True,
        )

    def _managed_artifact_paths(self, challenge: Challenge) -> tuple[Path, ...]:
        data_store = self.app._data_store
        if data_store is None or self.ctf.id is None or challenge.id is None:
            raise SolverError("managed storage IDs are unavailable")
        artifact_paths: list[Path] = []
        for artifact in challenge.artifacts:
            filename = artifact.get("filename")
            if not isinstance(filename, str):
                continue
            if not data_store.is_artifact_downloaded(
                self.ctf.id, challenge.id, filename
            ):
                continue
            path = data_store.resolve_challenge_file(
                self.ctf.id,
                challenge.id,
                f"artifacts/{filename}",
                must_exist=True,
            )
            artifact_paths.append(path)
        return tuple(artifact_paths)

    async def _run_solver_worker(
        self,
        challenge: Challenge,
        artifact_paths: Sequence[Path],
        cancel_event: threading.Event,
    ) -> None:
        service = self.app._solver_service
        if service is None or self.ctf.id is None or challenge.id is None:
            self._solver_cancel_event = None
            self.refresh_bindings()
            self.app.log_error("Cannot run solver without managed storage IDs.")
            return
        try:
            result = await asyncio.to_thread(
                service.run_solver,
                self.ctf.id,
                challenge.id,
                artifact_paths,
                cancel_event=cancel_event,
            )
        except Exception as error:
            self._log_solver_error(challenge.name, "run solver", error)
        else:
            if result.outcome == SolverOutcome.COMPLETED:
                self.app.log_message(
                    f"[{challenge.name}] Solver exited with status {result.returncode}."
                )
            elif result.outcome == SolverOutcome.CANCELLED:
                self.app.log_message(f"[{challenge.name}] Solver cancelled.")
            elif result.outcome == SolverOutcome.TIMED_OUT:
                self.app.log_error(f"[{challenge.name}] Solver timed out.")
            else:
                detail = f": {result.error}" if result.error else ""
                self.app.log_error(
                    f"[{challenge.name}] Solver could not start{detail}."
                )
            self.app.push_screen(
                SolverOutputDialog(
                    challenge.name,
                    result.outcome.value,
                    result.returncode,
                    result.stdout,
                    result.stderr,
                    result.error,
                )
            )
        finally:
            self._solver_cancel_event = None
            self.refresh_bindings()

    def action_cancel_solver(self) -> None:
        cancel_event = self._solver_cancel_event
        if cancel_event is None:
            self.app.log_message("No solver is currently running.")
            return
        cancel_event.set()
        self.app.log_message("Solver cancellation requested.")
        self.refresh_bindings()

    def _log_solver_error(
        self, challenge_name: str, operation: str, error: Exception
    ) -> None:
        if isinstance(error, (SolverError, EditorError, DataStoreError)):
            detail = str(error)
        else:
            detail = type(error).__name__
        self.app.log_error(f"[{challenge_name}] Could not {operation}: {detail}.")

    def make_challenge_list(self) -> ListView:
        return ListView(
            *(
                self.make_challenge_list_item(self.challenges[index])
                for index in self._visible_challenge_indices()
            ),
            id="challenge-list",
        )

    def _visible_challenge_indices(self) -> list[int]:
        query = self._filter_query.casefold()
        return [
            index
            for index, challenge in enumerate(self.challenges)
            if not query
            or query in challenge.name.casefold()
            or query in (challenge.category or "").casefold()
        ]

    def _challenge_index_at(self, list_index: int) -> int | None:
        visible_indices = self._visible_challenge_indices()
        if 0 <= list_index < len(visible_indices):
            return visible_indices[list_index]
        return None

    def _list_index_for_challenge(self, challenge_index: int) -> int | None:
        try:
            return self._visible_challenge_indices().index(challenge_index)
        except ValueError:
            return None

    def action_filter_challenges(self) -> None:
        self._filter_active = True
        self.query_one("#challenge-filter-row", Horizontal).styles.display = "block"
        query = self.query_one("#challenge-filter-query", Input)
        query.disabled = False
        query.value = self._filter_query
        query.focus()

    @on(Input.Changed, "#challenge-filter-query")
    async def filter_challenges(self, event: Input.Changed) -> None:
        if not self._filter_active:
            return
        selected_index: int | None = None
        if self.challenges:
            challenge_list = self.query_one("#challenge-list", ListView)
            if challenge_list.index is not None:
                selected_index = self._challenge_index_at(challenge_list.index)
        self._filter_query = event.value
        await self._refresh_challenge_list(
            selected_index if selected_index is not None else 0
        )

    @on(Input.Submitted, "#challenge-filter-query")
    def focus_filtered_challenges(self) -> None:
        if not self._visible_challenge_indices():
            return
        self.query_one("#challenge-list", ListView).focus()

    def make_challenge_list_item(self, challenge: Challenge) -> ListItem:
        status_label = self.STATUS_LABELS.get(challenge.status, "UNKNOWN")
        status_indicator = Static(
            status_label,
            classes="challenge-status-indicator",
            markup=False,
        )
        status_indicator.styles.color = self.STATUS_COLORS.get(
            challenge.status, "#ffffff"
        )
        return ListItem(
            Horizontal(
                Static(
                    challenge.name,
                    classes="challenge-name",
                    markup=False,
                ),
                status_indicator,
                classes="challenge-list-row",
            )
        )

    def update_challenge_list_item(self, index: int, challenge: Challenge) -> None:
        list_index = self._list_index_for_challenge(index)
        if list_index is None:
            return
        item = self.query_one("#challenge-list", ListView).children[list_index]
        item.query_one(".challenge-name", Static).update(challenge.name)
        status_indicator = item.query_one(".challenge-status-indicator", Static)
        status_indicator.update(self.STATUS_LABELS.get(challenge.status, "UNKNOWN"))
        status_indicator.styles.color = self.STATUS_COLORS.get(
            challenge.status, "#ffffff"
        )

    def action_add_challenge(self) -> None:
        self.app.push_screen(AddChallengeDialog(), self.add_challenge)

    def action_import_challenges(self) -> None:
        self.app.push_screen(
            ImportSourceDialog(),
            self.begin_import,
        )

    def begin_import(self, source: str | None) -> None:
        if source == "json":
            self.app.push_screen(
                ImportJSONDialog(),
                lambda records: self.preview_import("json_import", records),
            )
        elif source == "ctfd":
            self.app.push_screen(
                CTFdImportDialog(self.ctf, self.app._data_store),
                self.ctfd_import_loaded,
            )

    def ctfd_import_loaded(self, result: CTFdImportResult | None) -> None:
        if result is not None:
            self.preview_import("ctfd", result.challenges, platform_url=result.base_url)

    def preview_import(
        self,
        source: str,
        imported: Sequence[Mapping[str, object]] | None,
        *,
        platform_url: str | None = None,
    ) -> None:
        if imported is None:
            return
        try:
            plan = create_import_plan(
                imported,
                [_challenge_record(challenge) for challenge in self.challenges],
            )
        except ImportErrorBase as error:
            self.app.log_error(f"Import validation failed: {error}")
            return
        self.app.push_screen(
            ImportPreviewDialog(self.ctf.name, source, plan),
            lambda confirmed: self.apply_import(
                source, plan, confirmed, platform_url=platform_url
            ),
        )

    async def apply_import(
        self,
        source: str,
        plan: ImportPlan,
        confirmed: bool,
        *,
        platform_url: str | None = None,
    ) -> None:
        if not confirmed:
            self.app.log_message(
                "Challenge import cancelled; no challenges were added."
            )
            return
        records_to_add = [
            *plan.additions,
            *(record for record, _matches in plan.name_only_matches),
        ]
        if not records_to_add:
            if platform_url is not None:
                self._save_ctfd_platform_url(platform_url)
            self.app.log_message("Import confirmed; no new challenges to add.")
            return
        imported_challenges: list[Challenge] = []
        for record in records_to_add:
            challenge = Challenge(
                name=str(record["name"]),
                category=(
                    record["category"]
                    if isinstance(record.get("category"), str)
                    else None
                ),
                points=(
                    record["points"] if type(record.get("points")) is int else None
                ),
                description=str(record.get("description", "")),
                artifacts=tuple(
                    dict(artifact)
                    for artifact in record.get("artifacts", [])
                    if isinstance(artifact, Mapping)
                ),
                source=source,
                remote_id=(
                    str(record["remote_id"])
                    if isinstance(record.get("remote_id"), (str, int))
                    else None
                ),
            )
            imported_challenges.append(self.app._prepare_challenge(challenge))

        updated_challenges = [*self.challenges, *imported_challenges]
        if self.app._storage_error is not None:
            self.app.log_error(f"Cannot import challenges: {self.app._storage_error}")
            return
        if self.app._data_store is not None:
            if self.ctf.id is None:
                self.app._storage_failure(
                    DataStoreError("cannot import challenges for a CTF without an ID")
                )
                return
            try:
                self.app._data_store.save_challenges(
                    self.ctf.id,
                    [_challenge_record(challenge) for challenge in updated_challenges],
                )
            except DataStoreError as error:
                self.app._storage_failure(error)
                return

        self.challenges.extend(imported_challenges)
        await self._refresh_challenge_list(len(self.challenges) - 1)
        self.refresh_bindings()
        self.app.log_message(
            f"Imported {len(imported_challenges)} challenge(s) into {self.ctf.name}."
        )
        if platform_url is not None:
            self._save_ctfd_platform_url(platform_url)

    def _save_ctfd_platform_url(self, platform_url: str) -> bool:
        ctf_index = next(
            (
                index
                for index, ctf in enumerate(self.app._ctfs)
                if ctf.id == self.ctf.id
            ),
            None,
        )
        if ctf_index is None:
            self.app._storage_failure(
                DataStoreError("cannot save CTFd URL for a CTF without a stored ID")
            )
            return False
        current = self.app._ctfs[ctf_index]
        if current.platform_url == platform_url:
            self.ctf = current
            return True
        updated = replace(
            current,
            platform_url=platform_url,
            updated_at=utc_timestamp()
            if self.app._data_store is not None
            else self.app._ctfs[ctf_index].updated_at,
        )
        if self.app._data_store is not None:
            records = list(self.app._ctfs)
            records[ctf_index] = updated
            try:
                self.app._data_store.save_ctfs([_ctf_record(ctf) for ctf in records])
            except DataStoreError as error:
                self.app._storage_failure(error)
                return False
        self.app._ctfs[ctf_index] = updated
        self.ctf = updated
        return True

    def action_download_artifacts(self) -> None:
        index = self._selected_challenge_index("download artifacts for")
        if index is None:
            return
        challenge = self.challenges[index]
        if challenge.source != "ctfd" or challenge.remote_id is None:
            self.app.log_message("Artifact download is available for CTFd challenges.")
            return
        if not challenge.artifacts:
            self.app.log_message(f"[{challenge.name}] No artifacts are attached.")
            return
        data_store = self.app._data_store
        if data_store is None or self.ctf.id is None or challenge.id is None:
            self.app.log_error("Cannot download artifacts without managed storage IDs.")
            return
        if not self.ctf.platform_url:
            self.app.log_error(
                "No CTFd platform URL is saved. Import from CTFd to configure it."
            )
            return
        try:
            token = data_store.load_ctfd_token(self.ctf.id, self.ctf.platform_url)
        except DataStoreError as error:
            self.app.log_error(f"Cannot load CTFd credentials: {error}")
            return
        if token is None:
            self.app.log_error(
                "No saved CTFd token for this URL. Import from CTFd to configure it."
            )
            return

        artifacts: list[tuple[dict[str, object], bool]] = []
        for artifact in challenge.artifacts:
            filename = artifact.get("filename")
            if not isinstance(filename, str):
                self.app.log_error(
                    f"[{challenge.name}] An artifact has an invalid filename."
                )
                return
            try:
                downloaded = data_store.is_artifact_downloaded(
                    self.ctf.id, challenge.id, filename
                )
            except DataStoreError as error:
                self.app.log_error(
                    f"[{challenge.name}] Cannot check {filename}: {error}"
                )
                return
            artifacts.append((dict(artifact), downloaded))

        if any(downloaded for _artifact, downloaded in artifacts):
            self.app.push_screen(
                ArtifactDownloadDialog(
                    challenge.name,
                    [
                        (str(artifact["filename"]), downloaded)
                        for artifact, downloaded in artifacts
                    ],
                ),
                lambda confirmed: self._start_artifact_download(
                    challenge, artifacts, token, confirmed=confirmed
                ),
            )
        else:
            self._start_artifact_download(challenge, artifacts, token, confirmed=True)

    def action_open_artifacts_directory(self) -> None:
        index = self._selected_challenge_index("open artifacts for")
        if index is None:
            return
        challenge = self.challenges[index]
        if self.app._data_store is None or self.ctf.id is None or challenge.id is None:
            self.app.log_error("Cannot open artifacts without managed storage IDs.")
            return
        self.app.push_screen(
            OpenArtifactsDirectoryDialog(),
            lambda choice: self.open_artifacts_directory(challenge, choice),
        )

    def open_artifacts_directory(
        self,
        challenge: Challenge,
        choice: str | None,
    ) -> None:
        if choice is None:
            return
        data_store = self.app._data_store
        if data_store is None or self.ctf.id is None or challenge.id is None:
            self.app.log_error("Cannot open artifacts without managed storage IDs.")
            return
        try:
            directory = data_store.challenge_artifacts_directory(
                self.ctf.id, challenge.id
            )
        except DataStoreError as error:
            self.app.log_error(
                f"[{challenge.name}] Cannot open artifacts directory: {error}"
            )
            return

        if choice == "terminal":
            self.app.log_message(
                f"[{challenge.name}] Opening artifacts directory in terminal."
            )
            try:
                open_directory_in_terminal(directory)
            except OSError as error:
                self.app.log_error(f"[{challenge.name}] Cannot open terminal: {error}")
                return
            self.app.log_message(
                f"[{challenge.name}] Artifacts directory opened in terminal."
            )
        elif choice == "explorer":
            try:
                open_directory_in_file_explorer(directory)
            except OSError as error:
                self.app.log_error(
                    f"[{challenge.name}] Cannot open file explorer: {error}"
                )
                return
            self.app.log_message(
                f"[{challenge.name}] Opened artifacts directory in file explorer."
            )
        else:
            self.app.log_error("Unknown artifacts directory option.")

    def _start_artifact_download(
        self,
        challenge: Challenge,
        artifacts: Sequence[tuple[dict[str, object], bool]],
        token: str,
        *,
        confirmed: bool | None,
    ) -> None:
        if confirmed is not True:
            self.app.log_message(
                f"[{challenge.name}] Artifact download cancelled; no files changed."
            )
            return
        if self._artifact_download_active:
            self.app.log_message(
                f"[{challenge.name}] Artifact download is already running."
            )
            return
        self._artifact_download_active = True
        self.refresh_bindings()
        self.run_worker(
            self.download_challenge_artifacts(challenge, artifacts, token),
            group="artifact-download",
            exclusive=True,
        )

    async def download_challenge_artifacts(
        self,
        challenge: Challenge,
        artifacts: Sequence[tuple[dict[str, object], bool]],
        token: str,
    ) -> None:
        try:
            data_store = self.app._data_store
            if data_store is None or self.ctf.id is None or challenge.id is None:
                self.app.log_error(
                    "Cannot download artifacts without managed storage IDs."
                )
                return
            platform_url = self.ctf.platform_url
            if not platform_url or challenge.remote_id is None:
                self.app.log_error("CTFd download configuration is incomplete.")
                return
            self.app.log_message(
                f"[{challenge.name}] Downloading {len(artifacts)} artifact(s)..."
            )
            downloaded = 0
            failures = 0
            for artifact, overwrite in artifacts:
                filename = str(artifact["filename"])
                try:
                    await asyncio.to_thread(
                        self._download_and_save_artifact,
                        data_store,
                        self.ctf.id,
                        challenge.id,
                        platform_url,
                        token,
                        challenge.remote_id,
                        artifact,
                        overwrite,
                    )
                except (CTFdError, DataStoreError) as error:
                    failures += 1
                    self.app.log_error(f"[{challenge.name}] {filename}: {error}")
                else:
                    downloaded += 1
                    self.app.log_message(f"[{challenge.name}] Downloaded {filename}.")
            selected_index = next(
                (
                    index
                    for index, item in enumerate(self.challenges)
                    if item.id == challenge.id
                ),
                None,
            )
            if selected_index is not None:
                self.render_challenge_details(selected_index)
            self.app.log_message(
                f"[{challenge.name}] Artifact download finished: "
                f"{downloaded} downloaded, {failures} failed."
            )
        finally:
            self._artifact_download_active = False
            self.refresh_bindings()

    @staticmethod
    def _download_and_save_artifact(
        data_store: DataStore,
        ctf_id: str,
        challenge_id: str,
        platform_url: str,
        token: str,
        remote_id: str,
        artifact: Mapping[str, object],
        overwrite: bool,
    ) -> None:
        data_store.save_artifact(
            ctf_id,
            challenge_id,
            str(artifact["filename"]),
            download_ctfd_artifact(platform_url, token, remote_id, artifact),
            overwrite=overwrite,
        )

    async def action_refresh_ctfd_challenges(self) -> None:
        sources = tuple(
            source
            for source in ("ctfd", "json_import")
            if any(
                challenge.source == source and challenge.remote_id is not None
                for challenge in self.challenges
            )
        )
        if len(sources) > 1:
            self.app.push_screen(RefreshSourceDialog(sources), self.begin_refresh)
            return
        if not sources:
            return
        if sources[0] == "json_import":
            self.begin_json_refresh()
            return
        await self.refresh_ctfd_challenges()

    def begin_refresh(self, source: str | None) -> None:
        if source == "ctfd":
            self.run_worker(self.refresh_ctfd_challenges(), group="challenge-refresh")
        elif source == "json_import":
            self.begin_json_refresh()

    def begin_json_refresh(self) -> None:
        self.app.push_screen(
            ImportJSONDialog(purpose="refresh"),
            self.json_refresh_loaded,
        )

    def json_refresh_loaded(
        self, imported: Sequence[Mapping[str, object]] | None
    ) -> None:
        if imported is None:
            return
        try:
            plan = create_refresh_plan(
                imported,
                [_challenge_record(challenge) for challenge in self.challenges],
                source="json_import",
            )
        except ImportErrorBase as error:
            self.app.log_error(f"JSON refresh failed: {error}")
            return
        self.app.push_screen(
            CTFdRefreshPreviewDialog(self.ctf.name, plan, "CTFd JSON"),
            lambda confirmed: self.apply_ctfd_refresh(
                plan, confirmed, source="json_import"
            ),
        )

    async def refresh_ctfd_challenges(self) -> None:
        if not self.ctf.platform_url:
            self.app.log_error(
                "No CTFd platform URL is saved. Import from CTFd to configure it."
            )
            return
        data_store = self.app._data_store
        if data_store is None or self.ctf.id is None:
            self.app.log_error("Cannot refresh CTFd without managed CTF storage.")
            return
        try:
            token = data_store.load_ctfd_token(self.ctf.id, self.ctf.platform_url)
        except DataStoreError as error:
            self.app.log_error(f"Cannot load CTFd credentials: {error}")
            return
        if token is None:
            self.app.log_error(
                "No saved CTFd token for this URL. Import from CTFd to configure it."
            )
            return
        try:
            imported = await asyncio.to_thread(
                fetch_ctfd_challenges,
                self.ctf.platform_url,
                token,
            )
            plan = create_refresh_plan(
                imported,
                [_challenge_record(challenge) for challenge in self.challenges],
            )
        except (CTFdError, ImportErrorBase) as error:
            self.app.log_error(f"CTFd refresh failed: {error}")
            return
        self.app.push_screen(
            CTFdRefreshPreviewDialog(self.ctf.name, plan),
            lambda confirmed: self.apply_ctfd_refresh(plan, confirmed),
        )

    async def apply_ctfd_refresh(
        self,
        plan: RefreshPlan,
        confirmed: bool | None,
        *,
        source: str = "ctfd",
    ) -> None:
        source_label = "CTFd JSON" if source == "json_import" else "CTFd API"
        if confirmed is not True:
            self.app.log_message(
                f"{source_label} refresh cancelled; no challenges changed."
            )
            return
        if not plan.additions and not plan.updates:
            self.app.log_message(
                f"{source_label} refresh confirmed; no new or changed challenges. "
                f"{len(plan.missing)} remotely missing challenge(s) were retained."
            )
            return

        updates = {
            str(local["id"]): dict(merged) for _remote, local, merged in plan.updates
        }
        selected_index = 0
        if self.challenges:
            selected_index = self.query_one("#challenge-list", ListView).index or 0
        refreshed: list[Challenge] = []
        for challenge in self.challenges:
            record = updates.get(str(challenge.id))
            if record is None:
                refreshed.append(challenge)
                continue
            record["updated_at"] = utc_timestamp()
            refreshed.append(_challenge_from_record(record))

        additions: list[Challenge] = []
        for record in plan.additions:
            challenge = Challenge(
                name=str(record["name"]),
                category=(
                    record["category"]
                    if isinstance(record.get("category"), str)
                    else None
                ),
                points=(
                    record["points"] if type(record.get("points")) is int else None
                ),
                description=str(record.get("description", "")),
                artifacts=tuple(
                    dict(artifact)
                    for artifact in record.get("artifacts", [])
                    if isinstance(artifact, Mapping)
                ),
                source=source,
                remote_id=str(record["remote_id"]),
            )
            prepared = self.app._prepare_challenge(challenge)
            additions.append(prepared)
        refreshed.extend(additions)

        if self.app._storage_error is not None:
            self.app.log_error(f"Cannot refresh challenges: {self.app._storage_error}")
            return
        if self.app._data_store is not None:
            if self.ctf.id is None:
                self.app._storage_failure(
                    DataStoreError("cannot refresh challenges without a CTF ID")
                )
                return
            try:
                self.app._data_store.save_challenges(
                    self.ctf.id,
                    [_challenge_record(challenge) for challenge in refreshed],
                )
            except DataStoreError as error:
                self.app._storage_failure(error)
                return

        self.challenges[:] = refreshed
        await self._refresh_challenge_list(selected_index)
        self.refresh_bindings()
        self.app.log_message(
            f"{source_label} refresh applied: {len(additions)} added, "
            f"{len(plan.updates)} updated; missing remote challenges were retained."
        )

    async def add_challenge(self, challenge: Challenge | None) -> None:
        if challenge is None:
            return
        challenge = self.app.persist_challenge(self.ctf, self.challenges, challenge)
        if challenge is None:
            return
        self.challenges.append(challenge)
        self.app.log_message(f"[{challenge.name}] Challenge added.")
        await self._refresh_challenge_list(len(self.challenges) - 1)

    @on(ListView.Highlighted, "#challenge-list")
    def show_challenge_details(self, event: ListView.Highlighted) -> None:
        self.refresh_bindings()
        index = event.list_view.index
        if index is not None:
            challenge_index = self._challenge_index_at(index)
            if challenge_index is not None:
                self.render_challenge_details(challenge_index)

    def render_challenge_details(self, index: int) -> None:
        challenge = self.challenges[index]
        notes = ""
        data_store = self.app._data_store
        if data_store is not None and self.ctf.id and challenge.id:
            try:
                notes = data_store.read_challenge_notes(self.ctf.id, challenge.id)
            except DataStoreError as error:
                notes = f"Cannot load notes: {error}"
        details_text = Text(challenge.name, style=self.CHALLENGE_NAME_COLOR)
        details_text.append("\n\nCategory: ", style=self.DETAIL_LABEL_COLOR)
        details_text.append(f"{challenge.category or '—'}\n")
        details_text.append("Points: ", style=self.DETAIL_LABEL_COLOR)
        details_text.append(
            f"{challenge.points if challenge.points is not None else '—'}"
        )
        details_text.append("\nStatus: ", style=self.DETAIL_LABEL_COLOR)
        details_text.append(
            self.STATUS_LABELS.get(challenge.status, "UNKNOWN"),
            style=self.STATUS_COLORS.get(challenge.status, "#ffffff"),
        )
        details_text.append("\nFlag: ", style=self.DETAIL_LABEL_COLOR)
        details_text.append(f"{challenge.flag or '—'}\n")
        details_text.append("\n")
        details_text.append(
            challenge.description or "No description.",
            style=self.DESCRIPTION_COLOR,
        )
        details_text.append(
            "\n\nARTIFACTS\n" + "\n".join(self._artifact_details(challenge))
        )
        details_text.append("\n\nSOLVER\n" + "\n".join(self._solver_details(challenge)))
        details_text.append("\n\nNOTES\n")
        if notes:
            details_text.append("\n")
            details_text.append("\n".join(notes.splitlines()), style=self.NOTE_COLOR)
        else:
            details_text.append("  None")
        self.query_one("#challenge-details-content", Static).update(details_text)

    def _artifact_details(self, challenge: Challenge) -> list[str]:
        if not challenge.artifacts:
            return ["  None"]

        data_store = self.app._data_store
        lines: list[str] = []
        for artifact in challenge.artifacts:
            filename = artifact.get("filename")
            if not isinstance(filename, str):
                filename = "Unknown artifact"
            if data_store is None or self.ctf.id is None or challenge.id is None:
                status = "not downloaded"
            else:
                try:
                    downloaded = data_store.is_artifact_downloaded(
                        self.ctf.id, challenge.id, filename
                    )
                except DataStoreError as error:
                    status = f"status unavailable: {error}"
                else:
                    status = "downloaded" if downloaded else "not downloaded"
            lines.append(f"  {filename}: {status}")
        return lines

    @staticmethod
    def _solver_details(challenge: Challenge) -> list[str]:
        if challenge.solver is None:
            return ["  None"]
        return [f"  {key}: {value}" for key, value in sorted(challenge.solver.items())]

    def _selected_challenge_index(self, action: str) -> int | None:
        if not self.challenges:
            self.app.log_message(f"No challenge selected to {action}.")
            return None
        try:
            challenge_list = self.query_one("#challenge-list", ListView)
        except NoMatches:
            self.app.log_message(f"Select a challenge to {action}.")
            return None
        index = challenge_list.index
        if index is None:
            self.app.log_message(f"Select a challenge to {action}.")
            return None
        challenge_index = self._challenge_index_at(index)
        if challenge_index is None:
            self.app.log_message(f"Select a challenge to {action}.")
        return challenge_index

    def action_edit_challenge(self) -> None:
        index = self._selected_challenge_index("edit")
        if index is not None:
            self.app.push_screen(
                EditChallengeDialog(self.challenges[index]),
                lambda updated: self.update_challenge(index, updated),
            )

    def action_delete_challenge(self) -> None:
        index = self._selected_challenge_index("remove")
        if index is not None:
            self.app.push_screen(
                ConfirmDeleteChallengeDialog(self.challenges[index]),
                lambda confirmed: self.remove_challenge(index, confirmed),
            )

    async def update_challenge(self, index: int, updated: Challenge | None) -> None:
        if updated is None:
            return
        original = self.challenges[index]
        updated = replace(
            updated,
            id=original.id,
            source=original.source,
            remote_id=original.remote_id,
            solver=original.solver,
            created_at=original.created_at,
            updated_at=(
                utc_timestamp()
                if self.app._data_store is not None
                else original.updated_at
            ),
        )
        saved = self.app.persist_challenge(self.ctf, self.challenges, updated)
        if saved is None:
            return
        self.challenges[index] = saved
        await self._refresh_challenge_list(index)
        self.app.log_message(f"[{saved.name}] Challenge updated.")

    async def remove_challenge(self, index: int, confirmed: bool) -> None:
        if not confirmed:
            return
        challenge = self.challenges[index]
        if self.app._storage_error is not None:
            self.app.log_error(f"Cannot remove challenge: {self.app._storage_error}")
            return
        remaining = self.challenges[:index] + self.challenges[index + 1 :]
        retained_directory: Path | None = None
        if self.app._data_store is not None:
            if self.ctf.id is None or challenge.id is None:
                self.app._storage_failure(
                    DataStoreError("cannot remove a challenge without stable IDs")
                )
                return
            try:
                retained_directory = self.app._data_store.delete_challenge(
                    self.ctf.id,
                    challenge.id,
                    [_challenge_record(item) for item in remaining],
                )
            except DataStoreError as error:
                self.app._storage_failure(error)
                return
        del self.challenges[index]
        await self._refresh_challenge_list(index)
        if retained_directory is None:
            self.app.log_message(f"[{challenge.name}] Challenge removed.")
        else:
            self.app.log_error(
                f"[{challenge.name}] Challenge removed; data cleanup failed, "
                f"retained at {retained_directory}"
            )

    async def _refresh_challenge_list(self, selected_index: int) -> None:
        await self.query_one("#challenge-list").remove()
        panel = self.query_one("#challenge-panel", Vertical)
        visible_indices = self._visible_challenge_indices()
        filter_input_focused = self.query_one(
            "#challenge-filter-query", Input
        ).has_focus
        if self.challenges:
            await panel.mount(self.make_challenge_list())
            challenge_list = self.query_one("#challenge-list", ListView)
            list_index = self._list_index_for_challenge(selected_index)
            if list_index is None and visible_indices:
                list_index = 0
            challenge_list.index = list_index
            if list_index is not None:
                if not filter_input_focused:
                    challenge_list.focus()
                challenge_index = self._challenge_index_at(list_index)
                if challenge_index is not None:
                    self.render_challenge_details(challenge_index)
            else:
                self.query_one("#challenge-details-content", Static).update(
                    "No challenges match the filter."
                )
        else:
            await panel.mount(
                Static(
                    "No challenges yet.\n\nPress A to add a challenge.",
                    id="challenge-list",
                    classes="challenge-empty",
                    markup=False,
                )
            )
            self.screen.set_focus(None)
            self.query_one("#challenge-details-content", Static).update(
                "No challenge selected."
            )
        self.refresh_bindings()

    def action_set_challenge_status(self) -> None:
        index = self._selected_challenge_index("set status for")
        if index is None:
            return
        self.app.push_screen(
            SelectChallengeStatusDialog(self.challenges[index].status),
            self._set_challenge_status,
        )

    def _set_challenge_status(self, status: str | None) -> None:
        if status is None:
            return
        index = self._selected_challenge_index("update status")
        if index is None:
            return
        challenge = self.challenges[index]
        status_label = status.replace("_", " ").title()
        if challenge.status == status:
            self.app.log_message(
                f"[{challenge.name}]: Status is already: {status_label}"
            )
            return
        updated = replace(challenge, status=status)
        saved = self.app.persist_challenge(self.ctf, self.challenges, updated)
        if saved is None:
            return
        self.challenges[index] = saved
        self.update_challenge_list_item(index, saved)
        self.render_challenge_details(index)
        self.app.log_message(f"[{saved.name}]: Status changed to: {status_label}")

    def action_edit_flag(self) -> None:
        index = self._selected_challenge_index("edit the flag for")
        if index is None:
            return
        challenge = self.challenges[index]
        can_submit = False
        token: str | None = None
        if (
            challenge.source == "ctfd"
            and challenge.remote_id is not None
            and self.ctf.platform_url is not None
            and self.app._data_store is not None
            and self.ctf.id is not None
        ):
            try:
                token = self.app._data_store.load_ctfd_token(
                    self.ctf.id, self.ctf.platform_url
                )
            except DataStoreError as error:
                self.app.log_error(
                    f"[{challenge.name}] Cannot load CTFd credentials: {error}"
                )
            can_submit = token is not None

        self.app.push_screen(
            EditFlagDialog(challenge, can_submit=can_submit),
            lambda result: self._flag_dialog_result(index, result, token),
        )

    def _flag_dialog_result(
        self,
        index: int,
        result: tuple[str, str] | None,
        token: str | None,
    ) -> None:
        if result is None:
            return
        action, flag = result
        if action == "submit":
            challenge = self.challenges[index]
            if (
                token is None
                or self.ctf.platform_url is None
                or challenge.remote_id is None
            ):
                self.app.log_error(
                    f"[{challenge.name}] CTFd submission configuration is incomplete."
                )
                return
            if not flag:
                self.app.log_error(f"[{challenge.name}] Enter a flag to submit.")
                return
            self.run_worker(
                self._submit_flag_and_save(
                    index,
                    flag,
                    self.ctf.platform_url,
                    token,
                    challenge.remote_id,
                ),
                group="ctfd-flag-submission",
                exclusive=True,
            )
        else:
            self.run_worker(self.update_flag(index, flag), group="flag-save")

    async def _submit_flag_and_save(
        self,
        index: int,
        flag: str,
        platform_url: str,
        token: str,
        remote_id: str,
    ) -> None:
        challenge = self.challenges[index]
        self.app.log_message(f"[{challenge.name}] Submitting flag to CTFd...")
        try:
            status = await asyncio.to_thread(
                submit_ctfd_flag,
                platform_url,
                token,
                remote_id,
                flag,
            )
        except CTFdError as error:
            self.app.log_error(
                f"[{challenge.name}] CTFd flag submission failed: {error}"
            )
            return
        if status != "correct":
            self.app.log_error(
                f"[{challenge.name}] CTFd did not verify the flag; "
                "no local changes were made."
            )
            return
        await self.update_flag(index, flag, verified=True)

    def action_note(self) -> None:
        index = self._selected_challenge_index("edit a note for")
        if index is None:
            return

        challenge = self.challenges[index]
        data_store = self.app._data_store
        if data_store is None:
            self.app.log_error(
                f"[{challenge.name}] Cannot edit note: persistent storage "
                "is not configured."
            )
            return
        if self.ctf.id is None or challenge.id is None:
            self.app.log_error(
                f"[{challenge.name}] Cannot edit note: the selected CTF and "
                "challenge must have stable IDs."
            )
            return
        if self.app._storage_error is not None:
            self.app.log_error(
                f"[{challenge.name}] Cannot edit note: storage is unavailable: "
                f"{self.app._storage_error}"
            )
            return

        try:
            note_path = data_store.ensure_challenge_notes_file(
                self.ctf.id,
                challenge.id,
            )
            with self.app.suspend():
                # Keep the historical app-module monkeypatch seam used by
                # callers and tests while the screen lives in its own module.
                from ctfwb import app as app_entry

                exit_status = app_entry.run_editor(
                    self.app.editor,
                    self.app.editor_args,
                    note_path,
                )
        except (DataStoreError, OSError) as error:
            self.app.log_error(f"[{challenge.name}] Cannot edit note: {error}")
            return

        if exit_status != 0:
            self.app.log_error(
                f"[{challenge.name}] Note editor exited with non-zero "
                f"status {exit_status}."
            )
            return
        self.app.log_message(f"[{challenge.name}] Note edited.")
        self.render_challenge_details(index)

    async def update_flag(
        self,
        index: int,
        flag: str | None,
        *,
        verified: bool = False,
    ) -> None:
        if flag is None:
            return
        challenge = self.challenges[index]
        updated_flag = flag or None
        unchanged = updated_flag == (challenge.flag or None)
        if unchanged and (not verified or challenge.status == "solved"):
            if verified and updated_flag is not None:
                self.app.log_message(
                    f"[{challenge.name}] CTFd verified flag: {updated_flag}; "
                    "challenge is already solved."
                )
            else:
                self.app.log_message(f"[{challenge.name}] Flag unchanged.")
            return
        status = (
            "solved"
            if updated_flag is not None and (verified or not challenge.flag)
            else challenge.status
        )
        updated = replace(challenge, flag=updated_flag, status=status)
        saved = self.app.persist_challenge(self.ctf, self.challenges, updated)
        if saved is None:
            return
        self.challenges[index] = saved
        self.update_challenge_list_item(index, saved)
        self.render_challenge_details(index)
        if verified:
            self.app.log_message(
                f"[{challenge.name}] CTFd verified flag: {updated_flag}; "
                "status changed to: Solved"
            )
        elif not challenge.flag and updated_flag is not None:
            self.app.log_message(
                f"[{challenge.name}] Added flag: {updated_flag}; "
                "status changed to: Solved"
            )
        elif updated_flag is None:
            self.app.log_message(f"[{challenge.name}] Removed flag; status unchanged.")
        else:
            self.app.log_message(f"[{challenge.name}] Updated flag: {updated_flag}")

    def action_challenge_down(self) -> None:
        if self.query_one("#challenge-details", VerticalScroll).has_focus:
            self.query_one("#challenge-details", VerticalScroll).scroll_relative(
                y=1, animate=False
            )
        elif self.challenges:
            self.query_one("#challenge-list", ListView).action_cursor_down()

    def action_challenge_up(self) -> None:
        if self.query_one("#challenge-details", VerticalScroll).has_focus:
            self.query_one("#challenge-details", VerticalScroll).scroll_relative(
                y=-1, animate=False
            )
        elif self.challenges:
            self.query_one("#challenge-list", ListView).action_cursor_up()

    def action_toggle_panel(self) -> None:
        if not self.challenges:
            return
        challenge_list = self.query_one("#challenge-list", ListView)
        details = self.query_one("#challenge-details", VerticalScroll)
        if details.has_focus:
            challenge_list.focus()
        else:
            details.focus()

    def action_focus_challenge_list(self) -> None:
        if self.challenges:
            self.query_one("#challenge-list", ListView).focus()

    def action_focus_challenge_details(self) -> None:
        if self.challenges:
            self.query_one("#challenge-details", VerticalScroll).focus()

    def action_challenge_page_down(self) -> None:
        if not self.challenges:
            return
        details = self.query_one("#challenge-details", VerticalScroll)
        if details.has_focus:
            details.scroll_page_down(animate=False)
        else:
            visible_count = len(self._visible_challenge_indices())
            if visible_count == 0:
                return
            challenge_list = self.query_one("#challenge-list", ListView)
            challenge_list.index = min(
                (challenge_list.index or 0) + 15, visible_count - 1
            )

    def action_challenge_page_up(self) -> None:
        if not self.challenges:
            return
        details = self.query_one("#challenge-details", VerticalScroll)
        if details.has_focus:
            details.scroll_page_up(animate=False)
        else:
            if not self._visible_challenge_indices():
                return
            challenge_list = self.query_one("#challenge-list", ListView)
            challenge_list.index = max((challenge_list.index or 0) - 15, 0)

    async def action_back(self) -> None:
        if self._filter_active:
            selected_index: int | None = None
            if self.challenges:
                challenge_list = self.query_one("#challenge-list", ListView)
                if challenge_list.index is not None:
                    selected_index = self._challenge_index_at(challenge_list.index)
            self._filter_active = False
            self._filter_query = ""
            query = self.query_one("#challenge-filter-query", Input)
            query.value = ""
            query.disabled = True
            self.query_one("#challenge-filter-row", Horizontal).styles.display = "none"
            await self._refresh_challenge_list(
                selected_index if selected_index is not None else 0
            )
            if self.challenges:
                challenge_list = self.query_one("#challenge-list", ListView)
                if challenge_list.index is not None:
                    challenge_list.focus()
            return
        self.app.pop_screen()
