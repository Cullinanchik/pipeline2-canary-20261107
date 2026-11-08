# Pipeline 2 synthetic canary

This public repository contains only invented test application code and test instructions.
It has no production data or credentials. It exercises an isolated Development Pipeline controller.
Run locally: `python3 app.py --host 127.0.0.1 --port 18390`.
The `scripts/` pipeline entrypoints require the separately provisioned canary runtime on the test VPS.

## Run

`python3 app.py --host 127.0.0.1 --port 18390 [--db PATH]`

The default database is `var/inventory.sqlite3` on a local filesystem. SQLite
creates schema v1 and seeds Notebook=3, Pencil=5 once. Only Python's standard
library is required. Connections use explicit transactions, DELETE journals and
FULL synchronization. Newer schema versions are refused; existing v1 WAL files
are converted to DELETE without changing inventory.

## API

`GET /api/items` returns items ordered by id; `quantity` is available stock.

`POST /api/reservations` accepts exactly:
```json
{"item_id": 1, "quantity": 2, "idempotency_key": "order-42"}
```
`item_id` is an integer from 1 through 2^63-1; `quantity` is an integer from 1
through 1000000 (booleans are invalid). The key is a nonblank string of at most
128 Unicode characters, encodable as UTF-8, preserved exactly. The UTF-8 JSON
body must be at most 4096 bytes and contain exactly Content-Length bytes.
Duplicate JSON fields and duplicate Content-Length headers are rejected.

| Status | Meaning / error |
| --- | --- |
| 201 | Created: id, item_id, quantity, idempotency_key, created_at (UTC) |
| 200 | Same key and data: original reservation, identical response bytes |
| 400 | invalid_request: invalid JSON, fields, length or incomplete body |
| 404 | item_not_found; unknown POST route: not_found |
| 405 | method_not_allowed, with Allow: POST or GET |
| 409 | insufficient_stock or idempotency_key_conflict |
| 411 | length_required |
| 413 | payload_too_large |
| 503 | storage_busy, Retry-After: 1 |
| 500 | internal_error; transaction rolled back |

A failed attempt does not consume its key. Retry network failures or 503 with
the same key and data. Successful replay also works after stock exhaustion and
server restart. Different data with an existing key returns 409. Reservations
are permanent: no cancellation, expiration or reservation listing. GET
/api/reservations returns 405 Allow: POST; POST /api/items returns 405 Allow: GET.
The socket timeout for an incomplete body is 10 seconds. Chunked transfer is
unsupported. GET / and /health retain their existing behavior.

## Reset

Stop the server, then delete `var/inventory.sqlite3` together with
`var/inventory.sqlite3-journal` if present (use the chosen --db path instead
when customized). Never delete the journal alone: it is needed for crash
recovery. Restart to recreate the seed inventory.

## Rollback

Use `git revert` on the task commits. The old application does not read the
SQLite file. Keep it for a subsequent release or reset it as described above.
Change code versions using one database only while the server is stopped.

## Tests

Controller Verify runs `python3 -m unittest discover -s tests -v`.
During development use `scripts/agent-check --phase quick` or targeted checks,
e.g. `python3 -m unittest discover -s tests -p 'test_*.py' -k _ac6_ -v`.
