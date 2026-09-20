# NOVA-QL — Privacy-Preserving, Carbon-Aware SQL CLI

A PostgreSQL wrapper CLI that adds differential privacy, role-based PII
masking, and per-query carbon-emission tracking on top of ordinary SQL
queries.

## What it does

You run SQL through a `SQL >` prompt. Depending on your role and the
active mode, results come back noised (differential privacy), masked
(PII redaction), both, or neither — and every query reports its execution
time, epsilon, remaining privacy budget, and estimated CO2 emitted.

## Roles

| Role | Privacy budget | Allowed modes | Masking config access |
|---|---|---|---|
| `admin` | 999.0 (effectively unlimited) | `raw`, `private`, `audit` | Full — `\dmc` wizard |
| `analyst` | 10.0 | `private` only | None — masking always on |
| `auditor` | 15.0 | `private`, `audit` | None — masking always on |

Role and username are chosen at login; a fresh `DifferentialPrivacy`
instance and budget are created per session.

## Differential privacy

`private` mode applies Laplace noise (`scale = sensitivity / epsilon`) to
aggregate queries (`COUNT`, `SUM`, `AVG`) detected by a keyword scan of the
SQL text. Every private query deducts `epsilon` from that user's session
budget; once exhausted, further private queries are refused.

- `raw` — admin-only, exact results, no budget deducted.
- `private` — default, noised results only.
- `audit` — both the raw result and the exact noise applied, for
  transparency/inspection.

Sensitivity is currently a **fixed constant per aggregate type** (`1` for
COUNT/AVG, `100` for SUM), not derived from actual column bounds —
correct for a working demo, not yet a general-purpose sensitivity
estimator. Non-aggregate queries (`SELECT *`, etc.) bypass DP entirely and
are returned as-is.

## PII masking

Independent of DP, applied after it. Admin toggles which columns are
masked via `\dmc`, an interactive wizard that reads the live schema from
`information_schema.columns` so it works against any table, not a
hardcoded list. Choices persist to `backend/.mask_config.json`. Masking
shows the last 4 characters and redacts the rest (`********9012`); admin
always sees unmasked values.

## Carbon tracking

Every query is wrapped in a CodeCarbon `EmissionsTracker` start/stop pair;
`\metrics` prints a live panel with total queries, cumulative CO2, average
execution time, current epsilon, remaining budget, and masking status for
the session.

## Interface

A Rich-rendered terminal CLI: an ASCII banner and a startup diagnostics
panel (DB connection, DP status, masking status, role) print once at
login, followed by a `SQL >` prompt loop with keyword/table-name
autocomplete (`prompt_toolkit`) and persistent command history
(`.safe_sql_history`). `\metrics` and query results print as panels
in the scroll — there's no persistent split-pane layout.

### Commands

| Command | Effect |
|---|---|
| `\epsilon <value>` | Set noise level (0.01–10.0; lower = more private) |
| `\mode raw\|private\|audit` | Switch privacy mode (role-restricted) |
| `\dmc` | Admin-only masking configuration wizard |
| `\metrics` | Live session metrics panel |
| `\help` | Full command reference |
| `\logout` | Return to login prompt without exiting |

## Setup

```bash
python -m venv venv
venv\Scripts\activate        # or source venv/bin/activate on macOS/Linux
pip install -r requirements.txt
```

Set your own DB connection in `backend/main.py` (the `db_config` dict) —
don't reuse the placeholder in this repo. Create a Postgres database and
point it there; the app works against any schema, since the masking
wizard discovers columns at runtime.

```bash
python -m backend.main
```

## Repository layout

```
backend/
  main.py           CLI orchestration, role config, command dispatch, masking engine
  privacy.py         DifferentialPrivacy — Laplace mechanism, per-user budgets
  db.py               Thin psycopg2 wrapper
  eco_scheduler.py     CodeCarbon EmissionsTracker start/stop wrapper
  config.py            Placeholder settings — not currently read by main.py
  .mask_config.json    Persisted masking selections
  .safe_sql_history     Prompt history for the interactive session
utils/
  query_buffer.py       Not currently used by the app
  energy_tracker.py     Not currently used by the app
```

## Known limitations

- Aggregate detection is a keyword scan (`"count("` etc. in the lowercased
  query string), not a SQL parser — a column literally named `count` in a
  non-aggregate query would misfire.
- DP sensitivity values are fixed per aggregate type, not computed from
  actual column bounds.
- `utils/query_buffer.py` and `utils/energy_tracker.py` are present but
  unused — no query batching or standalone energy polling currently runs.
- Single hardcoded DB connection in `main.py`; no `.env`/config-file based
  connection setup.