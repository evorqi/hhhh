# Architecture

One process. The UI is static files. The API orchestrates jobs. Domain code does the work and does not know HTTP.

```text
web/  ->  api/app.py  ->  services/jobs.py  ->  domain/*
                                              ->  storage/*
                                              ->  ai/client.py   (optional, off by default)
```

## Components

| Module | Responsibility | Not responsible for |
| --- | --- | --- |
| `web/` | Upload, request, plan review, approval, result, download | Deciding what changed |
| `api/app.py` | HTTP, optional token, safe errors | Transformations |
| `services/jobs.py` | State transitions, preview, export, validation, retention | Parsing rules |
| `domain/security.py` | Signatures, zip limits, names, CSV guard policy | Job storage |
| `domain/readers.py` | CSV and XLSX to an in-memory model | Writing output |
| `domain/profiling.py` | Counts and candidate types | Mutation |
| `domain/planner.py` | Request text to a registered plan | Executing it |
| `domain/operations.py` | Allowlisted transforms and postconditions | Arbitrary code |
| `domain/engine.py` | Run a plan or refuse it | HTTP |
| `domain/export.py` | Write a new file | Touching the source path |
| `domain/validate.py` | Reopen the output and compare it with the ledger | Repairing a bad file |
| `ai/client.py` | Pick a clarification option when configured | Inventing operations |

## Data flow

`UPLOAD → VALIDATE_FILE → INSPECT → PROFILE → INTERPRET_REQUEST → BUILD_PLAN → REVIEW_OR_CLARIFY → EXECUTE → VERIFY_DATA → EXPORT → VERIFY_ARTIFACT → DELIVER`

Intake runs validate, inspect, and profile before the response. Planning runs interpretation and an in-memory preview. Execute runs the same plan, writes a new file, reopens it, and only then marks the job complete. A failed validation deletes the output so it cannot be downloaded.

## Format matrix

| Feature | CSV | XLSX |
| --- | --- | --- |
| Multiple sheets | Unsupported. One sheet named `CSV`. | Supported. The plan applies to every sheet. |
| Values and text | Supported. Rewritten. | Supported. Changed cells are patched. |
| Formulas | Not representable. Text that looks like a formula is guarded. | Preserved and not evaluated. Tested. |
| Styles, column widths | Not representable. | Left on the workbook object. Not separately asserted for every style. |
| Merged cells | Not representable. | Kept. Empty-row deletion is blocked when a merge also covers a kept row. Tested. |
| Hidden sheets, rows, columns | Not representable. | Counted. Hidden sheets are still processed. |
| Tables, validation, defined names, comments, hyperlinks | Not representable. | Counted when openpyxl exposes them. Not edited. Round-trip not individually tested. |
| Charts and images | Not representable. | Not edited. A warning is recorded. Survival depends on openpyxl. |
| External links | Not representable. | Not fetched. Warning recorded. |
| VBA | Not representable. | Not executed. `xl/vbaProject.bin` is detected. `keep_vba` is used only then. No automated round-trip fixture. |
| 1904 date system | Not applicable. | Warning recorded. Values come from openpyxl. |
| Conditional formatting | Not representable. | Not inspected and not tested. |
| Delimiters, quotes, newlines, UTF-8, UTF-8 BOM, Windows-1256 | Supported as documented in tests. | Not applicable. |
| Legacy XLS / XLSB | Rejected. | Rejected. |

Output CSV is UTF-8 with BOM and CRLF even if the input used another encoding or newline. That is an export normalization, not a silent value change. Value changes are in the ledger.

## Operation order

Invisible characters, collapse, trim, letters, digits, headers, dates, email flags, empty rows, duplicate mark or removal, then the CSV guard when the file is CSV. The guard is omitted when the plan has no user operation.

## Failure behavior

An invariant failure or an export failure does not publish the output. The source file remains. The job stores the Persian error. Unexpected exceptions become a generic 500 without a traceback in the response.
