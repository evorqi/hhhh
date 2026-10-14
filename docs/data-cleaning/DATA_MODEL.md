# Data model

Only job metadata is stored in SQLite. Cell bodies stay in the uploaded file and the output file.

## `jobs`

| Field | Meaning |
| --- | --- |
| `id` | UUID. This is the capability used to read the job. |
| `status` | Current lifecycle state. |
| `original_filename` | Display name only. Path characters are stripped. Never used as a filesystem path. |
| `detected_format` | `csv` or `xlsx`. |
| `size_bytes`, `source_sha256` | Size and hash taken when the bytes were stored. |
| `created_at`, `updated_at`, `expires_at` | UTC timestamps. Default lifetime is 24 hours (`CLEANING_RETENTION_HOURS`). |
| `error_code`, `error_message_fa`, `error_message_en` | Safe error, when the job failed. |
| `inspection_json` | Workbook structure and warnings. No full cell dump. |
| `profile_json` | Column statistics and up to three short samples per column. |
| `plan_json` | The reviewed plan, including preview counts. |
| `result_json` | Validation summary and report after execution. |

## `job_events`

Append-only. Each row is a status that was actually entered, with a Persian detail and a timestamp. There is no separate progress percentage.

## Files

```text
data/jobs/<uuid>/source
data/jobs/<uuid>/output
data/jobs/<uuid>/report.json
data/jobs/<uuid>/ledger.json
```

`source` is written once. `output` is written only for a new path and removed if validation fails. On expiry the directory is deleted and the JSON columns are cleared. The job row remains as `expired` so the id does not get reused, but `GET` returns 404.

## Ledger

Each applied operation stores its real affected count, unresolved items (capped), warnings, and up to 200 samples. Samples of sensitive headers (email, phone, national id, account) are redacted; the SHA-256 of the canonical value is kept so validation can still compare. Net changes are capped at 2000 stored records. Counts themselves are not capped. If more than 2000 net changes exist, hash checks cover the first and last 250 and the truncation is stated.

## Ownership

There is no user table. Possession of the job UUID, plus the workspace token when `WORKSPACE_ACCESS_TOKEN` is set, is the authorization check.
