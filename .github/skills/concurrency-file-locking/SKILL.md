---
name: concurrency-file-locking
description: Implement and test single-instance locking for a resolved CTF Workbench data directory, including contention and stale-lock recovery.
---

# Concurrency and File Locking

Use this skill when implementing access coordination for the data directory.

## Code ownership

Implement lock behavior in `src/ctfwb/storage/locking.py` and keep the public
storage exports in `storage/__init__.py`. `DataStore` exposes lock acquisition
and release; `src/ctfwb/app.py` acquires the lock during startup and releases
it when the application exits.

## Guidance

- Acquire a lock associated with the resolved data directory before editing
  data.
- If another live instance holds the lock, report the conflict and exit without
  modifying data.
- Release the lock on normal exit.
- Detect and safely recover stale locks after a crash where possible.
- Avoid unsafe lock breaking when ownership or process state is uncertain.
- Keep atomic writes even when locking is enabled; a lock is not a replacement
  for atomicity.
- Test acquisition, contention, release, stale recovery, and failure paths.
