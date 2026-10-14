# Project state

Updated: 2026-10-14. Branch: `cursor/data-cleaning-workspace-0acf`.

## Status

The local workspace runs without an AI provider. Upload, inspect, plan, preview, execute, validate, and download are implemented for CSV and XLSX.

| Area | Status |
| --- | --- |
| Repository audit | VERIFIED |
| File detection, CSV, XLSX | TESTED |
| Profiling | TESTED |
| Safe transforms and duplicate marking | TESTED |
| Destructive duplicate removal | TESTED (refused without approval) |
| Plan, ledger, validation | TESTED |
| Persian UI | IMPLEMENTED (bound to API state; no video walkthrough) |
| Optional AI clarifier | IMPLEMENTED, unconfigured, not called |
| XLS / XLSB | Rejected on purpose |
| VBA round-trip, charts, conditional formatting | NOT TESTED |

## Tests

Command: `.venv/bin/pytest -q --tb=line`

Observed: `24 passed, 1 warning in 0.41s`

The warning is Starlette's deprecation notice about `httpx` inside `TestClient`. It is not a product failure.

Separate local timing, not part of the 24 tests: 10,000 CSV rows were cleaned in about 0.25 seconds. 50,001 rows were rejected by `CLEANING_MAX_ROWS`.

## How to continue

Run `./run.sh` and open `http://127.0.0.1:8000`. Sample file: `web/examples/customers.csv`.

## Known limits

- Cancellation works only before execute.
- Ambiguous dates, partial rows, and similar-but-not-equal records are not guessed or merged.
- openpyxl may not preserve every Excel feature. Untested features are listed in `ARCHITECTURE.md`.
