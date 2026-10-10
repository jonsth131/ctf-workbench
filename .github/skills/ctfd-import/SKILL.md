---
name: ctfd-import
description: Implement and review supported CTFd API and JSON imports, authentication, pagination, previews, artifact downloads, and refresh merges.
---

# CTFd Import

Use this skill when working on CTFd API or JSON import and refresh behavior.

Importer code is grouped under `src/ctfwb/importers/`: JSON validation and
planning live in `json_import.py`, and CTFd HTTP retrieval lives in
`ctfd_client.py`. Prefer the public API exported by `ctfwb.importers`.

## Guidance

- Document the supported API version and exact accepted JSON response shapes.
- Keep representative fixtures in the test suite.
- Send a configured token only to the configured host.
- Require HTTPS; do not send CTFd tokens over HTTP.
- Apply finite request timeouts and handle pagination, rate limits,
  authentication failures, server errors, and malformed responses.
- Redact credentials and sensitive headers in logs and exceptions.
- Match challenges by stable remote ID where available.
- For inputs without stable IDs, preview proposed additions and matches and ask
  for confirmation; never silently merge ambiguous records.
- Fetch challenge details and artifact references during import, but do not
  download artifact contents as part of import. Any later artifact-download
  workflow must be separate and previewed before applying.
- For artifact downloads, fetch fresh detail data for short-lived file links,
  stream only from the configured HTTPS origin without following redirects,
  and never log signed URLs or query tokens.
- Save files atomically beneath managed storage. If a target file already
  exists, require explicit overwrite confirmation and replace it in place;
  do not create versioned artifact copies.
- Preserve local status, flags, solvers, local notes, and local artifacts
  during refresh.
- Do not automatically delete challenges missing from the latest response.
- Use safe filenames and ensure failed downloads do not appear complete.
- Ensure failed imports leave existing data intact.
