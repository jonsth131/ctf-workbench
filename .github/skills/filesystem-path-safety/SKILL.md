---
name: filesystem-path-safety
description: Keep CTF Workbench storage paths contained, validate generated IDs, and safely store imported artifacts and solver files.
---

# Filesystem and Path Safety

Use this skill whenever code reads or writes managed files, artifacts, or
solver paths.

## Code ownership

- Keep managed storage operations and path containment in
  `src/ctfwb/storage/data_store.py`; keep record and ID validation in
  `src/ctfwb/storage/schema.py`.
- Keep imported artifact filename validation in
  `src/ctfwb/importers/json_import.py`.
- Prefer the public `ctfwb.storage` and `ctfwb.importers` APIs over duplicating
  path or filename checks in UI code.

## Guidance

- Store all user data beneath the configured per-user data directory.
- Use application-generated stable IDs for directory names.
- Validate IDs before using them as path components.
- Never use user-provided names, imported filenames, or remote values directly
  as trusted paths.
- Resolve and verify managed paths remain beneath their designated root.
- Sanitize artifact filenames before storage and retain original names only as
  metadata.
- Require explicit confirmation before replacing an existing artifact file.
  Replace it atomically in place; do not create versioned copies for an
  overwrite.
- Do not treat a failed or partial download as a completed artifact.
- Validate solver-relative paths and ensure they resolve inside the challenge
  directory.
- Test traversal attempts, absolute paths, symlinks where relevant, unconfirmed
  collisions, and names containing spaces or special characters.
