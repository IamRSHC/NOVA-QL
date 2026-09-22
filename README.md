# NOVA-QL — Privacy-Preserving, Carbon-Aware SQL CLI

A PostgreSQL wrapper CLI that adds differential privacy, role-based PII
masking, and per-query carbon-emission tracking on top of ordinary SQL
queries — built as a research-oriented exploration of what it takes to
make ad-hoc SQL access provably privacy-safe and carbon-accountable at the
same time, rather than treating those as separate concerns bolted on
after the fact.

## Table of contents

- [What it does](#what-it-does)
- [Roles and permissions](#roles-and-permissions)
- [Differential privacy](#differential-privacy)
- [PII masking](#pii-masking)
- [Carbon tracking](#carbon-tracking)
- [Interface](#interface)
- [Query lifecycle](#query-lifecycle)
- [Setup](#setup)
- [Repository layout](#repository-layout)
- [Current implementation status](#current-implementation-status)
- [Roadmap](#roadmap)
- [Known limitations](#known-limitations)

## What it does

You log in with a username and one of three roles, then run SQL through a
`SQL >` prompt exactly as you would in `psql`. What's different is what
happens between your query hitting Postgres and the result reaching your
terminal:

1. The query executes against the real database, unmodified.
2. If it's an aggregate query (`COUNT`, `SUM`, `AVG`) and your session is
   in `private` or `audit` mode, Laplace noise is added to the numeric
   result before you see it — a differential-privacy guarantee that no
   single row's presence or absence measurably changes what you can infer
   from the output.
3. Independently, any column an admin has flagged as sensitive is masked
   for non-admin roles, regardless of DP mode.
4. Every query's wall-clock execution time and estimated CO2 emissions
   (via CodeCarbon, which samples CPU/GPU/RAM power draw during
   execution) are tracked and available on demand via `\metrics`.

None of this requires the underlying database or its schema to be
modified — masking and privacy are applied entirely in the response path.

## Roles and permissions

| Role | Privacy budget | Allowed `\mode` values | `\dmc` masking wizard |
|---|---|---|---|
| `admin` | `999.0` (not literally infinite — a large ceiling meant to function as unlimited in practice) | `raw`, `private`, `audit` | Full access |
| `analyst` | `10.0` | `private` only | No access — masking always active |
| `auditor` | `15.0` | `private`, `audit` | No access — masking always active |

Role and username are entered at login (no password check against the
role itself — this is a research prototype's access model, not a
production auth system). A fresh `DifferentialPrivacy` instance and a
fresh privacy budget are created per session; nothing persists across
logins except the masking configuration and the CodeCarbon totals reset
each session too.

## Differential privacy

Implemented in `backend/privacy.py` as a hand-rolled NumPy Laplace
mechanism — not currently using the `diffprivlib` library, despite it
being listed in `requirements.txt`. See
[Current implementation status](#current-implementation-status) below for
exactly what that means in practice.

**Mechanism**: for a numeric aggregate result, noise is drawn from a
Laplace distribution with scale `sensitivity / epsilon` and added to the
value. Lower epsilon → more noise → stronger privacy, weaker accuracy.
This is the textbook Laplace mechanism for `epsilon`-differential privacy.

**Sensitivity**: currently a *fixed constant per aggregate type*, not
computed from the actual data:

| Aggregate | Sensitivity used | Basis |
|---|---|---|
| `COUNT` | `1` | Adding/removing one row changes a count by at most 1 — this one is actually correct as a general bound. |
| `SUM` | `100` | An assumed maximum single-row contribution. Not derived from the column's real range — a genuinely wrong sensitivity for any column whose values can exceed 100, and an over-conservative (unnecessarily noisy) one for columns that can't. |
| `AVG` | `1` | Simplified placeholder, not sensitivity-derived from bounded-value theory for averages. |

**Query detection**: `is_aggregate_query()` does a lowercase substring
check for `"count("`, `"sum("`, `"avg("` in the query text — not a SQL
parser. A query containing those substrings in an unrelated context (a
column literally named `count`, a string literal containing the word)
would misfire.

**Budget mechanics**: each user is registered with a starting budget
(from their role's table above). Every query in `private` or `audit` mode
against an aggregate deducts `epsilon` from that budget. `raw` mode and
non-aggregate queries never touch the budget. Once a user's remaining
budget is less than the current epsilon, further private/audit queries on
aggregates raise an exception and are refused — this is what actually
enforces the privacy guarantee over repeated querying, not just the noise
itself.

**Modes**:
- `raw` — admin-only. Exact results, no noise, no budget deduction.
- `private` — default for everyone. Noised results only; raw values are
  never returned to the client.
- `audit` — both the raw result and the exact noise vector applied are
  returned, for transparency and inspection. Still deducts budget like
  `private` does.

## PII masking

Independent layer from DP, applied after it, to any result (aggregate or
not). Admin runs `\dmc` to open an interactive wizard that:

1. Queries `information_schema.columns` live, so it works against
   whatever schema is actually loaded — nothing is hardcoded to a
   particular table set.
2. Shows every table/column pair and whether it's currently masked.
3. Accepts a comma-separated list of columns to mask, `keep` to leave the
   configuration unchanged, or `none` to disable masking entirely.
4. Persists the choice to `backend/.mask_config.json` as a flat list of
   lowercased column names — masking is column-name-based, not
   table-scoped, so a column called `student_name` is masked in every
   table that has one.

At query time, masked columns show the last 4 characters with everything
before that replaced by `*` (`"123456789012"` → `"********9012"`).
Admin always sees unmasked values regardless of configuration; the
database itself is never modified — masking happens only in what's
displayed.

Default sensitive columns if no config file exists yet:
`aadhar_number`, `abc_id`.

## Carbon tracking

Every query is wrapped in a CodeCarbon `EmissionsTracker` start/stop
pair (`log_level="error", save_to_file=False` — no CodeCarbon log files
or CSVs are written to disk; everything stays in-memory for the session).
`\metrics` prints a live panel: total queries run, cumulative CO2 in kg,
average execution time, current epsilon, remaining budget, and masking
status — all scoped to the current login session, reset on `\logout`.

## Interface

A `rich`-rendered terminal CLI. On login: an ASCII "NOVA QL" banner, then
a one-time startup diagnostics panel (DB connection status, DP readiness,
masking status, energy tracker readiness, username, role). After that,
it's a normal scrolling `SQL >` prompt loop with:

- SQL-keyword and live table-name autocomplete (`prompt_toolkit`'s
  `WordCompleter`, seeded from `information_schema.tables` at login)
- Persistent command history across sessions, via `FileHistory`
- Query results, `\metrics` panels, and masking wizard output all print
  as `rich` panels/tables in the normal scroll

There is no persistent split-pane layout or sidebar — nothing in the code
uses `rich.layout.Layout` or `rich.live.Live`. Anything you've heard or
read describing a "70/30 split-screen with a persistent sidebar" is not
what this build does; that appears to have been a documentation error in
an earlier draft, not a removed feature.

### Command reference

| Command | Effect | Restriction |
|---|---|---|
| `\epsilon <value>` | Set noise level for this session (valid range 0.01–10.0; lower = more private, more noise) | None |
| `\mode raw\|private\|audit` | Switch privacy mode | Must be in the role's `allowed_modes` |
| `\dmc` | Launch the masking configuration wizard | Admin only |
| `\metrics` | Print the live session metrics panel | None |
| `\help` | Print the full command reference | None |
| `\logout` | End the session, return to the login prompt (role/budget/mode all reset) | None |
| `exit` | Quit the application entirely | None |

## Query lifecycle

```
User types SQL at the SQL > prompt
        │
        ▼
eco_scheduler.start_tracking()   ── CodeCarbon EmissionsTracker.start()
        │
        ▼
db_interface.execute_query(sql)  ── raw psycopg2 execute + fetchall
        │
        ▼
dp_instance.process_result(username, sql, result)
        │
        ├─ mode == "raw"        → return result unmodified, no budget deducted
        ├─ not an aggregate     → return result unmodified, no budget deducted
        └─ aggregate + private/audit
                │
                ▼
           deduct_budget(username)   ── raises if budget < epsilon
                │
                ▼
           apply_laplace(value, sensitivity)  per numeric cell
                │
                ▼
           private mode → {private: noised}
           audit mode   → {raw: exact, private: noised, noise: [...]}
        │
        ▼
eco_scheduler.stop_tracking()    ── EmissionsTracker.stop(), returns kg CO2
        │
        ▼
apply_masking(private_result, columns, role, sensitive_columns)
        │   (admin bypasses; non-admin gets flagged columns redacted)
        ▼
render as a rich.Table, print execution time / epsilon / budget / CO2 panel
```

## Setup

**Prerequisites**: Python 3.9+, a running PostgreSQL server.

```bash
python -m venv venv
venv\Scripts\activate        # macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
```

Set your own connection details directly in `backend/main.py` (the
`db_config` dict near the start of `main()`) before running — there's
currently no `.env`/config-file-based connection setup (see
[Roadmap](#roadmap)). Point it at any Postgres database; the app
discovers schema at runtime, so no specific table structure is required
beyond it existing.

```bash
python -m backend.main
```

At the login prompt, enter any username and one of `admin` / `analyst` /
`auditor`.

## Repository layout

```
backend/
  main.py             CLI orchestration: login, command dispatch, masking
                        engine (mask_value, apply_masking), admin mask
                        wizard, startup diagnostics
  privacy.py            DifferentialPrivacy class — Laplace mechanism,
                        per-user budgets, mode handling
  db.py                  Thin psycopg2 wrapper — execute_query() with
                        commit/rollback handling
  eco_scheduler.py        CodeCarbon EmissionsTracker start/stop wrapper
  .mask_config.json        Persisted masking column selections (written
                        by the \dmc wizard, read on every login)
requirements.txt
```

## Current implementation status

Being direct about what's real versus aspirational, because the two have
drifted apart in past documentation of this project:

| Claimed in CV / earlier docs | Actually in the code |
|---|---|
| `diffprivlib` for differential privacy | **Not used.** `privacy.py` is a hand-rolled NumPy Laplace implementation. `diffprivlib` is listed in `requirements.txt` but never imported anywhere in the source. |
| `SciPy` for privacy/statistics | **Not used.** No `scipy` import anywhere in the codebase. Also listed in `requirements.txt`, also unused. |
| Sensitivity-aware noise scaling | **Partially true.** The *mechanism* is sensitivity-aware (`scale = sensitivity / epsilon`), but sensitivity itself is a fixed constant per aggregate type, not computed from real column bounds. |
| Professional split-screen CLI with persistent sidebar | **Not accurate.** It's a normal scrolling Rich CLI — see [Interface](#interface). |

What *is* real and working: role-based access control, budget-gated
Laplace noise with genuine per-user budget enforcement, live-schema-aware
PII masking with persistent admin configuration, and real per-query
CodeCarbon emissions tracking. The gap is specifically between the
current hand-rolled DP math and the more rigorous `diffprivlib`/`SciPy`
approach that was planned but not yet built.

## Roadmap

Not yet implemented — listed here as intent, not as features:

- **`diffprivlib` integration**: replace the hand-rolled Laplace mechanism
  with `diffprivlib`'s mechanisms, which come with tighter, better-tested
  privacy guarantees and support for mechanisms beyond Laplace (Gaussian,
  exponential) for different accuracy/privacy tradeoffs.
- **`SciPy`-based dynamic sensitivity estimation**: derive `SUM`/`AVG`
  sensitivity from the actual observed or declared bounds of a column
  (e.g., via `scipy.stats`) instead of the current fixed constants.
- **SQL-parser-based aggregate detection**: replace the substring scan
  with an actual SQL parser (e.g., `sqlparse` or `sqlglot`) so aggregate
  detection isn't fooled by column names or string literals.
- **Environment-variable / config-file-based DB connection**: move
  connection details out of a literal dict in `main.py`.

## Known limitations

- Aggregate detection is a lowercase substring scan, not a SQL parser —
  see above.
- DP sensitivity values are fixed per aggregate type, not derived from
  actual column bounds — `SUM`'s sensitivity of `100` is a real accuracy
  problem for columns whose values commonly exceed that.
- `diffprivlib` and `SciPy` are declared dependencies but currently
  unused — see [Current implementation status](#current-implementation-status).
- No SQL injection protection beyond whatever psycopg2's parameter
  handling gives implicitly — queries are passed through as raw text
  entered at the prompt, since the whole point of the tool is ad-hoc SQL
  access.
- Masking is by column name globally, not scoped per table — a column
  name reused across tables with different sensitivity would be masked
  or unmasked everywhere at once.
- DB connection details live directly in source (`main.py`), not in
  environment variables or a config file.

  ## License
All rights reserved. This repository is public for portfolio/demonstration 
purposes only. No permission is granted to copy, modify, or redistribute 
this code without explicit written consent from the author.