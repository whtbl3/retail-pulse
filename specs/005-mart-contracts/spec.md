# 005: Enforced contracts on the marts

- Status: Approved (2026-10-15, PhucLH)
- Intent: none (requested by the project owner, 2026-10-15, as a next step towards a senior-level
  portfolio)
- Project-Spec sections affected: §10 (mart contract rule), §13.1, §13.3, §17

## Problem

Preset and the semantic layer read the marts by column name and type. Today a change that renames,
drops or retypes a mart column still builds and passes CI, because the dbt tests check values, not the
shape of the table. The break shows up only when someone opens a dashboard chart after the 23:00 run.

## Goal

A change that alters the column names or types of a mart fails in CI, before it reaches production,
and the person making it sees which column changed. Adding a column on purpose is a one-line change
to the declared shape, reviewed in the same PR.

## Scope

In scope:

- All 10 tables in `MARTS`, dimensions and facts (Q1).
- A declared name and type for every column of those tables, checked on every build.
- Not-null rules that the warehouse can enforce, where the column is already tested as not null.
- A check that a new mart cannot be added without a declared shape.

Out of scope:

- Staging and intermediate models (no consumer outside dbt).
- Model versioning (several live versions of one mart).
- Any change to data, grain, keys, load strategy, RAW or SCD2 history.
- Uniqueness or foreign-key rules enforced by the warehouse: Snowflake records them but does not
  enforce them, so the existing dbt tests stay.

## Requirements

1. **R1:** Every mart in scope declares each of its columns with a name and a data type.
2. **R2:** A build fails when a mart in scope returns a column that is not declared, misses a
   declared column, or returns a column of a different type than declared. The failure names the
   column.
3. **R3:** Columns already tested as not null are declared not null, so the warehouse rejects a null
   on write.
4. **R4:** The marts keep exactly their current columns and types: declaring the contract changes no
   data and no column a reader can see.
5. **R5:** The incremental sales fact keeps loading incrementally; the contract does not force a full
   refresh on a normal run.
6. **R6:** A mart added later without a declared shape fails a check in CI.
7. **R7:** The docs say what a contract is, which marts have one, and how to change a mart's shape on
   purpose.

## Acceptance criteria

- **AC1:** Given the marts in scope, when the project is parsed, then each one has every column
  declared with a type and its contract turned on.
- **AC2:** Given a branch that renames a column in a mart's SQL without changing its declared shape,
  when CI builds it, then the build fails and the message names the column.
- **AC3:** Given a branch that changes a column's type in a mart's SQL, when CI builds it, then the
  build fails.
- **AC4:** Given this feature merged, when the next 23:00 run builds production, then every mart has
  the same columns, types and row counts as the day before.
- **AC5:** Given the incremental sales fact, when the 23:00 run loads new sales, then it merges them
  without rebuilding the table.
- **AC6:** Given a new mart with no declared shape, when CI runs, then a check fails and names it.
- **AC7:** Given the docs, when a reader wants to add a column to a mart, then they find the steps.

## Data contract changes

No table, column, grain, key or load strategy changes. The current shape of the marts in scope
becomes declared and enforced.

## Decisions

| Decision | Status | Rationale |
| --- | --- | --- |
| Mart shapes (column names and types) are enforced on every build | Proposed | Preset and the semantic layer depend on them; CI should catch a break, not a dashboard reader |
| Uniqueness and relationships stay dbt tests | Proposed | The warehouse does not enforce them; only not-null is enforced |

## Answers to open questions

Answered by the owner on 2026-10-15 (decision card in the project thread).

- **Q1, which marts:** all 10 marts, dimensions and facts.

## Open questions

None.
