# Decisions

## ADR-001 — Python modular monolith

- Status: accepted
- Context: the repository had no stack. The product needs spreadsheet IO, deterministic transforms, a small UI, and tests, without paid services.
- Decision: one Python 3.11+ process. FastAPI serves the HTTP API and the static UI. SQLite stores job metadata. Files live on the local disk.
- Alternatives: a Node service, a separate worker process, or a hosted queue. Rejected because they add operating cost without a current need.
- Revisit when: more than one machine must process jobs, or execution must continue after the request process stops.

## ADR-002 — No pandas

- Status: accepted
- Decision: CSV is parsed with the standard `csv` module and XLSX with openpyxl 3.1.5. Values keep the type the reader produced. Numeric-looking identifiers stay text in CSV.
- Alternatives: pandas. Rejected because it coerces types and can turn identifiers into floats.
- Revisit when: a measured workbook exceeds the documented limits and a columnar engine is profiled against those limits.

## ADR-003 — SQLite and local files

- Status: accepted
- Decision: `data/workspace.sqlite3` stores job rows and status events. Bytes are stored under `data/jobs/<uuid>/` with generated names.
- Alternatives: Postgres or object storage. Not needed for a single local workspace.
- Revisit when: multiple users need shared durable storage.

## ADR-004 — Rules first, model optional

- Status: accepted
- Decision: natural language is interpreted by a local rule planner that can only emit registered operations. An optional OpenAI-compatible endpoint may answer a clarification by picking one of the offered option ids. It is not configured by default and is not called unless `CLEANING_AI_BASE_URL`, `CLEANING_AI_API_KEY`, and `CLEANING_AI_MODEL` are all set.
- Alternatives: require a paid model, or let the model emit free-form code. Rejected.
- Revisit when: the rule planner produces too many clarifications on real requests and a schema-constrained model is worth the privacy cost.

## ADR-005 — XLS and XLSB are rejected

- Status: accepted
- Decision: OLE compound files and `.xls` / `.xlsb` names are rejected. Bytes are not renamed to XLSX.
- Revisit when: a maintained reader has tests for a safe conversion path.

## ADR-006 — Patch the workbook, do not rebuild it

- Status: accepted
- Decision: XLSX output loads the original package and writes changed cells, then deletes approved rows. This keeps formulas that were not edited. CSV is rewritten as UTF-8 with BOM and CRLF.
- Trade-off: openpyxl does not promise to preserve every Excel feature. Untested features are listed as limitations, not as supported.
- Revisit when: a fixture proves a required feature is dropped.

## ADR-007 — Duplicates are marked unless removal is approved

- Status: accepted
- Decision: exact duplicates are labeled. Removal keeps the first row and only runs after `approve_destructive`. Similar names are not merged. Empty keys are not grouped.
- Revisit when: a survivorship policy is specified for conflicting non-identical records.

## ADR-008 — Calendars are not switched implicitly

- Status: accepted
- Decision: Jalali conversion uses `jdatetime` 5.3.0. Ambiguous numeric dates stay unchanged. A request that does not name a target calendar standardizes each detected calendar in place.
- Known pairs locked in tests: 1403-01-01 = 2024-03-20, and 1403-12-30 is valid while 1404-12-30 is not.
- Revisit when: another calendar library replaces jdatetime.

## ADR-009 — CSV formula guard changes some text

- Status: accepted
- Decision: on CSV output, text starting with `=`, `+`, `@`, tab, carriage return, or a non-numeric minus is prefixed with an apostrophe. A plain negative number such as `-12` is unchanged. The operation is part of the visible plan. It is not claimed to be safe for every spreadsheet consumer.
- Revisit when: a different consumer-specific policy is required.
