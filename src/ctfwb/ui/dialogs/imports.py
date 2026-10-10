"""Modal dialogs for imports, CTF management, and challenge actions."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Mapping, Sequence

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Input,
    Label,
    Static,
    TextArea,
)

from ctfwb.importers import (
    CTFdError,
    ImportErrorBase,
    ImportPlan,
    RefreshPlan,
    validate_challenge_json,
)
from ctfwb.logging_setup import (
    log_debug_exception,
)
from ctfwb.storage import (
    DataStore,
    DataStoreError,
    normalize_ctfd_base_url,
)
from ctfwb.ui.models import CTF


@dataclass(frozen=True)
class CTFdImportResult:
    base_url: str
    challenges: tuple[dict[str, object], ...]


class ImportSourceDialog(ModalScreen[str | None]):
    """Choose between importing a CTFd JSON file and a live CTFd instance."""

    BINDINGS = [Binding("escape", "cancel", "Cancel", priority=True)]

    CSS = """
    ImportSourceDialog {
        align: center middle;
        background: #07131c 80%;
    }

    #import-source-dialog {
        width: 58;
        height: auto;
        border: round #71d6bc;
        background: #0b202b;
        padding: 1 2;
    }

    #import-source-title {
        height: 1;
        color: #71d6bc;
        text-style: bold;
        margin-bottom: 1;
    }

    #import-source-actions {
        height: auto;
        align-horizontal: right;
    }

    #import-json-source, #import-ctfd-source, #cancel-import-source {
        height: 1;
        border: none;
        padding: 0 1;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="import-source-dialog"):
            yield Label("IMPORT CHALLENGES", id="import-source-title")
            yield Static(
                "Paste CTFd JSON or fetch challenges from a live CTFd API.",
                markup=False,
            )
            with Horizontal(id="import-source-actions"):
                yield Button("Paste JSON", id="import-json-source")
                yield Button("CTFd API", id="import-ctfd-source")
                yield Button("Cancel", id="cancel-import-source")

    @on(Button.Pressed)
    def handle_button(self, event: Button.Pressed) -> None:
        if event.button.id == "import-json-source":
            self.dismiss("json")
        elif event.button.id == "import-ctfd-source":
            self.dismiss("ctfd")
        elif event.button.id == "cancel-import-source":
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class RefreshSourceDialog(ModalScreen[str | None]):
    """Choose a source when a CTF has multiple refreshable imports."""

    BINDINGS = [Binding("escape", "cancel", "Cancel", priority=True)]

    CSS = """
    RefreshSourceDialog {
        align: center middle;
        background: #07131c 80%;
    }

    #refresh-source-dialog {
        width: 58;
        height: auto;
        border: round #71d6bc;
        background: #0b202b;
        padding: 1 2;
    }

    #refresh-source-title {
        height: 1;
        color: #71d6bc;
        text-style: bold;
        margin-bottom: 1;
    }

    #refresh-source-actions {
        height: auto;
        align-horizontal: right;
    }
    """

    def __init__(self, sources: Sequence[str]) -> None:
        super().__init__()
        self.sources = tuple(sources)

    def compose(self) -> ComposeResult:
        with Vertical(id="refresh-source-dialog"):
            yield Label("REFRESH CHALLENGES", id="refresh-source-title")
            yield Static(
                "Choose which imported challenge source to refresh.",
                markup=False,
            )
            with Horizontal(id="refresh-source-actions"):
                if "ctfd" in self.sources:
                    yield Button("Live CTFd", id="refresh-ctfd-source")
                if "json_import" in self.sources:
                    yield Button("Paste JSON", id="refresh-json-source")
                yield Button("Cancel", id="cancel-refresh-source")

    @on(Button.Pressed)
    def handle_button(self, event: Button.Pressed) -> None:
        if event.button.id == "refresh-ctfd-source":
            self.dismiss("ctfd")
        elif event.button.id == "refresh-json-source":
            self.dismiss("json_import")
        elif event.button.id == "cancel-refresh-source":
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class ImportJSONDialog(ModalScreen[list[dict[str, object]] | None]):
    """Validate pasted CTFd JSON response or export data."""

    BINDINGS = [Binding("escape", "cancel", "Cancel", priority=True)]

    def __init__(self, *, purpose: str = "import") -> None:
        super().__init__()
        self.purpose = purpose

    CSS = """
    ImportJSONDialog {
        align: center middle;
        background: #07131c 80%;
    }

    #import-json-dialog {
        width: 78;
        max-width: 95%;
        height: auto;
        max-height: 80%;
        border: round #71d6bc;
        background: #0b202b;
        padding: 1 2;
    }

    #import-json-title {
        height: 1;
        color: #71d6bc;
        text-style: bold;
        margin-bottom: 1;
    }

    #import-json-text {
        width: 1fr;
        height: 6;
    }

    #import-json-actions {
        height: auto;
        align-horizontal: right;
    }

    #import-json-error {
        height: auto;
        min-height: 1;
        color: #ff9c83;
        margin-top: 1;
    }

    #load-import-json, #cancel-import-json {
        height: 1;
        border: none;
        padding: 0 1;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="import-json-dialog"):
            title = (
                "REFRESH FROM CTFD JSON"
                if self.purpose == "refresh"
                else "IMPORT CTFD JSON"
            )
            yield Label(title, id="import-json-title")
            yield Static(
                "Paste a CTFd challenge array, API response, or export object."
                + (
                    " Refresh requires a stable ID for every challenge."
                    if self.purpose == "refresh"
                    else ""
                ),
                markup=False,
            )
            yield TextArea(id="import-json-text")
            yield Static("", id="import-json-error", markup=False)
            with Horizontal(id="import-json-actions"):
                yield Button("Cancel", id="cancel-import-json")
                yield Button("Validate JSON", id="load-import-json", variant="primary")

    @on(Button.Pressed)
    def handle_button(self, event: Button.Pressed) -> None:
        if event.button.id == "load-import-json":
            self.load_json()
        elif event.button.id == "cancel-import-json":
            self.dismiss(None)

    def load_json(self) -> None:
        content = self.query_one("#import-json-text", TextArea).text.strip()
        if not content:
            self.report_error("Paste a JSON object or challenge array to import.")
            return
        try:
            challenges = validate_challenge_json(content)
        except ImportErrorBase as error:
            self.report_error(str(error))
            return
        self.dismiss(challenges)

    def report_error(self, message: str) -> None:
        self.query_one("#import-json-error", Static).update(message)
        self.app.log_error(f"JSON import: {message}")

    def action_cancel(self) -> None:
        self.dismiss(None)


class CTFdImportDialog(ModalScreen[CTFdImportResult | None]):
    """Fetch CTFd challenges using credentials scoped to the configured URL."""

    BINDINGS = [Binding("escape", "cancel", "Cancel", priority=True)]

    CSS = """
    CTFdImportDialog {
        align: center middle;
        background: #07131c 80%;
    }

    #ctfd-import-dialog {
        width: 78;
        max-width: 95%;
        height: auto;
        max-height: 85%;
        border: round #71d6bc;
        background: #0b202b;
        padding: 1 2;
    }

    #ctfd-import-title {
        height: 1;
        color: #71d6bc;
        text-style: bold;
        margin-bottom: 1;
    }

    #ctfd-import-url, #ctfd-import-token {
        width: 1fr;
        height: 1;
        border: none;
        padding: 0 1;
    }

    #ctfd-import-actions {
        height: auto;
        align-horizontal: right;
    }

    #ctfd-import-error {
        height: auto;
        min-height: 1;
        color: #ff9c83;
        margin-top: 1;
    }

    #fetch-ctfd-challenges, #cancel-ctfd-import {
        height: 1;
        border: none;
        padding: 0 1;
    }
    """

    def __init__(self, ctf: CTF, data_store: DataStore | None) -> None:
        super().__init__()
        self.ctf = ctf
        self.data_store = data_store
        self._fetching = False
        self._cancelled = False
        self._fetch_task: asyncio.Task[None] | None = None
        self._prefilled_token: str | None = None
        self._prefilled_token_url: str | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="ctfd-import-dialog"):
            yield Label("IMPORT FROM CTFD API V1", id="ctfd-import-title")
            yield Input(
                value=self.ctf.platform_url or "",
                placeholder="https://ctfd.example",
                id="ctfd-import-url",
            )
            yield Input(
                placeholder="CTFd API token",
                password=True,
                id="ctfd-import-token",
            )
            yield Static("", id="ctfd-import-error", markup=False)
            with Horizontal(id="ctfd-import-actions"):
                yield Button("Cancel", id="cancel-ctfd-import")
                yield Button(
                    "Fetch Challenges",
                    id="fetch-ctfd-challenges",
                    variant="primary",
                )

    def on_mount(self) -> None:
        if (
            self.data_store is None
            or self.ctf.id is None
            or self.ctf.platform_url is None
        ):
            return
        try:
            token = self._load_saved_token(self.ctf.platform_url)
        except DataStoreError:
            return
        if token:
            self._prefilled_token = token
            self._prefilled_token_url = normalize_ctfd_base_url(self.ctf.platform_url)
            self.query_one("#ctfd-import-token", Input).value = token

    @on(Input.Changed, "#ctfd-import-url")
    def clear_token_for_different_url(self, event: Input.Changed) -> None:
        if (
            self._prefilled_token is None
            or normalize_ctfd_base_url(event.value) == self._prefilled_token_url
        ):
            return
        token_input = self.query_one("#ctfd-import-token", Input)
        if token_input.value == self._prefilled_token:
            token_input.value = ""
        self._prefilled_token = None
        self._prefilled_token_url = None

    @on(Button.Pressed)
    def handle_button(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel-ctfd-import":
            self.cancel_fetch()
        elif event.button.id == "fetch-ctfd-challenges":
            self.start_fetch()

    def start_fetch(self) -> None:
        if self._fetching:
            return
        base_url = self.query_one("#ctfd-import-url", Input).value.strip()
        token = self.query_one("#ctfd-import-token", Input).value.strip()
        if not base_url:
            self.report_error("A CTFd HTTPS base URL is required.")
            return
        if not token and self.data_store is not None:
            if self.ctf.id is None:
                self.report_error(
                    "Cannot load saved credentials for a CTF without an ID."
                )
                return
            try:
                token = self._load_saved_token(base_url) or ""
            except DataStoreError:
                return
        if not token:
            self.report_error(
                "Enter a token or configure one for this exact HTTPS URL."
            )
            return

        self._fetching = True
        button = self.query_one("#fetch-ctfd-challenges", Button)
        button.disabled = True
        self.query_one("#ctfd-import-error", Static).update(
            "Fetching CTFd challenge pages..."
        )
        self.app.log_message("Fetching challenges from configured CTFd host.")
        self._fetch_task = asyncio.create_task(self.fetch_challenges(base_url, token))

    def _load_saved_token(self, base_url: str) -> str | None:
        if self.data_store is None or self.ctf.id is None:
            return None
        try:
            return self.data_store.load_ctfd_token(self.ctf.id, base_url)
        except DataStoreError as error:
            self.report_error(f"Cannot load saved CTFd credentials: {error}")
            raise

    async def fetch_challenges(self, base_url: str, token: str) -> None:
        try:
            from ctfwb.ui import dialogs

            challenges = await asyncio.to_thread(
                dialogs.fetch_ctfd_challenges,
                base_url,
                token,
            )
            if self._cancelled:
                return
            if self.data_store is not None:
                if self.ctf.id is None:
                    raise DataStoreError(
                        "cannot save CTFd credentials for a CTF without an ID"
                    )
                self.data_store.save_ctfd_token(self.ctf.id, base_url, token)
            if self._cancelled:
                return
        except (CTFdError, DataStoreError) as error:
            log_debug_exception("CTFd import failed", error)
            self.report_error(str(error))
        else:
            self.dismiss(CTFdImportResult(base_url, tuple(challenges)))
        finally:
            self._fetching = False
            if self.is_mounted:
                self.query_one("#fetch-ctfd-challenges", Button).disabled = False

    def cancel_fetch(self) -> None:
        self._cancelled = True
        if self._fetch_task is not None and not self._fetch_task.done():
            self._fetch_task.cancel()
        self.dismiss(None)

    def report_error(self, message: str) -> None:
        self.query_one("#ctfd-import-error", Static).update(message)
        self.app.log_error(f"CTFd import: {message}")

    def action_cancel(self) -> None:
        self.cancel_fetch()


class ImportPreviewDialog(ModalScreen[bool]):
    """Show the complete import plan and require a deliberate confirmation."""

    BINDINGS = [Binding("escape", "cancel", "Cancel", priority=True)]

    CSS = """
    ImportPreviewDialog {
        align: center middle;
        background: #07131c 80%;
    }

    #import-preview-dialog {
        width: 88;
        max-width: 96%;
        height: 90%;
        max-height: 90%;
        border: round #e7c66a;
        background: #0b202b;
        padding: 1 2;
    }

    #import-preview-title {
        height: 1;
        color: #e7c66a;
        text-style: bold;
        margin-bottom: 1;
    }

    #import-preview-content {
        height: 1fr;
        overflow-y: auto;
        margin-bottom: 1;
    }

    #import-preview-actions {
        height: auto;
        align-horizontal: right;
    }

    #cancel-import-preview, #confirm-import {
        height: 1;
        border: none;
        padding: 0 1;
    }
    """

    def __init__(self, ctf_name: str, source: str, plan: ImportPlan) -> None:
        super().__init__()
        self.ctf_name = ctf_name
        self.source = source
        self.plan = plan

    def on_mount(self) -> None:
        self.query_one("#confirm-import", Button).focus()

    @staticmethod
    def _names(records: Sequence[Mapping[str, object]]) -> list[str]:
        names = [str(record.get("name", "Unnamed")) for record in records]
        if len(names) > 20:
            return [*names[:20], f"... and {len(names) - 20} more"]
        return names

    def preview_text(self) -> str:
        additions = [
            *self.plan.additions,
            *(record for record, _matches in self.plan.name_only_matches),
        ]
        lines = [
            f"CTF: {self.ctf_name}",
            f"Source: {'CTFd API' if self.source == 'ctfd' else 'CTFd JSON'}",
            f"Challenges to add: {len(additions)}",
            f"Already present by remote ID (unchanged): {len(self.plan.remote_matches)}",
            f"Name-only suggestions (will be added separately, not merged): "
            f"{len(self.plan.name_only_matches)}",
            "",
        ]
        if additions:
            lines.extend(
                ["ADDITIONS", *(f"  {name}" for name in self._names(additions))]
            )
        else:
            lines.append("No new challenges.")
        if self.plan.remote_matches:
            lines.extend(
                [
                    "",
                    "REMOTE ID MATCHES (existing local records will not be changed)",
                    *(
                        f"  {record['name']} -> {existing.get('name', 'Unnamed')}"
                        for record, existing in self.plan.remote_matches
                    ),
                ]
            )
        if self.plan.name_only_matches:
            lines.extend(["", "NAME-ONLY SUGGESTIONS (no automatic merge)"])
            for record, candidates in self.plan.name_only_matches:
                candidate_names = ", ".join(
                    str(candidate.get("name", "Unnamed")) for candidate in candidates
                )
                lines.append(f"  {record['name']} may match: {candidate_names}")
        lines.extend(
            [
                "",
                "Confirm to add the listed challenges. Existing challenges are left unchanged.",
            ]
        )
        return "\n".join(lines)

    def compose(self) -> ComposeResult:
        with Vertical(id="import-preview-dialog"):
            yield Label(
                "IMPORT PREVIEW // CONFIRM BEFORE WRITING", id="import-preview-title"
            )
            yield Static(self.preview_text(), id="import-preview-content", markup=False)
            with Horizontal(id="import-preview-actions"):
                yield Button("Cancel", id="cancel-import-preview")
                yield Button("Add Challenges", id="confirm-import", variant="primary")

    @on(Button.Pressed)
    def handle_button(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm-import":
            self.dismiss(True)
        elif event.button.id == "cancel-import-preview":
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class ArtifactDownloadDialog(ModalScreen[bool | None]):
    """Preview selected challenge artifacts and require overwrite confirmation."""

    BINDINGS = [Binding("escape", "cancel", "Cancel", priority=True)]

    CSS = """
    ArtifactDownloadDialog {
        align: center middle;
        background: #07131c 80%;
    }

    #artifact-download-dialog {
        width: 78;
        max-width: 95%;
        height: auto;
        max-height: 80%;
        border: round #e7c66a;
        background: #0b202b;
        padding: 1 2;
    }

    #artifact-download-title {
        height: 1;
        color: #e7c66a;
        text-style: bold;
        margin-bottom: 1;
    }

    #artifact-download-content {
        height: auto;
        max-height: 1fr;
        overflow-y: auto;
        margin-bottom: 1;
    }

    #artifact-download-actions {
        height: auto;
        align-horizontal: right;
    }

    #cancel-artifact-download, #confirm-artifact-download {
        height: 1;
        border: none;
        padding: 0 1;
    }
    """

    def __init__(
        self,
        challenge_name: str,
        artifacts: Sequence[tuple[str, bool]],
    ) -> None:
        super().__init__()
        self.challenge_name = challenge_name
        self.artifacts = tuple(artifacts)
        self.overwrites = any(downloaded for _filename, downloaded in artifacts)

    def preview_text(self) -> str:
        lines = [
            f"Challenge: {self.challenge_name}",
            "The following files will be downloaded:",
        ]
        lines.extend(
            f"  {filename} — {'OVERWRITE existing file' if downloaded else 'new file'}"
            for filename, downloaded in self.artifacts
        )
        if self.overwrites:
            lines.extend(
                [
                    "",
                    "Existing files will be replaced in place. No extra versions will be kept.",
                ]
            )
        return "\n".join(lines)

    def compose(self) -> ComposeResult:
        with Vertical(id="artifact-download-dialog"):
            yield Label(
                "ARTIFACT DOWNLOAD // CONFIRM REPLACEMENTS",
                id="artifact-download-title",
            )
            yield Static(
                self.preview_text(), id="artifact-download-content", markup=False
            )
            with Horizontal(id="artifact-download-actions"):
                yield Button("Cancel", id="cancel-artifact-download")
                yield Button(
                    "Overwrite and Download" if self.overwrites else "Download",
                    id="confirm-artifact-download",
                    variant="primary",
                )

    @on(Button.Pressed)
    def handle_button(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm-artifact-download":
            self.dismiss(True)
        elif event.button.id == "cancel-artifact-download":
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class CTFdRefreshPreviewDialog(ModalScreen[bool | None]):
    """Review imported-source refresh additions and changes before applying."""

    BINDINGS = [Binding("escape", "cancel", "Cancel", priority=True)]

    CSS = """
    CTFdRefreshPreviewDialog {
        align: center middle;
        background: #07131c 80%;
    }

    #ctfd-refresh-dialog {
        width: 88;
        max-width: 96%;
        height: 90%;
        max-height: 90%;
        border: round #e7c66a;
        background: #0b202b;
        padding: 1 2;
    }

    #ctfd-refresh-title {
        height: 1;
        color: #e7c66a;
        text-style: bold;
        margin-bottom: 1;
    }

    #ctfd-refresh-content {
        height: 1fr;
        overflow-y: auto;
        margin-bottom: 1;
    }

    #ctfd-refresh-actions {
        height: auto;
        align-horizontal: right;
    }

    #cancel-ctfd-refresh, #confirm-ctfd-refresh {
        height: 1;
        border: none;
        padding: 0 1;
    }
    """

    def __init__(
        self, ctf_name: str, plan: RefreshPlan, source: str = "CTFd API"
    ) -> None:
        super().__init__()
        self.ctf_name = ctf_name
        self.plan = plan
        self.source = source

    @staticmethod
    def _display(value: object) -> str:
        rendered = str(value) if value is not None else "—"
        return rendered.replace("\n", " ")[:120]

    def preview_text(self) -> str:
        lines = [
            f"CTF: {self.ctf_name}",
            f"Source: {self.source}",
            f"Challenges to add: {len(self.plan.additions)}",
            f"Challenges with remote changes: {len(self.plan.updates)}",
            f"Unchanged challenges: {len(self.plan.unchanged)}",
            f"Missing remotely (will be kept locally): {len(self.plan.missing)}",
        ]
        if self.plan.additions:
            lines.extend(["", "ADDITIONS"])
            lines.extend(f"  {record['name']}" for record in self.plan.additions)
        if self.plan.updates:
            lines.extend(["", "CHANGES"])
            for remote, local, merged in self.plan.updates:
                lines.append(f"  {local.get('name', 'Unnamed')}")
                for field in (
                    "name",
                    "category",
                    "points",
                    "description",
                    "artifacts",
                ):
                    if local.get(field) != merged.get(field):
                        if field == "artifacts":
                            before_artifacts = [
                                item
                                for item in local.get("artifacts", [])
                                if isinstance(item, Mapping)
                            ]
                            after_artifacts = [
                                item
                                for item in merged.get("artifacts", [])
                                if isinstance(item, Mapping)
                            ]
                            before = ", ".join(
                                str(item.get("filename", ""))
                                for item in before_artifacts
                            )
                            after = ", ".join(
                                str(item.get("filename", ""))
                                for item in after_artifacts
                            )
                            if before == after and any(
                                old.get("source_url") != new.get("source_url")
                                for old, new in zip(
                                    before_artifacts, after_artifacts, strict=False
                                )
                            ):
                                before += " (reference)"
                                after += " (updated reference)"
                        else:
                            before = self._display(local.get(field))
                            after = self._display(merged.get(field))
                        lines.append(f"    {field}: {before} -> {after}")
        if self.plan.missing:
            lines.extend(["", "NO LONGER PRESENT REMOTELY (kept locally)"])
            lines.extend(
                f"  {record.get('name', 'Unnamed')}" for record in self.plan.missing
            )
        lines.extend(
            [
                "",
                "Local status, flags, solver data, notes, and local-only artifacts are preserved.",
            ]
        )
        return "\n".join(lines)

    def compose(self) -> ComposeResult:
        with Vertical(id="ctfd-refresh-dialog"):
            yield Label("REFRESH // REVIEW BEFORE APPLYING", id="ctfd-refresh-title")
            yield Static(self.preview_text(), id="ctfd-refresh-content", markup=False)
            with Horizontal(id="ctfd-refresh-actions"):
                yield Button("Cancel", id="cancel-ctfd-refresh")
                yield Button(
                    "Apply Refresh", id="confirm-ctfd-refresh", variant="primary"
                )

    def on_mount(self) -> None:
        self.query_one("#confirm-ctfd-refresh", Button).focus()

    @on(Button.Pressed)
    def handle_button(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm-ctfd-refresh":
            self.dismiss(True)
        elif event.button.id == "cancel-ctfd-refresh":
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)
