# Implementation plan

| Phase | Scope | Status |
| --- | --- | --- |
| 0 | Audit the empty repository and record the baseline. | Done |
| 1 | Requirements, architecture, security, and decisions. | Done in `docs/data-cleaning/` |
| 2 | Signature checks, CSV and XLSX readers, limits. | Done |
| 3 | Profiling without mutation. | Done |
| 4 | Registered transforms and postconditions. | Done for the catalog in `operations.py` |
| 5 | Plan schema, preview, ledger, validation, failure without delivery. | Done |
| 6 | Rule interpreter and optional clarification adapter. | Done. Provider not configured. |
| 7 | Persian UI bound to job status, preview, and downloads. | Done |
| 8 | Report and ledger files generated from execution records. | Done |
| 9 | Token, retention, zip limits, formula guard, tests. | Done for the controls listed in `SECURITY.md` |
| 10 | Suite plus a timed 10,000-row run. | Done. See `PROJECT_STATE.md` |

## Later, only if a real workbook needs it

- A tested XLS conversion path.
- VBA round-trip fixture.
- Explicit preservation tests for charts and conditional formatting.
- Asynchronous execution with cooperative cancellation.
- A richer clarification model, still behind the option allowlist.

## First slice that is already executable

Upload `web/examples/customers.csv`, send the Persian cleaning sentence from the product brief, review the plan, execute, and download the CSV plus the report.
