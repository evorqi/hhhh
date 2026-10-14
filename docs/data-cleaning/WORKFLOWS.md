# Workflows

## States

| State | Meaning |
| --- | --- |
| `uploaded` | Bytes stored and hashed. |
| `validating` | Format accepted and the reader is running. |
| `profiling` | The in-memory model exists. |
| `awaiting_request` | Inspection and profile are saved. |
| `plan_ready` | A non-blocking plan exists. |
| `clarification_required` | At least one question is unanswered. Execute is refused. |
| `approval_required` | The plan removes exact duplicates. Execute without `approve_destructive` is refused and does not change state. |
| `executing` | The registered operations are running. |
| `verifying` | In-memory postconditions passed. |
| `exporting` | A new file is being written. |
| `completed` | Validation passed and the request had no leftover warnings or unsupported parts. |
| `completed_with_limitations` | Validation passed, and the report lists unresolved or unsupported parts. |
| `validation_failed` | The reopened file disagreed with the ledger, or an invariant failed. Output is not downloadable. |
| `failed` | Intake or execution failed. Source is kept until expiry if it was stored. |
| `cancelled` | Cancelled before execute. |
| `expired` | Files deleted. |

Rejected uploads that fail the signature policy (empty, XLS, zip bomb, corrupt XLSX) do not create a job and are not stored.

## Legal transitions

- Intake: `uploaded → validating → profiling → awaiting_request`, or `failed` if reading fails after the file was stored.
- Plan, from `awaiting_request`, `plan_ready`, `clarification_required`, `approval_required`, `failed`, or `validation_failed`, when a profile exists: to `plan_ready`, `clarification_required`, or `approval_required`.
- Execute, from `plan_ready` or `approval_required`: `executing → verifying → exporting → completed` or `completed_with_limitations`.
- The same completed plan id returns the existing result and does not run again.
- Cancel, before execute: `cancelled`.
- Expiry from any non-expired job: `expired`.

## Recovery

A failed or validation-failed job that still has a profile can be re-planned. The source bytes are not modified. Completed and cancelled jobs are terminal; upload again to start over.

## Cancellation and retries

Execute is synchronous inside the request. Another request cannot cancel it mid-operation. Cancel is tested before execute. A repeated execute with the same plan id after success is idempotent.

## Preview

Planning runs the engine in memory with approval enabled so destructive counts are real. That run does not write a file. The displayed preview is that result. The later execute runs the plan again from the original file.
