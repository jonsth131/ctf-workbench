"""Top-level CTF browser application and CTF selection screen behavior."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from pathlib import Path
from typing import Sequence

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.css.query import NoMatches
from textual.widgets import Footer, Header, Label, ListItem, ListView, Static

from ctfwb.config import AppConfig
from ctfwb.logging_setup import (
    APP_LOGGER,
    log_debug_exception,
)
from ctfwb.solvers import SolverService
from ctfwb.storage import DataStore, DataStoreError, generate_id, utc_timestamp
from ctfwb.ui.dialogs import (
    AddCTFDialog,
    ConfirmDeleteCTFDialog,
    ExportArchiveDialog,
)
from ctfwb.ui.models import (
    CTF,
    Challenge,
    CTFTimeLookup,
    _challenge_from_record,
    _challenge_record,
    _ctf_from_record,
    _ctf_record,
    _default_ctftime_lookup,
)
from ctfwb.ui.screens.challenges import CTFChallengeScreen
from ctfwb.ui.screens.ctfs import CTFSelectionView


class CTFWorkbenchApp(App[None]):
    """CTF browser with optional file-backed storage."""

    LOG_HISTORY_LIMIT = 5
    TITLE = "CTF WORKBENCH"
    SUB_TITLE = "CTF BROWSER"

    CSS = """
    Screen {
        background: #07131c;
        color: #d7e4df;
    }

    #log-panel {
        height: 7;
        border-top: solid #397a78;
        padding: 0 2;
        color: #9cb8b2;
    }

    #log-message {
        height: 5;
        overflow-y: auto;
    }

    #log-title {
        color: #71d6bc;
        text-style: bold;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("a", "add_ctf", "Add"),
        Binding("e", "edit_ctf", "Edit"),
        Binding("d", "delete_ctf", "Delete"),
        Binding("b", "export_backup", "Backup"),
        Binding("j", "ctf_down", "Next"),
        Binding("k", "ctf_up", "Prev"),
    ]

    def __init__(
        self,
        ctfs: Sequence[CTF] = (),
        *,
        ctftime_lookup: CTFTimeLookup | None = None,
        data_store: DataStore | None = None,
        editor: str = "nvim",
        editor_args: Sequence[str] = (),
        config: AppConfig | None = None,
    ) -> None:
        super().__init__()
        self._data_store = data_store
        self.config = config or AppConfig(
            data_dir=data_store.data_dir if data_store is not None else Path.cwd(),
            config_path=Path.cwd() / "ctf-workbench.toml",
            editor=editor,
            editor_args=tuple(editor_args),
        )
        self.editor = self.config.editor
        self.editor_args = self.config.editor_args
        self._solver_service = (
            SolverService(
                data_store,
                self.config,
                warning_callback=self._log_solver_warning,
            )
            if data_store is not None
            else None
        )
        self._storage_error: str | None = None
        self._startup_state_error: str | None = None
        self._last_ctf_id: str | None = None
        if data_store is None:
            self._ctfs = list(ctfs)
            self._challenges = [[] for _ in self._ctfs]
        else:
            try:
                ctf_records = data_store.load_ctfs()
                self._ctfs = [_ctf_from_record(record) for record in ctf_records]
                self._challenges = [
                    [
                        _challenge_from_record(record)
                        for record in data_store.load_challenges(ctf.id or "")
                    ]
                    for ctf in self._ctfs
                ]
            except DataStoreError as error:
                self._ctfs = []
                self._challenges = []
                self._storage_error = str(error)
                log_debug_exception("Storage initialization failed", error)
            if self._storage_error is None:
                try:
                    self._last_ctf_id = data_store.load_last_ctf_id()
                except DataStoreError as error:
                    self._startup_state_error = str(error)
                    log_debug_exception("Last CTF state could not be loaded", error)
        self._ctftime_lookup = ctftime_lookup or _default_ctftime_lookup
        self._log_messages = (
            [f"Storage error: {self._storage_error}"]
            if self._storage_error is not None
            else ["CTF Workbench ready."]
        )
        if self._startup_state_error is not None:
            self._log_messages.append(
                f"Cannot restore last CTF: {self._startup_state_error}"
            )
        self._log_message = self._format_log_messages()
        if self._storage_error is not None and APP_LOGGER.handlers:
            APP_LOGGER.error("Storage error: %s", self._storage_error)

    def on_mount(self) -> None:
        if self._last_ctf_id is None:
            return
        index = next(
            (
                index
                for index, ctf in enumerate(self._ctfs)
                if ctf.id == self._last_ctf_id
            ),
            None,
        )
        if index is None:
            self.log_error("The previously opened CTF is no longer available.")
            self._last_ctf_id = None
            if self._data_store is not None:
                try:
                    self._data_store.save_last_ctf_id(None)
                except DataStoreError as error:
                    self.log_error(f"Cannot clear last CTF state: {error}")
            return
        self.open_ctf(index)

    def compose(self) -> ComposeResult:
        yield Header()
        yield CTFSelectionView()
        with Vertical(id="log-panel"):
            yield Label("LOG", id="log-title")
            yield Static(self._log_message, id="log-message", markup=False)
        yield Footer()

    def action_add_ctf(self) -> None:
        self.push_screen(AddCTFDialog(self._ctftime_lookup), self.add_ctf)

    def action_edit_ctf(self) -> None:
        if self.screen is not self.screen_stack[0]:
            return
        if not self._ctfs:
            self.log_message("No CTF selected to update.")
            return
        ctf_list = self.query_one("#ctf-list", ListView)
        index = ctf_list.index
        if index is None:
            self.log_message("Select a CTF to update.")
            return
        self.push_screen(
            AddCTFDialog(self._ctftime_lookup, self._ctfs[index]),
            lambda ctf: self.update_ctf(index, ctf),
        )

    def action_delete_ctf(self) -> None:
        if self.screen is not self.screen_stack[0]:
            return
        if not self._ctfs:
            self.log_message("No CTF selected to remove.")
            return
        ctf_list = self.query_one("#ctf-list", ListView)
        index = ctf_list.index
        if index is None:
            self.log_message("Select a CTF to remove.")
            return
        self.push_screen(
            ConfirmDeleteCTFDialog(self._ctfs[index]),
            lambda confirmed: self.remove_ctf(index, confirmed),
        )

    def action_export_backup(self) -> None:
        """Offer a user-invoked archive export from the CTF browser."""
        self.push_screen(ExportArchiveDialog(), self.export_archive)

    def open_ctf(self, index: int) -> None:
        ctf = self._ctfs[index]
        if self._data_store is not None and ctf.id is not None:
            self._last_ctf_id = ctf.id
            if self._storage_error is None:
                try:
                    self._data_store.save_last_ctf_id(ctf.id)
                except DataStoreError as error:
                    self.log_error(f"Cannot remember last CTF: {error}")
        self.push_screen(
            CTFChallengeScreen(
                ctf,
                self._log_message,
                self._challenges[index],
            )
        )

    async def export_archive(self, request: tuple[Path, bool] | None) -> None:
        if request is None:
            return
        if self._data_store is None:
            self.log_error("Cannot export: managed storage is unavailable.")
            return
        destination, include_flags = request
        self.log_message("Creating data export; CTFd tokens are always excluded.")
        try:
            await asyncio.to_thread(
                self._data_store.export_archive,
                destination,
                include_flags=include_flags,
            )
        except DataStoreError as error:
            self.log_error(f"Export failed safely: {error}")
            return
        flags_note = " with flags" if include_flags else " without flags"
        self.log_message(
            f"Export complete: {destination.name or 'archive'}{flags_note}; "
            "CTFd tokens excluded."
        )

    def _log_solver_warning(self, message: str) -> None:
        """Deliver service warnings from its worker thread to the shared log."""
        self.call_from_thread(self.log_message, f"WARNING: {message}")

    async def add_ctf(self, ctf: CTF | None) -> None:
        if ctf is None:
            return
        if self._storage_error is not None:
            self.log_error(f"Cannot save CTF: {self._storage_error}")
            return
        if self._data_store is not None:
            ctf = self._prepare_ctf(ctf)
            try:
                self._data_store.save_ctfs(
                    [
                        *(_ctf_record(existing) for existing in self._ctfs),
                        _ctf_record(ctf),
                    ]
                )
            except DataStoreError as error:
                self._storage_failure(error)
                return
        self._ctfs.append(ctf)
        self._challenges.append([])
        self.log_message(f"Added CTF: {ctf.name}")

        if self._ctfs[:-1]:
            ctf_list = self.query_one("#ctf-list", ListView)
            await ctf_list.append(ListItem(Static(ctf.name, markup=False)))
        else:
            await self.query_one("#ctf-list", Static).remove()
            await self.query_one("#ctf-panel", Vertical).mount(
                self.query_one(CTFSelectionView).make_ctf_list()
            )

        ctf_list = self.query_one("#ctf-list", ListView)
        ctf_list.index = len(self._ctfs) - 1
        ctf_list.focus()
        self.query_one(CTFSelectionView).render_ctf_details(len(self._ctfs) - 1)

    async def update_ctf(self, index: int, ctf: CTF | None) -> None:
        if ctf is None:
            return
        if self._storage_error is not None:
            self.log_error(f"Cannot update CTF: {self._storage_error}")
            return

        original = self._ctfs[index]
        updated = replace(
            ctf,
            id=original.id,
            source=original.source,
            created_at=original.created_at,
            updated_at=utc_timestamp()
            if self._data_store is not None
            else original.updated_at,
        )
        if self._data_store is not None:
            if updated.id is None:
                self._storage_failure(
                    DataStoreError("cannot update a CTF without an ID")
                )
                return
            records = list(self._ctfs)
            records[index] = updated
            try:
                self._data_store.save_ctfs([_ctf_record(record) for record in records])
            except DataStoreError as error:
                self._storage_failure(error)
                return

        self._ctfs[index] = updated
        ctf_list = self.query_one("#ctf-list", ListView)
        ctf_list.children[index].query_one(Static).update(updated.name)
        ctf_list.index = index
        ctf_list.focus()
        self.query_one(CTFSelectionView).render_ctf_details(index)
        self.log_message(f"Updated CTF: {updated.name}")

    async def remove_ctf(self, index: int, confirmed: bool) -> None:
        if not confirmed:
            return
        if self._storage_error is not None:
            self.log_error(f"Cannot remove CTF: {self._storage_error}")
            return

        ctf = self._ctfs[index]
        remaining = self._ctfs[:index] + self._ctfs[index + 1 :]
        retained_directory: Path | None = None
        if self._data_store is not None:
            if ctf.id is None:
                self._storage_failure(
                    DataStoreError("cannot remove a CTF without an ID")
                )
                return
            try:
                retained_directory = self._data_store.delete_ctf(
                    ctf.id,
                    [_ctf_record(record) for record in remaining],
                )
            except DataStoreError as error:
                self._storage_failure(error)
                return

        del self._ctfs[index]
        del self._challenges[index]
        if self._last_ctf_id == ctf.id:
            self._last_ctf_id = None
            if self._data_store is not None:
                try:
                    self._data_store.save_last_ctf_id(None)
                except DataStoreError as error:
                    self.log_error(f"Cannot clear last CTF state: {error}")
        await self.query_one(CTFSelectionView).refresh_ctf_list(index)
        if retained_directory is None:
            self.log_message(f"Removed CTF: {ctf.name}")
        else:
            self.log_message(
                f"Removed CTF: {ctf.name}; data cleanup failed, retained at "
                f"{retained_directory}"
            )

    def log_message(self, message: str, *, level: int | None = None) -> None:
        if level is not None and APP_LOGGER.handlers:
            APP_LOGGER.log(level, message)
        self._log_messages.append(message)
        del self._log_messages[: -self.LOG_HISTORY_LIMIT]
        self._log_message = self._format_log_messages()
        for screen in self.screen_stack:
            try:
                screen.query_one("#log-message", Static).update(self._log_message)
            except NoMatches:
                continue

    def log_error(self, message: str) -> None:
        self.log_message(message, level=logging.ERROR)

    def _format_log_messages(self) -> str:
        return "\n".join(self._log_messages[-self.LOG_HISTORY_LIMIT :])

    def _prepare_ctf(self, ctf: CTF) -> CTF:
        now = utc_timestamp()
        return replace(
            ctf,
            id=ctf.id or generate_id(),
            created_at=ctf.created_at or now,
            updated_at=now,
        )

    def _prepare_challenge(self, challenge: Challenge) -> Challenge:
        now = utc_timestamp()
        return replace(
            challenge,
            id=challenge.id or generate_id(),
            created_at=challenge.created_at or now,
            updated_at=now,
        )

    def _storage_failure(self, error: DataStoreError) -> None:
        self._storage_error = str(error)
        log_debug_exception("Storage operation failed", error)
        self.log_error(f"Storage error: {error}")

    def persist_challenge(
        self,
        ctf: CTF,
        existing: Sequence[Challenge],
        challenge: Challenge,
    ) -> Challenge | None:
        if self._storage_error is not None:
            self.log_error(f"Cannot save challenge: {self._storage_error}")
            return None
        if self._data_store is None:
            return challenge

        challenge = self._prepare_challenge(challenge)
        if ctf.id is None:
            self._storage_failure(
                DataStoreError("cannot save a challenge for a CTF without an ID")
            )
            return None
        try:
            records = list(existing)
            replace_index = next(
                (
                    index
                    for index, item in enumerate(records)
                    if item.id is not None and item.id == challenge.id
                ),
                None,
            )
            if replace_index is None:
                records.append(challenge)
            else:
                records[replace_index] = challenge
            self._data_store.save_challenges(
                ctf.id,
                [_challenge_record(item) for item in records],
            )
        except DataStoreError as error:
            self._storage_failure(error)
            return None
        return challenge

    def action_ctf_down(self) -> None:
        """Move the CTF lightbar down (the ``j`` key)."""
        if self._ctfs:
            self.query_one("#ctf-list", ListView).action_cursor_down()

    def action_ctf_up(self) -> None:
        """Move the CTF lightbar up (the ``k`` key)."""
        if self._ctfs:
            self.query_one("#ctf-list", ListView).action_cursor_up()
