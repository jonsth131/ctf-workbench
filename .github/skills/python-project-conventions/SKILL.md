---
name: python-project-conventions
description: Apply CTF Workbench's Python 3 conventions for typing, packaging, module boundaries, filesystem operations, subprocesses, and error handling.
---

# Python Project Conventions

Use this skill when creating or changing Python code in CTF Workbench.

## Guidance

- Use a repository-root `venv/` virtual environment for Python commands. If it
  does not exist, create it with `python3 -m venv venv` (or
  `py -m venv venv` on Windows), then activate it with
  `source venv/bin/activate` (or `venv\Scripts\Activate.ps1` in PowerShell).
  Install packages with `python -m pip` while it is active; do not install
  project tools into the system Python. Do not commit the virtual environment.
- Follow the repository's configured formatter, linter, and type-checker.
- Add type annotations to public interfaces and nontrivial internal APIs.
- Keep modules focused; separate UI, domain logic, persistence, integrations,
  and subprocess orchestration.
- Follow this source layout when adding files:
  - Keep the CLI and standalone modules (`app.py`, `config.py`, `ctftime.py`,
    `editor.py`, and `logging_setup.py`) directly under `src/ctfwb/`.
  - Put importer implementation in `ctfwb/importers/` (`json_import.py` and
    `ctfd_client.py`); export its supported API from `importers/__init__.py`.
  - Put persistence implementation in `ctfwb/storage/` (`data_store.py`,
    `schema.py`, and `locking.py`); export its supported API from
    `storage/__init__.py`.
  - Put Textual code in `ctfwb/ui/`: the app shell in `application.py`, one
    screen/view per file in `screens/`, one model per file in `models/`, and
    workflow-specific dialogs in `dialogs/`.
  - When a feature grows beyond a standalone module, group its related files
    in a package rather than adding them flat at the `ctfwb` root. Use
    `ctfwb.importers` and `ctfwb.storage` as the package APIs; `imports.py`
    only preserves the former import path.
- Prefer explicit, structured error handling over broad exception swallowing.
- Keep filesystem and subprocess operations behind small, testable interfaces.
- Use argument lists with subprocess APIs; do not build shell commands from
  user-controlled values.
- Never log CTFd tokens or other sensitive values. Challenge action logs
  intentionally include flag values when added or updated.
- Write tests for observable behavior and failure cases.
- Keep the code readable and maintainable.
- Refactor large functions
- Prefer reusable functions and components over reimplementing
- Think SOLID and KISS (Keep It Simple, Stupid)
- Use Single Responsibility Principle
