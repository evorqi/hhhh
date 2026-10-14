# Test strategy

Runner: `pytest` with `pythonpath = src`. HTTP tests use FastAPI's `TestClient`.

| Layer | What it covers |
| --- | --- |
| Unit | Date pairs, leap days, ambiguous dates, trim idempotence, ZWNJ preservation, AI answer filtering, archive limits. |
| Transforms | Empty versus partial rows, zero and false, formulas left intact, merged cells blocking deletion, leading zeros, quoted newlines, formula guard, Persian plan. |
| API | Upload through download, source hash, idempotent execute, approval refusal, clarification block, XLS and corrupt XLSX, MIME ignored, token, expiry, cancel, Windows-1256. |
| Scale | 2,000 CSV rows inside the suite. A separate local run cleaned 10,000 rows in about 0.25 seconds. 50,001 rows are rejected by the cap. |

## Invariants that are actually checked

- Trimming twice equals trimming once, for the text helper.
- A rejected destructive execute does not change source bytes.
- After success, the stored source hash still matches the file.
- Reopened output matches ledger hashes for the recorded net changes.
- Formula counts survive a whitespace edit.
- Fully empty rows do not remain unless a merge blocked them.
- CSV cells that still need the formula guard fail validation.

## Not covered by an automated fixture

- A real VBA project round-trip.
- Charts, images, conditional formatting, and pivot tables.
- 1904 workbooks beyond the warning path.
- Mid-execution cancellation.
- A live call to an AI provider. The filter is tested with local payloads. The network function is not called in tests.

Do not delete a failing test to make the suite green. Replace an expectation only when the previous expectation disagreed with the stated rule, as with collapsing an embedded newline into a space when that operation was requested.
