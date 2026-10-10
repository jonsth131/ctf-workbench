---
name: json-persistence-migrations
description: Design and implement versioned JSON schemas, validation, migrations, backups, atomic writes, and malformed-file recovery.
---

# JSON Persistence and Migrations

Use this skill when working on `ctfs.json`, challenge `information.json`, or
other persisted JSON data.

The persistence implementation is grouped under `src/ctfwb/storage/`:
`data_store.py` handles storage operations, `schema.py` defines validation,
and `locking.py` manages data-directory locks. Prefer the public API exported
by `ctfwb.storage`.

## Guidance

- Include a schema version in each persisted JSON document.
- Validate loaded data before it is used.
- Create valid defaults only when required files are missing.
- Never silently overwrite malformed or invalid existing files.
- Report the file path and useful parse or validation details; include line and
  column when available.
- Implement explicit, testable migrations.
- Back up files before migrations and bulk updates.
- Write complete content to a temporary file in the same directory, then
  atomically replace the target.
- Ensure failed writes leave the previous canonical file intact.
- Test missing files, malformed files, validation errors, migrations, backup
  behavior, and interrupted writes.
