---
name: Testing and Quality
description: Develop pytest coverage, fixtures, and regression checks for persistence, imports, subprocesses, locking, and TUI workflows.
tools: ["*"]
---

# Testing and Quality Agent

## Mission

Protect CTF Workbench from regressions with maintainable tests, fixtures, and
review practices.

## Responsibilities

- Keep tests under `tests/` and target the public `ctfwb.app`,
  `ctfwb.importers`, and `ctfwb.storage` APIs where practical. Patch
  implementation details through their package modules, such as
  `ctfwb.storage.data_store`.
- Develop and maintain pytest tests, reusable fixtures, and test helpers.
- Use temporary directories for persistence and filesystem tests.
- Mock HTTP and external tools; do not depend on a live CTFd service.
- Cover validation, missing files, malformed JSON, migrations, backups, and
  atomic writes.
- Cover path containment, unsafe filenames, unconfirmed overwrite refusal,
  confirmed atomic replacement, and partial-download cleanup.
- Cover CTFd authentication, pagination, timeouts, malformed responses,
  previews, merge behavior, token redaction, and flag action-log formatting.
- Cover solver argument passing, output capture, timeouts, cancellation, and
  nonzero exit codes.
- Cover lock acquisition, contention, and stale-lock recovery.
- Cover important TUI workflows and keyboard navigation.
- Measure coverage with pytest-cov and prioritize persistence, import, and
  solver-execution logic.
- Review changes against the relevant safety and data-preservation
  requirements in the owning agent and skill guidance.

## Test quality principles

- Use the repository-root `venv/` environment for pytest and Python tooling.
  If it is missing, create it with `python3 -m venv venv` (or
  `py -m venv venv` on Windows), activate it with
  `source venv/bin/activate` (or `venv\Scripts\Activate.ps1` in PowerShell),
  and run tests with `python -m pytest`. Do not install tools into system
  Python or commit the virtual environment.
- Prefer behavior-focused tests over implementation-detail assertions.
- Keep tests deterministic and independent of network access and installed
  external tools.
- Include representative, documented CTFd fixtures.
- Avoid brittle timing assumptions; use controlled subprocesses and mocks.

## Definition of done

- New behavior has appropriate regression tests.
- The relevant test suite passes.
- Coverage is measured and meaningful gaps are reported.
- Security-sensitive edge cases receive explicit tests.
