"""Modal dialogs for imports, CTF management, and challenge actions."""

from __future__ import annotations

import json
from dataclasses import replace

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Input,
    Label,
    ListItem,
    ListView,
    Static,
    TextArea,
)

from ctfwb.ui.models import Challenge


class AddChallengeDialog(ModalScreen[Challenge | None]):
    """Collect the details for a manually-created challenge."""

    BINDINGS = [Binding("escape", "cancel", "Cancel", priority=True)]

    CSS = """
    AddChallengeDialog {
        align: center middle;
        background: #07131c 80%;
    }

    #add-challenge-dialog {
        width: 80;
        max-width: 95%;
        height: auto;
        max-height: 90%;
        border: round #71d6bc;
        background: #0b202b;
        padding: 1 2;
    }

    #challenge-dialog-title {
        height: 1;
        color: #71d6bc;
        text-style: bold;
        margin-bottom: 1;
    }

    .field-label {
        width: 20;
        height: auto;
        color: #9cb8b2;
        content-align: left middle;
    }

    #challenge-name, #challenge-category, #challenge-points {
        width: 1fr;
        height: 1;
        border: none;
        padding: 0 1;
    }

    #challenge-description {
        width: 1fr;
        height: 3;
        border: round #397a78;
    }

    #challenge-name-row, #challenge-category-row, #challenge-points-row,
    #challenge-description-row, #challenge-dialog-actions {
        height: auto;
        margin-top: 0;
        align-horizontal: right;
    }

    #cancel-challenge, #confirm-challenge {
        height: 1;
        border: none;
        padding: 0 1;
    }

    #challenge-dialog-error {
        height: auto;
        min-height: 1;
        color: #ff9c83;
        margin-top: 1;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="add-challenge-dialog"):
            yield Label("ADD CHALLENGE", id="challenge-dialog-title")
            with Horizontal(id="challenge-name-row"):
                yield Label("Name *", classes="field-label")
                yield Input(placeholder="Challenge name", id="challenge-name")
            with Horizontal(id="challenge-category-row"):
                yield Label("Category", classes="field-label")
                yield Input(placeholder="e.g. web, crypto", id="challenge-category")
            with Horizontal(id="challenge-points-row"):
                yield Label("Points", classes="field-label")
                yield Input(placeholder="Optional", id="challenge-points")
            with Horizontal(id="challenge-description-row"):
                yield Label("Description", classes="field-label")
                yield TextArea("", id="challenge-description")
            yield Static("", id="challenge-dialog-error", markup=False)
            with Horizontal(id="challenge-dialog-actions"):
                yield Button("Cancel", id="cancel-challenge")
                yield Button(
                    "Add Challenge",
                    id="confirm-challenge",
                    variant="primary",
                )

    @on(Button.Pressed)
    def handle_button(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm-challenge":
            self.confirm_add()
        elif event.button.id == "cancel-challenge":
            self.dismiss(None)

    def confirm_add(self) -> None:
        name = self.query_one("#challenge-name", Input).value.strip()
        if not name:
            self.report_error("Name is required.")
            self.query_one("#challenge-name", Input).focus()
            return

        points_text = self.query_one("#challenge-points", Input).value.strip()
        points: int | None = None
        if points_text:
            try:
                points = int(points_text)
            except ValueError:
                self.report_error("Points must be a whole number.")
                self.query_one("#challenge-points", Input).focus()
                return

        category = self.query_one("#challenge-category", Input).value.strip() or None
        description = self.query_one("#challenge-description", TextArea).text
        self.dismiss(Challenge(name, category, points, description))

    def report_error(self, message: str) -> None:
        self.query_one("#challenge-dialog-error", Static).update(message)
        self.app.log_error(message)

    def action_cancel(self) -> None:
        self.dismiss(None)


class EditChallengeDialog(ModalScreen[Challenge | None]):
    """Edit challenge metadata without changing its identity or timestamps."""

    BINDINGS = [Binding("escape", "cancel", "Cancel", priority=True)]

    CSS = """
    EditChallengeDialog {
        align: center middle;
        background: #07131c 80%;
    }

    #edit-challenge-dialog {
        width: 88;
        max-width: 96%;
        height: auto;
        max-height: 96%;
        border: round #71d6bc;
        background: #0b202b;
        padding: 1 2;
    }

    #edit-challenge-title {
        height: 1;
        color: #71d6bc;
        text-style: bold;
        margin-bottom: 1;
    }

    .field-label {
        width: 18;
        height: auto;
        color: #9cb8b2;
        content-align: left middle;
    }

    #edit-challenge-name, #edit-challenge-category, #edit-challenge-points,
    #edit-challenge-status, #edit-challenge-flag {
        width: 1fr;
        height: 1;
        border: none;
        padding: 0 1;
    }

    #edit-challenge-description, #edit-challenge-artifacts {
        width: 1fr;
        height: 3;
        border: round #397a78;
    }

    #edit-challenge-name-row, #edit-challenge-category-row,
    #edit-challenge-points-row, #edit-challenge-status-row,
    #edit-challenge-flag-row, #edit-challenge-description-row,
    #edit-challenge-artifacts-row, #edit-challenge-actions {
        height: auto;
        margin-top: 0;
        align-horizontal: right;
    }

    #edit-challenge-error {
        height: auto;
        min-height: 1;
        color: #ff9c83;
        margin-top: 1;
    }

    #cancel-edit-challenge, #confirm-edit-challenge {
        height: 1;
        border: none;
        padding: 0 1;
    }
    """

    STATUSES = ("unsolved", "in_progress", "solved", "skipped")

    def __init__(self, challenge: Challenge) -> None:
        super().__init__()
        self.challenge = challenge

    def compose(self) -> ComposeResult:
        challenge = self.challenge
        with Vertical(id="edit-challenge-dialog"):
            yield Label("EDIT CHALLENGE // METADATA", id="edit-challenge-title")
            with Horizontal(id="edit-challenge-name-row"):
                yield Label("Name *", classes="field-label")
                yield Input(value=challenge.name, id="edit-challenge-name")
            with Horizontal(id="edit-challenge-category-row"):
                yield Label("Category", classes="field-label")
                yield Input(
                    value=challenge.category or "", id="edit-challenge-category"
                )
            with Horizontal(id="edit-challenge-points-row"):
                yield Label("Points", classes="field-label")
                yield Input(
                    value="" if challenge.points is None else str(challenge.points),
                    id="edit-challenge-points",
                )
            with Horizontal(id="edit-challenge-status-row"):
                yield Label("Status", classes="field-label")
                yield Input(value=challenge.status, id="edit-challenge-status")
            with Horizontal(id="edit-challenge-flag-row"):
                yield Label("Flag", classes="field-label")
                yield Input(
                    value=challenge.flag or "",
                    id="edit-challenge-flag",
                )
            with Horizontal(id="edit-challenge-description-row"):
                yield Label("Description", classes="field-label")
                yield TextArea(
                    challenge.description,
                    id="edit-challenge-description",
                )
            with Horizontal(id="edit-challenge-artifacts-row"):
                yield Label("Artifacts (JSON list)", classes="field-label")
                yield TextArea(
                    json.dumps(
                        [dict(artifact) for artifact in challenge.artifacts],
                        indent=2,
                        ensure_ascii=False,
                    ),
                    id="edit-challenge-artifacts",
                )
            yield Static("", id="edit-challenge-error", markup=False)
            with Horizontal(id="edit-challenge-actions"):
                yield Button("Cancel", id="cancel-edit-challenge")
                yield Button(
                    "Save Changes",
                    id="confirm-edit-challenge",
                    variant="primary",
                )

    @on(Button.Pressed)
    def handle_button(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm-edit-challenge":
            self.confirm_edit()
        elif event.button.id == "cancel-edit-challenge":
            self.dismiss(None)

    def confirm_edit(self) -> None:
        challenge = self.challenge
        name = self.query_one("#edit-challenge-name", Input).value.strip()
        if not name:
            self.report_error("Name is required.")
            self.query_one("#edit-challenge-name", Input).focus()
            return

        points_text = self.query_one("#edit-challenge-points", Input).value.strip()
        points: int | None = None
        if points_text:
            try:
                points = int(points_text)
            except ValueError:
                self.report_error("Points must be a whole number.")
                self.query_one("#edit-challenge-points", Input).focus()
                return

        status = self.query_one("#edit-challenge-status", Input).value.strip()
        if status not in self.STATUSES:
            self.report_error(
                "Status must be one of: unsolved, in_progress, solved, skipped."
            )
            self.query_one("#edit-challenge-status", Input).focus()
            return

        artifacts_text = self.query_one("#edit-challenge-artifacts", TextArea).text
        try:
            artifacts_data = json.loads(artifacts_text or "[]")
        except json.JSONDecodeError as error:
            self.report_error(f"Artifacts must be valid JSON: {error.msg}.")
            self.query_one("#edit-challenge-artifacts", TextArea).focus()
            return
        if not isinstance(artifacts_data, list) or any(
            not isinstance(artifact, dict) for artifact in artifacts_data
        ):
            self.report_error("Artifacts must be a JSON list of metadata objects.")
            self.query_one("#edit-challenge-artifacts", TextArea).focus()
            return

        flag = self.query_one("#edit-challenge-flag", Input).value.strip() or None
        updated = replace(
            challenge,
            name=name,
            category=(
                self.query_one("#edit-challenge-category", Input).value.strip() or None
            ),
            points=points,
            description=self.query_one("#edit-challenge-description", TextArea).text,
            artifacts=tuple(artifacts_data),
            status=status,
            flag=flag,
        )
        self.dismiss(updated)

    def report_error(self, message: str) -> None:
        self.query_one("#edit-challenge-error", Static).update(message)
        self.app.log_error(message)

    def action_cancel(self) -> None:
        self.dismiss(None)


class ConfirmDeleteChallengeDialog(ModalScreen[bool]):
    """Require confirmation before removing a challenge and its saved files."""

    BINDINGS = [Binding("escape", "cancel", "Cancel", priority=True)]

    CSS = """
    ConfirmDeleteChallengeDialog {
        align: center middle;
        background: #07131c 80%;
    }

    #confirm-delete-challenge-dialog {
        width: 72;
        max-width: 95%;
        height: auto;
        border: round #ff9c83;
        background: #0b202b;
        padding: 1 2;
    }

    #delete-challenge-title {
        height: 1;
        color: #ff9c83;
        text-style: bold;
        margin-bottom: 1;
    }

    #delete-challenge-message {
        height: auto;
        margin-bottom: 1;
    }

    #delete-challenge-actions {
        height: auto;
        align-horizontal: right;
    }

    #cancel-delete-challenge, #confirm-delete-challenge {
        height: 1;
        border: none;
        padding: 0 1;
    }
    """

    def __init__(self, challenge: Challenge) -> None:
        super().__init__()
        self.challenge = challenge

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-delete-challenge-dialog"):
            yield Label("REMOVE CHALLENGE // CONFIRM", id="delete-challenge-title")
            yield Static(
                f"Remove {self.challenge.name!r} and its saved solver/artifact files?",
                id="delete-challenge-message",
                markup=False,
            )
            with Horizontal(id="delete-challenge-actions"):
                yield Button("Cancel", id="cancel-delete-challenge")
                yield Button(
                    "Remove Challenge",
                    id="confirm-delete-challenge",
                    variant="error",
                )

    @on(Button.Pressed)
    def handle_button(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm-delete-challenge":
            self.dismiss(True)
        elif event.button.id == "cancel-delete-challenge":
            self.dismiss(False)

    def action_cancel(self) -> None:
        self.dismiss(False)


class SelectChallengeStatusDialog(ModalScreen[str | None]):
    """Choose a new status for a challenge."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", priority=True),
        Binding("tab", "next_status", show=False, priority=True),
        Binding("shift+tab", "previous_status", show=False, priority=True),
        Binding("j", "next_status", show=False, priority=True),
        Binding("down", "next_status", show=False, priority=True),
        Binding("k", "previous_status", show=False, priority=True),
        Binding("up", "previous_status", show=False, priority=True),
    ]

    CSS = """
    SelectChallengeStatusDialog {
        align: center middle;
        background: #07131c 80%;
    }

    #select-challenge-status-dialog {
        width: 56;
        max-width: 95%;
        height: auto;
        border: round #71d6bc;
        background: #0b202b;
        padding: 1 2;
    }

    #select-challenge-status-title {
        height: 1;
        color: #71d6bc;
        text-style: bold;
        margin-bottom: 1;
    }

    #select-challenge-status-current {
        height: 1;
        color: #9cb8b2;
        margin-bottom: 1;
    }

    #select-challenge-status-options {
        height: auto;
        border: none;
        background: transparent;
    }

    #select-challenge-status-options > ListItem {
        height: 1;
        padding: 0 1;
        color: #d7e4df;
    }

    #select-challenge-status-options > ListItem.--highlight {
        background: #176b66;
        color: #ffffff;
        text-style: bold;
    }
    """

    STATUS_BUTTONS = {
        "status-unsolved": "unsolved",
        "status-in-progress": "in_progress",
        "status-solved": "solved",
        "status-skipped": "skipped",
    }

    def __init__(self, current_status: str) -> None:
        super().__init__()
        self.current_status = current_status

    def compose(self) -> ComposeResult:
        with Vertical(id="select-challenge-status-dialog"):
            yield Label("SET CHALLENGE STATUS", id="select-challenge-status-title")
            yield Static(
                f"Current status: {self.current_status}",
                id="select-challenge-status-current",
                markup=False,
            )
            yield ListView(
                *(
                    ListItem(
                        Static(status.replace("_", " ").title(), markup=False),
                        id=button_id,
                    )
                    for button_id, status in self.STATUS_BUTTONS.items()
                ),
                ListItem(
                    Static("Cancel", markup=False),
                    id="cancel-select-challenge-status",
                ),
                id="select-challenge-status-options",
            )

    def on_mount(self) -> None:
        options = self.query_one("#select-challenge-status-options", ListView)
        options.index = next(
            index
            for index, status in enumerate(self.STATUS_BUTTONS.values())
            if status == self.current_status
        )
        options.focus()

    @on(ListView.Selected, "#select-challenge-status-options")
    def select_status(self, event: ListView.Selected) -> None:
        self.dismiss(self.STATUS_BUTTONS.get(event.item.id or ""))

    def action_next_status(self) -> None:
        self.query_one(
            "#select-challenge-status-options", ListView
        ).action_cursor_down()

    def action_previous_status(self) -> None:
        self.query_one("#select-challenge-status-options", ListView).action_cursor_up()

    def action_cancel(self) -> None:
        self.dismiss(None)


class EditFlagDialog(ModalScreen[tuple[str, str] | None]):
    """Edit or clear a challenge flag."""

    BINDINGS = [Binding("escape", "cancel", "Cancel", priority=True)]

    CSS = """
    EditFlagDialog {
        align: center middle;
        background: #07131c 80%;
    }

    #edit-flag-dialog {
        width: 68;
        max-width: 95%;
        height: auto;
        border: round #71d6bc;
        background: #0b202b;
        padding: 1 2;
    }

    #edit-flag-title {
        height: 1;
        color: #71d6bc;
        text-style: bold;
        margin-bottom: 1;
    }

    #edit-flag-input {
        width: 1fr;
        height: 1;
        border: none;
        padding: 0 1;
    }

    #edit-flag-actions {
        height: auto;
        margin-top: 1;
        align-horizontal: right;
    }

    #cancel-edit-flag, #save-flag, #save-and-submit-flag {
        height: 1;
        border: none;
        padding: 0 1;
    }
    """

    def __init__(self, challenge: Challenge, *, can_submit: bool = False) -> None:
        super().__init__()
        self.challenge = challenge
        self.can_submit = can_submit

    def compose(self) -> ComposeResult:
        with Vertical(id="edit-flag-dialog"):
            yield Label(
                f"FLAG // {self.challenge.name}",
                id="edit-flag-title",
            )
            yield Input(
                value=self.challenge.flag or "",
                placeholder="Flag value",
                id="edit-flag-input",
            )
            with Horizontal(id="edit-flag-actions"):
                yield Button("Cancel", id="cancel-edit-flag")
                if self.can_submit:
                    yield Button("Save", id="save-flag")
                    yield Button(
                        "Save and submit",
                        id="save-and-submit-flag",
                        variant="primary",
                    )
                else:
                    yield Button(
                        "Save",
                        id="save-flag",
                        variant="primary",
                    )

    @on(Input.Submitted, "#edit-flag-input")
    def handle_input_submitted(self, event: Input.Submitted) -> None:
        self.save_flag("submit" if self.can_submit else "save")

    @on(Button.Pressed)
    def handle_button(self, event: Button.Pressed) -> None:
        if event.button.id == "save-flag":
            self.save_flag("save")
        elif event.button.id == "save-and-submit-flag":
            self.save_flag("submit")
        elif event.button.id == "cancel-edit-flag":
            self.dismiss(None)

    def save_flag(self, action: str) -> None:
        flag = self.query_one("#edit-flag-input", Input).value.strip()
        self.dismiss((action, flag))

    def action_cancel(self) -> None:
        self.dismiss(None)


class OpenArtifactsDirectoryDialog(ModalScreen[str | None]):
    """Choose how to open a challenge's artifacts directory."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", priority=True),
        Binding("tab", "next_option", show=False, priority=True),
        Binding("shift+tab", "previous_option", show=False, priority=True),
        Binding("j", "next_option", show=False, priority=True),
        Binding("k", "previous_option", show=False, priority=True),
    ]

    CSS = """
    OpenArtifactsDirectoryDialog {
        align: center middle;
        background: #07131c 80%;
    }

    #open-artifacts-dialog {
        width: 60;
        max-width: 95%;
        height: auto;
        border: round #71d6bc;
        background: #0b202b;
        padding: 1 2;
    }

    #open-artifacts-title {
        height: 1;
        color: #71d6bc;
        text-style: bold;
        margin-bottom: 1;
    }

    #open-artifacts-options {
        height: auto;
        border: none;
        background: transparent;
    }

    #open-artifacts-options > ListItem {
        height: 1;
        padding: 0 1;
        color: #d7e4df;
    }

    #open-artifacts-options > ListItem.--highlight {
        background: #176b66;
        color: #ffffff;
        text-style: bold;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="open-artifacts-dialog"):
            yield Label("OPEN ARTIFACTS DIRECTORY", id="open-artifacts-title")
            yield ListView(
                ListItem(Static("Open path in terminal", markup=False)),
                ListItem(Static("Open in file explorer", markup=False)),
                ListItem(Static("Cancel", markup=False)),
                id="open-artifacts-options",
            )

    def on_mount(self) -> None:
        options = self.query_one("#open-artifacts-options", ListView)
        options.index = 0
        options.focus()

    @on(ListView.Selected, "#open-artifacts-options")
    def select_option(self, event: ListView.Selected) -> None:
        choices = ("terminal", "explorer", None)
        index = event.list_view.index
        if index is not None and 0 <= index < len(choices):
            self.dismiss(choices[index])

    def action_next_option(self) -> None:
        self._move_option(1)

    def action_previous_option(self) -> None:
        self._move_option(-1)

    def _move_option(self, amount: int) -> None:
        options = self.query_one("#open-artifacts-options", ListView)
        if options.children:
            index = options.index or 0
            options.index = (index + amount) % len(options.children)

    def action_cancel(self) -> None:
        self.dismiss(None)
