# Repository audit — 2026-11-04

## Baseline

Existing Django project inspected: settings, routes, every model, source registry,
base/CFTC collectors, four commands, API, admin, initial migration, tests and dependencies.
Python environment: existing Windows venv, Python 3.12.8. No Git metadata exists.
Initial automated baseline: 5 tests passed using the explicitly enabled SQLite test backend;
Django system check clean; `makemigrations --check --dry-run`: no changes.
SQLite results do not certify PostgreSQL. Production remains PostgreSQL.

## Findings before implementation

| Priority | Finding | Evidence / impact |
|---|---|---|
| Critical | Archive checkpoint ignores requested coverage | `cftc._run` skips a complete SHA even after a narrow backfill; later dates/markets never load. |
| High | Normalization exceptions escape row handling | Generator advances outside `persist` try block; malformed row aborts file, raw remains processing. |
| High | No file transaction | Per-row commits leave partially written files after database failure. |
| High | Source enabled flag unenforced | Disabled providers can still execute. |
| High | No collector locking or recovery | Concurrent runs can overwrite newer revisions; no durable work queue. |
| High | Default secret | Missing environment secret silently uses a public development value. |
| Medium | Nullable instrument uniqueness | NULL expiration permits duplicate undated instruments. Existing duplicates must not be deleted. |
| Medium | CSV shape not checked | Extra columns discarded, missing cells silently empty, duplicate normalized headers overwrite. |
| Medium | Position field matching incomplete | Legacy/source-specific position names may not match the current suffix pattern. |
| Medium | Raw provenance SHA globally unique | Same bytes from distinct sources share identity; must scope identity to provider. |
| Medium | API date errors not validated | Malformed date can become a server error; OI/OHLCV lack filters. |
| Medium | Health only returns constant | Does not establish database readiness. |
| Medium | Source check returns success on errors | Automation cannot reliably detect failures. |
| Medium | Download retry/resource gaps | HTTP exceptions inconsistent; no Retry-After, streamed-to-file workflow, or retry telemetry. |
| Missing | Non-CFTC adapters, imports, exports, dashboard, scheduler, quality scans | Registered sources are not working collectors. |

## Preservation rules

Do not delete current rows or recreate migration 0001. Add migrations only. Quarantine bad
input and retain raw evidence. Never infer prices from reference/OI data or equate CFTC
markets with exchange contracts. Never log secrets or raw database exception messages.

## Validation tracking

See ACCEPTANCE_REPORT.md and LIVE_SOURCE_REPORT.md for final commands, counts, limitations
and per-step outcomes. This file records the pre-change findings, not a production certificate.
