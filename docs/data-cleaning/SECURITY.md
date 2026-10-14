# Security

## Threats and controls

| Threat | Control |
| --- | --- |
| Huge upload | `CLEANING_MAX_UPLOAD_BYTES` (default 20 MiB), checked while reading the body. |
| Zip bomb or path inside the XLSX package | Member count, declared uncompressed size, and rejection of absolute or `..` names. |
| Misleading extension or MIME | MIME is ignored. OLE magic is rejected. PK packages must contain `[Content_Types].xml` and `xl/workbook.xml`. |
| Overwriting the upload | Output is a different path. Export refuses identical source and destination paths. The hash is checked again before delivery. |
| Path traversal on download | Job ids must be UUID shaped. Artifact names are `source`, `output`, `report`, `ledger`. |
| Stolen URL | The UUID is the capability. Set `WORKSPACE_ACCESS_TOKEN` to also require `X-Workspace-Token`. Health and meta stay open so the UI can load. Comparison uses `hmac.compare_digest`. The token is not logged or echoed. |
| Formula injection in CSV | Apostrophe prefix, recorded as `csv_formula_guard`. Plain negative numbers are not prefixed. XLSX text that starts with `=` is stored with data type string when this program writes it. Existing formulas are not executed. |
| Macros, formulas, external links | Not executed and not fetched. |
| Prompt injection | Cell text is not sent to a planner as instructions. The rule planner only matches cleaning verbs. Unknown operation types never run. A configured model may only return an option id from the question already built locally. |
| Sensitive logs | Ledger samples for email, phone, and account-like headers are redacted. Server logs contain job ids, statuses, and counts. |
| Stack traces | Unhandled errors return a fixed Persian message. The traceback stays in the server log. |
| Retention | Expired jobs lose their files and stored profiles. |

## Secrets

Read only from the environment: `WORKSPACE_ACCESS_TOKEN`, `CLEANING_AI_API_KEY`. They are masked in the startup log (`access_token_set`, `ai_configured`). Nothing in the repository is a credential.

## AI boundary

Default: no outbound call. When configured, the payload is the user request (max 2000 characters) and the clarification option ids. Workbook cells are not included. The endpoint URL is operator configuration, not something the uploaded file can set.

## Residual risk

- Anyone who can read the server log or the data directory can use a job UUID.
- The CSV guard is not a universal guarantee for every application that opens the file.
- openpyxl preservation gaps can still change an untested workbook feature even though cell values of untouched formulas are tested.
- This is not a multi-tenant authorization system.
