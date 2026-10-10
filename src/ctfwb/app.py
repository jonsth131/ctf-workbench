"""Stable application entry point and compatibility exports."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from ctfwb.config import AppConfig, ConfigError

# Retain historical import surfaces used by callers and test monkeypatches.
from ctfwb.editor import run_editor
from ctfwb.importers import (
    CTFdError,
    ImportErrorBase,
    ImportPlan,
    create_import_plan,
    fetch_ctfd_challenges,
    validate_challenge_json,
)
from ctfwb.logging_setup import (
    APP_LOGGER,
    close_file_logging,
    configure_file_logging,
    log_debug_exception,
)
from ctfwb.storage import (
    DataStore,
    DataStoreError,
    LockError,
    generate_id,
    utc_timestamp,
)
from ctfwb.tools import TOOL_HELPERS
from ctfwb.ui.application import CTFWorkbenchApp
from ctfwb.ui.dialogs import (
    AddChallengeDialog,
    AddCTFDialog,
    ConfirmDeleteChallengeDialog,
    ConfirmDeleteCTFDialog,
    ConfirmOverwriteSolverDialog,
    CTFdImportDialog,
    EditChallengeDialog,
    EditFlagDialog,
    ExportArchiveDialog,
    ImportJSONDialog,
    ImportPreviewDialog,
    ImportSourceDialog,
    RefreshSourceDialog,
    SelectChallengeStatusDialog,
    SelectSolverTemplateDialog,
    SolverOutputDialog,
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

__all__ = [
    "CTF",
    "Challenge",
    "CTFTimeLookup",
    "CTFChallengeScreen",
    "CTFWorkbenchApp",
    "ImportSourceDialog",
    "ImportJSONDialog",
    "CTFdImportDialog",
    "ImportPreviewDialog",
    "RefreshSourceDialog",
    "AddCTFDialog",
    "ConfirmDeleteCTFDialog",
    "AddChallengeDialog",
    "EditChallengeDialog",
    "ConfirmDeleteChallengeDialog",
    "SelectChallengeStatusDialog",
    "EditFlagDialog",
    "SelectSolverTemplateDialog",
    "ConfirmOverwriteSolverDialog",
    "SolverOutputDialog",
    "ExportArchiveDialog",
    "main",
    "_default_ctftime_lookup",
    "_ctf_from_record",
    "_challenge_from_record",
    "_ctf_record",
    "_challenge_record",
    "AppConfig",
    "ConfigError",
    "APP_LOGGER",
    "close_file_logging",
    "configure_file_logging",
    "log_debug_exception",
    "DataStore",
    "DataStoreError",
    "LockError",
    "generate_id",
    "utc_timestamp",
    "run_editor",
    "CTFdError",
    "ImportErrorBase",
    "ImportPlan",
    "create_import_plan",
    "fetch_ctfd_challenges",
    "validate_challenge_json",
]


def main(
    config_path: Path | None = None,
    argv: Sequence[str] | None = None,
) -> int:
    """Load configuration, initialize logging, and launch the application."""
    parser = argparse.ArgumentParser(prog="ctf-workbench")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="write diagnostic details to the application log",
    )
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser(
        "doctor",
        help="check which registered external tool helpers are installed",
    )
    if argv is None and config_path is not None:
        argv = []
    arguments = parser.parse_args(argv)

    if arguments.command == "doctor":
        return run_doctor()

    try:
        config = AppConfig.load(config_path)
    except ConfigError as error:
        try:
            log_path = configure_file_logging(
                error.path.parent / "logs",
                debug=arguments.debug,
            )
            APP_LOGGER.error("Configuration error: %s", error)
            log_debug_exception("Configuration loading failed", error)
            APP_LOGGER.debug("Application log: %s", log_path)
        except OSError as log_error:
            print(f"Cannot initialize application log: {log_error}", file=sys.stderr)
        finally:
            close_file_logging()
        print(f"Configuration error: {error}", file=sys.stderr)
        return 1

    try:
        log_path = configure_file_logging(
            config.data_dir / "logs",
            debug=arguments.debug,
        )
    except OSError as error:
        print(f"Cannot initialize application log: {error}", file=sys.stderr)
        close_file_logging()
        return 1
    APP_LOGGER.debug("Application log: %s", log_path)
    APP_LOGGER.debug("Data directory: %s", config.data_dir)
    APP_LOGGER.debug("Debug logging enabled")

    try:
        data_store = DataStore(config.data_dir)
        try:
            data_store.acquire()
        except LockError as error:
            APP_LOGGER.error("Cannot start CTF Workbench: %s", error)
            log_debug_exception("Application startup failed", error)
            print(f"Cannot start CTF Workbench: {error}", file=sys.stderr)
            return 1

        try:
            CTFWorkbenchApp(
                data_store=data_store,
                config=config,
            ).run()
        except Exception as error:
            APP_LOGGER.error("Unhandled application error (%s)", type(error).__name__)
            log_debug_exception("Unhandled application error traceback", error)
            raise
        finally:
            data_store.release()
        return 0
    finally:
        close_file_logging()


def run_doctor() -> int:
    """Report whether registered external-tool helpers can find their tools."""
    print("External tool helpers:")
    all_installed = True
    for helper in TOOL_HELPERS:
        executable = helper.find_executable()
        if executable is None:
            print(f"  {helper.name}: missing ({helper.executable} not found on PATH)")
            all_installed = False
        else:
            print(f"  {helper.name}: installed ({executable})")
    return 0 if all_installed else 1
