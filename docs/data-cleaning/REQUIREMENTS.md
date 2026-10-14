# Requirements

The product is a local workspace. A person uploads a CSV or XLSX file, describes the change in Persian or English, reviews a concrete plan, and downloads a separate result only after validation.

## Functional

| ID | Requirement | Priority | Status |
| --- | --- | --- | --- |
| F-01 | Accept CSV and XLSX after signature checks. Reject XLS, XLSB, empty files, and corrupt packages. | P0 | Implemented |
| F-02 | Keep the uploaded bytes unchanged and write a separate output. | P0 | Implemented |
| F-03 | Inspect sheets, dimensions, formulas, merges, and basic workbook objects without modifying values. | P0 | Implemented |
| F-04 | Profile blanks, whitespace, duplicates, date candidates, and identifier-like columns without mutating them. | P0 | Implemented |
| F-05 | Turn a natural-language request into registered operations, or ask a blocking question. | P0 | Implemented |
| F-06 | Show a preview count produced by running the plan in memory. | P0 | Implemented |
| F-07 | Trim, collapse whitespace, remove invisible characters, drop fully empty rows, standardize unambiguous dates, and mark exact duplicates. | P0 | Implemented |
| F-08 | Remove exact duplicates only with an extra approval, keeping the first row. | P0 | Implemented |
| F-09 | Leave partial rows, zeros, false, ambiguous dates, and leading zeros in place. | P0 | Implemented |
| F-10 | Produce a report and a ledger from the execution record and validate the reopened file. | P0 | Implemented |
| F-11 | Persian UI, RTL layout, and a bundled Persian font. | P1 | Implemented |
| F-12 | Optional model that may only select an offered clarification answer. | P1 | Implemented, off by default |
| F-13 | Jalali/Gregorian conversion only when the request or the answer names the target calendar. | P1 | Implemented |
| F-14 | Flag email syntax without claiming the mailbox exists. | P2 | Implemented |
| F-15 | Normalize only Arabic yeh/kaf variants, and only when asked. | P2 | Implemented |

## Non-functional

| ID | Requirement | Status |
| --- | --- | --- |
| NF-01 | Useful cleaning with no AI provider and no network call. | Implemented |
| NF-02 | Upload, row, column, sheet, cell, and zip-expansion limits. | Implemented |
| NF-03 | Job id is an unguessable capability. Optional `WORKSPACE_ACCESS_TOKEN`. | Implemented |
| NF-04 | Retention default 24 hours, then files and profiles are deleted. | Implemented |
| NF-05 | Errors returned to the client have a Persian message and no stack trace. | Implemented |
| NF-06 | 10,000 CSV rows of two columns were cleaned in about 0.25 seconds on this machine. The hard cap is 50,000 rows. | Measured for 10,000; cap enforced |

## Exclusions

- Legacy XLS and XLSB.
- Formula evaluation and macro execution.
- Merging similar but non-identical records.
- Deleting partially empty rows.
- Guessing ambiguous dates, decimal separators, phone country codes, or imputed values.
- Claiming that every Excel feature survives an openpyxl save.
- Multi-user accounts, tenants, and a background queue.
- Cancelling a run after execution has started. Cancellation works only before execute.

## Assumptions

- One operator runs the process on a trusted machine. Bind address defaults to `127.0.0.1`.
- The first sheet's headers define column indexes. The same indexes are used on every sheet; a sheet that lacks the column is skipped with a warning.
- Header row is the fullest of the first five rows, unless the first row has at most one value and the second has more.
- Fully empty means every cell is missing or whitespace. `0`, `false`, and tokens such as `null` are not empty.

## Acceptance for the first slice

A CSV like `web/examples/customers.csv` can be uploaded, planned with the sample Persian sentence, executed, validated, and downloaded. The source hash is unchanged, duplicate customers are marked, fully empty rows are gone, `00123` and `1,000` and `0` remain, and `01/02/2024` is not rewritten.
