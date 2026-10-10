"""Dialogs for creating and replacing challenge solver templates."""

from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Label, ListItem, ListView, Static

from ctfwb.solvers import SolverTemplate, list_templates


class SelectSolverTemplateDialog(ModalScreen[str | None]):
    """Choose a registered solver template using the keyboard lightbar."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", priority=True),
        Binding("j", "next_template", "Next", show=False),
        Binding("k", "previous_template", "Previous", show=False),
    ]

    CSS = """
    SelectSolverTemplateDialog {
        align: center middle;
        background: #07131c 80%;
    }

    #select-solver-dialog {
        width: 76;
        max-width: 95%;
        height: auto;
        max-height: 90%;
        border: round #71d6bc;
        background: #0b202b;
        padding: 1 2;
    }

    #select-solver-title {
        height: 1;
        color: #71d6bc;
        text-style: bold;
        margin-bottom: 1;
    }

    #solver-template-list {
        height: auto;
        max-height: 12;
        border: none;
        background: transparent;
    }

    #solver-template-list > ListItem {
        height: auto;
        min-height: 2;
        padding: 0 1;
    }

    #solver-template-list > ListItem.--highlight {
        background: #176b66;
        color: #ffffff;
    }

    .solver-template-row {
        height: auto;
        color: #d7e4df;
    }

    #cancel-solver-template {
        width: 1fr;
        height: 1;
        border: none;
        padding: 0 1;
    }
    """

    def __init__(self, templates: tuple[SolverTemplate, ...] | None = None) -> None:
        super().__init__()
        self.templates = templates or list_templates()

    def compose(self) -> ComposeResult:
        with Vertical(id="select-solver-dialog"):
            yield Label("CREATE SOLVER // TEMPLATE", id="select-solver-title")
            yield Static(
                "Select a starter file. Template creation does not execute Bash.",
                markup=False,
            )
            yield ListView(
                *(
                    ListItem(
                        Static(
                            f"{template.display_name}\n  {template.description}",
                            classes="solver-template-row",
                            markup=False,
                        ),
                        id=template.template_id,
                    )
                    for template in self.templates
                ),
                id="solver-template-list",
            )
            yield Button("Cancel", id="cancel-solver-template")

    def on_mount(self) -> None:
        template_list = self.query_one("#solver-template-list", ListView)
        if self.templates:
            template_list.index = 0
            template_list.focus()

    @on(ListView.Selected, "#solver-template-list")
    def select_template(self, event: ListView.Selected) -> None:
        template_id = event.item.id
        if template_id:
            self.dismiss(template_id)

    @on(Button.Pressed, "#cancel-solver-template")
    def cancel_button(self) -> None:
        self.dismiss(None)

    def action_next_template(self) -> None:
        self.query_one("#solver-template-list", ListView).action_cursor_down()

    def action_previous_template(self) -> None:
        self.query_one("#solver-template-list", ListView).action_cursor_up()

    def action_cancel(self) -> None:
        self.dismiss(None)


class ConfirmOverwriteSolverDialog(ModalScreen[bool]):
    """Require an explicit choice before replacing an existing solver file."""

    BINDINGS = [Binding("escape", "cancel", "Cancel", priority=True)]

    CSS = """
    ConfirmOverwriteSolverDialog {
        align: center middle;
        background: #07131c 80%;
    }

    #overwrite-solver-dialog {
        width: 68;
        max-width: 95%;
        height: auto;
        border: round #e7c66a;
        background: #0b202b;
        padding: 1 2;
    }

    #overwrite-solver-title {
        height: 1;
        color: #e7c66a;
        text-style: bold;
        margin-bottom: 1;
    }

    #overwrite-solver-message {
        height: auto;
        margin-bottom: 1;
    }

    #overwrite-solver-actions {
        height: auto;
        align-horizontal: right;
    }

    #cancel-overwrite-solver, #confirm-overwrite-solver {
        height: 1;
        border: none;
        padding: 0 1;
    }
    """

    def __init__(self, challenge_name: str, relative_path: str) -> None:
        super().__init__()
        self.challenge_name = challenge_name
        self.relative_path = relative_path

    def compose(self) -> ComposeResult:
        with Vertical(id="overwrite-solver-dialog"):
            yield Label(
                "SOLVER EXISTS // CONFIRM REPLACEMENT", id="overwrite-solver-title"
            )
            yield Static(
                f"[{self.challenge_name}] {self.relative_path} already exists. "
                "Replace its contents?",
                id="overwrite-solver-message",
                markup=False,
            )
            with Vertical(id="overwrite-solver-actions"):
                yield Button("Keep Existing", id="cancel-overwrite-solver")
                yield Button(
                    "Replace Solver",
                    id="confirm-overwrite-solver",
                    variant="warning",
                )

    @on(Button.Pressed)
    def handle_button(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm-overwrite-solver":
            self.dismiss(True)
        elif event.button.id == "cancel-overwrite-solver":
            self.dismiss(False)

    def action_cancel(self) -> None:
        self.dismiss(False)


class SolverOutputDialog(ModalScreen[None]):
    """Show separate solver streams in a scrollable output window."""

    BINDINGS = [
        Binding("escape", "close", "Close", priority=True),
        Binding("up", "scroll_up", "Scroll Up", show=False),
        Binding("down", "scroll_down", "Scroll Down", show=False),
        Binding("k", "scroll_up", "Scroll Up", show=False),
        Binding("j", "scroll_down", "Scroll Down", show=False),
        Binding("ctrl+u", "page_up", "Page Up", show=False),
        Binding("ctrl+d", "page_down", "Page Down", show=False),
    ]

    CSS = """
    SolverOutputDialog {
        align: center middle;
        background: #07131c 80%;
    }

    #solver-output-dialog {
        width: 90%;
        max-width: 95%;
        height: 90%;
        max-height: 90%;
        border: round #397a78;
        background: #0b202b;
        padding: 1 2;
    }

    #solver-output-title {
        height: auto;
        color: #71d6bc;
        text-style: bold;
        margin-bottom: 1;
    }

    #solver-output-status {
        height: auto;
        color: #9cb8b2;
        margin-bottom: 1;
    }

    #solver-output-hint {
        height: 1;
        color: #9cb8b2;
    }

    #solver-output-scroll {
        height: 1fr;
        scrollbar-gutter: stable;
        color: #d7e4df;
        border: round #397a78;
        padding: 0 1;
    }

    #solver-output-scroll:focus {
        border: round #56a9a3;
        background: #102934;
    }

    .solver-output-heading {
        height: 1;
        color: #71d6bc;
        text-style: bold;
        margin-top: 1;
    }

    .solver-output-stderr-heading,
    #solver-output-stderr {
        color: #ff7777;
    }

    .solver-output-content {
        height: auto;
        width: 1fr;
    }

    #solver-output-actions {
        height: auto;
        align-horizontal: right;
        margin-top: 1;
    }

    #close-solver-output {
        width: 16;
        height: 1;
        border: none;
        padding: 0 1;
    }

    #close-solver-output:focus {
        background: #176b66;
        color: #ffffff;
        text-style: bold;
    }
    """

    def __init__(
        self,
        challenge_name: str,
        outcome: str,
        returncode: int | None,
        stdout: str,
        stderr: str,
        error: str | None = None,
    ) -> None:
        super().__init__()
        self.challenge_name = challenge_name
        self.outcome = outcome
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.error = error

    def compose(self) -> ComposeResult:
        return_label = (
            f" // EXIT {self.returncode}" if self.returncode is not None else ""
        )
        with Vertical(id="solver-output-dialog"):
            yield Label(
                f"SOLVER OUTPUT // {self.challenge_name}",
                id="solver-output-title",
            )
            yield Static(
                f"Outcome: {self.outcome}{return_label}",
                id="solver-output-status",
                markup=False,
            )
            yield Static(
                "OUTPUT // TAB TO FOCUS AND SCROLL WITH ARROWS / J-K / CTRL-D-U",
                id="solver-output-hint",
                markup=False,
            )
            with VerticalScroll(id="solver-output-scroll"):
                yield Label("STDOUT", classes="solver-output-heading")
                yield Static(
                    self.stdout or "(no output)",
                    id="solver-output-stdout",
                    classes="solver-output-content",
                    markup=False,
                )
                yield Label(
                    "STDERR",
                    classes="solver-output-heading solver-output-stderr-heading",
                )
                yield Static(
                    self.stderr or self.error or "(no output)",
                    id="solver-output-stderr",
                    classes="solver-output-content",
                    markup=False,
                )
            with Horizontal(id="solver-output-actions"):
                yield Button("CLOSE", id="close-solver-output")

    def on_mount(self) -> None:
        self.query_one("#close-solver-output", Button).focus()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action in {
            "scroll_up",
            "scroll_down",
            "page_up",
            "page_down",
        }:
            return self.query_one("#solver-output-scroll", VerticalScroll).has_focus
        return super().check_action(action, parameters)

    def action_scroll_up(self) -> None:
        self.query_one("#solver-output-scroll", VerticalScroll).scroll_relative(
            y=-1, animate=False
        )

    def action_scroll_down(self) -> None:
        self.query_one("#solver-output-scroll", VerticalScroll).scroll_relative(
            y=1, animate=False
        )

    def action_page_up(self) -> None:
        self.query_one("#solver-output-scroll", VerticalScroll).scroll_page_up(
            animate=False
        )

    def action_page_down(self) -> None:
        self.query_one("#solver-output-scroll", VerticalScroll).scroll_page_down(
            animate=False
        )

    @on(Button.Pressed, "#close-solver-output")
    def close_button(self) -> None:
        self.dismiss()

    def action_close(self) -> None:
        self.dismiss()
