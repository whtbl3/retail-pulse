# Code review in this repo

This page explains step 4 of the SDLC roadmap: what a pull request is checked for, by whom, and in what
order. The rules themselves are in [`REVIEW.md`](../REVIEW.md).

## Four layers, each with one job

| Layer | Who | Checks | Can it block a merge? |
| --- | --- | --- | --- |
| CI | GitHub Actions (`lint`, `test`, `dbt-slim-ci`) | Lint, format, pytest, dbt build and tests | Yes, through required checks |
| Spec check | The PR author, feature PRs only | Every requirement and acceptance criterion is met and tested | No, it reports |
| Policy review | A reviewer, following `REVIEW.md` | Rules that protect RAW, SCD2 history, money and secrets | No, it reports |
| Approval | You | Does the change do what was intended, and is the risk acceptable? | Yes |

Each layer skips what the one before it already covers. `REVIEW.md` tells reviewers not to report lint or
test failures, because CI catches those. That leaves the human reviewer with the questions only a person
can answer: is this the right change, and is it safe to merge?

## `REVIEW.md`: what counts as Important

Without guidance, a reviewer treats a renamed variable and a deleted RAW table with the same weight.
`REVIEW.md` fixes the scale for this project:

- **Important** means data loss, corrupted history or wrong numbers: a `replace` on `product` RAW, money
  as `float`, schema and ORM drifting apart, a Final decision changed without §17.
- **Nit** is everything else, capped at five per review.
- **Do not report** what CI already enforces, generated files and known cleanup items.

## Spec check: did we build what the spec says?

Before a feature PR is opened, the branch is read against its spec with fresh eyes: only the spec and the
diff, not the reasoning that produced the code. The check:

- finds `specs/NNN-*/` from the branch name `feat/NNN-*`;
- marks each requirement and acceptance criterion Met, Partly or Missing, each with a `file:line`;
- lists plan drift (files changed that `plan.md` did not mention);
- checks the bookkeeping (`Status: Implemented`, §17 updated when the spec changes a decision);
- runs `make check`.

It only reports; fixes go in follow-up commits on the same branch. A made-up report for a CDC branch
looks like this:

```text
Ready with gaps

| Item | Status  | Evidence                                              |
| ---- | ------- | ----------------------------------------------------- |
| R1   | Met     | src/.../cdc.py:40, tests/test_cdc.py:12               |
| AC2  | Partly  | dbt/models/intermediate/int_product_scd2.sql:18, no test |

Plan drift: Makefile changed, not in plan.md
Bookkeeping: spec Status is still Approved
make check: 61 passed
```

## In a pull request

The PR template has a **Review** section: tick that you self-reviewed against `REVIEW.md`, and for a
feature PR paste the spec check. No criterion should be Missing when the PR is opened.

## Later

Two upgrades are possible once there is a reason for them:

- Run an automated `REVIEW.md` review in CI, so every PR gets one without anyone asking. That needs an
  API key secret.
- Add `test` to the required checks in the `protect-main` ruleset, so a red test job blocks the merge.
