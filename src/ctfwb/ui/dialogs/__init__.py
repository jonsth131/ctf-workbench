"""Dialogs grouped by the screens and workflows that use them."""

from ctfwb.importers import fetch_ctfd_challenges
from ctfwb.ui.dialogs.backup import ExportArchiveDialog
from ctfwb.ui.dialogs.challenges import (
    AddChallengeDialog,
    ConfirmDeleteChallengeDialog,
    EditChallengeDialog,
    EditFlagDialog,
    OpenArtifactsDirectoryDialog,
    SelectChallengeStatusDialog,
)
from ctfwb.ui.dialogs.ctfs import AddCTFDialog, ConfirmDeleteCTFDialog
from ctfwb.ui.dialogs.imports import (
    ArtifactDownloadDialog,
    CTFdImportDialog,
    CTFdImportResult,
    CTFdRefreshPreviewDialog,
    ImportJSONDialog,
    ImportPreviewDialog,
    ImportSourceDialog,
    RefreshSourceDialog,
)
from ctfwb.ui.dialogs.loading import LoadingDialog
from ctfwb.ui.dialogs.solvers import (
    ConfirmOverwriteSolverDialog,
    SelectSolverTemplateDialog,
    SolverOutputDialog,
)

__all__ = [
    "ExportArchiveDialog",
    "SelectSolverTemplateDialog",
    "ConfirmOverwriteSolverDialog",
    "SolverOutputDialog",
    "ImportSourceDialog",
    "ImportJSONDialog",
    "CTFdImportDialog",
    "CTFdImportResult",
    "ImportPreviewDialog",
    "ArtifactDownloadDialog",
    "CTFdRefreshPreviewDialog",
    "RefreshSourceDialog",
    "AddCTFDialog",
    "ConfirmDeleteCTFDialog",
    "AddChallengeDialog",
    "EditChallengeDialog",
    "ConfirmDeleteChallengeDialog",
    "SelectChallengeStatusDialog",
    "EditFlagDialog",
    "OpenArtifactsDirectoryDialog",
    "LoadingDialog",
    "fetch_ctfd_challenges",
]
