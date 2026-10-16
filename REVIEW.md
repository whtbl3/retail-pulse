# Review instructions

How to review a pull request in this repo. Project context lives in `docs/Project-Spec.md`; this file only says what to flag and how hard.

## What Important means here

Important is reserved for findings that would lose data, corrupt history or ship wrong numbers:

- Anything that can delete or overwrite Snowflake RAW: `replace`, `merge` or `refresh="drop_sources"` on
  `product` or `employee` in dlt, a new caller of `make seed`, `reseed`, `db-reset` or `clean-raw`.
- SCD2 built anywhere other than dbt window functions over RAW: `dbt snapshot`, history columns in the
  Python generators, or a change to how `valid_from` / `valid_to` are derived.
- Money written as `float`, or a money column that is not `NUMERIC(12, 2)` / `Decimal`.
- `infras/postgres/init/01_schema.sql` and `src/retail_pulse/oltp/models.py` no longer agree.
- A fact or mart that counts transactions other than `completed`.
- A secret, key or real `.env` / `profiles.yml` / `secrets.toml` in the diff.
- A change to a Final decision in Project-Spec §17 without the §17 row, the acceptance criteria and the
  docs updated in the same PR.
- Behavior that contradicts the PR's own spec (`specs/NNN-*/spec.md`) when the PR has one.

Everything else is Nit at most: naming, style, wording, refactoring ideas, missing comments.

## Always check

- **Spec compliance.** If the PR touches `specs/` or its branch is `feat/NNN-*`, every requirement and
  acceptance criterion in that spec is met by code and proved by a test or a stated manual check. Report
  each one that is not. Files changed that `plan.md` does not mention are worth one line, not a finding.
- **Tests for new behavior.** New Python behavior has a pytest; new dbt models have column tests in the
  folder's `___models.yml`; a bug fix has a test that fails without the fix.
- **dbt conventions** in `docs/dbt-conventions.md`: unknown members use `-2`, fact joins `COALESCE` missing
  keys to `-2`, `date_key` / `time_key` use `var('local_tz')`.
- **Docs follow behavior.** A new command or setting appears in `make help` and the relevant
  `docs/phases/` or `docs/design/` page.
- **English only** in code, docs, dbt descriptions and commit messages.

## Verification bar

Behavior claims need a `file:line` in the diff or the source, not an inference from a name. If you cannot
point to the line, say "could not confirm" instead of posting a finding.

## Do not report

- What CI already enforces: ruff lint and format, pytest failures, `dbt parse` and dbt test failures.
- Files under `dbt/dbt_packages/`, `dbt/target/`, `uv.lock` and images in `assets/`.
- Trailing whitespace in existing dbt files (a separate cleanup is planned).

## Shape of the review

- Open with one line: `N important, M nits`, or `No blocking issues` when there are no Important findings.
- Report at most five Nits; mention the rest as a count.
- On a re-review, report only new Important findings.
- Findings do not approve or block the PR. A person approves it.
