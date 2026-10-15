# Code review in this repo

This page explains step 4 of the SDLC roadmap: what a pull request is checked for, by whom, and in what
order. The rules themselves are in [`REVIEW.md`](../REVIEW.md) and
[`.claude/agents/spec-reviewer.md`](../.claude/agents/spec-reviewer.md).

## Four layers, each with one job

| Layer | Who | Checks | Can it block a merge? |
| --- | --- | --- | --- |
| CI | GitHub Actions (`lint`, `test`, `dbt-slim-ci`) | Lint, format, pytest, dbt build and tests | Yes, through required checks |
| Spec check | `spec-reviewer` subagent, feature PRs only | Every requirement and acceptance criterion is met and tested | No, it reports |
| Policy review | Claude or a person, following `REVIEW.md` | Rules that protect RAW, SCD2 history, money and secrets | No, it reports |
| Approval | You | Does the change do what was intended, and is the risk acceptable? | Yes |

Each layer skips what the one before it already covers. `REVIEW.md` tells reviewers not to report lint or
test failures, because CI catches those. That leaves the human reviewer with the questions only a person
can answer: is this the right change, and is it safe to merge?

> **Read more:** [The AI-native SDLC playbook](https://claude.com/resources/articles/the-ai-native-sdlc-playbook),
> Stage 5 (review runs in both directions; human attention moves to intent and risk).

## `REVIEW.md`: what counts as Important

Without guidance, a reviewer, human or Claude, treats a renamed variable and a deleted RAW table with the
same weight. `REVIEW.md` fixes the scale for this project:

- **Important** means data loss, corrupted history or wrong numbers: a `replace` on `product` RAW, money
  as `float`, schema and ORM drifting apart, a Final decision changed without §17.
- **Nit** is everything else, capped at five per review.
- **Do not report** what CI already enforces, generated files and known cleanup items.

`REVIEW.md` sits at the repo root, the place Claude's managed
[Code Review](https://code.claude.com/docs/en/code-review) reads it from. That service is not enabled here
yet; today the file is used when you ask Claude to review a PR and by people reviewing by hand.

## `spec-reviewer`: did we build what the spec says?

A subagent is a separate Claude with its own instructions, its own tools and a fresh context window. That
fresh context is the point: the session that wrote the code believes it is correct, while a new context
reads only the spec and the diff.

The subagent:

- finds `specs/NNN-*/` from the branch name `feat/NNN-*`;
- marks each requirement and acceptance criterion Met, Partly or Missing, each with a `file:line`;
- lists plan drift (files changed that `plan.md` did not mention);
- checks the bookkeeping (`Status: Implemented`, §17 updated when the spec changes a decision);
- runs `make check`.

It cannot edit files (`disallowedTools: Edit, Write`). It reports, and the main session fixes.

To run it, in Claude Code:

```text
Use the spec-reviewer subagent on this branch
```

or type `@agent-spec-reviewer` to make sure that subagent is the one used. A made-up report for a CDC branch
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

> **Read more:** [Create custom subagents](https://code.claude.com/docs/en/sub-agents),
> [Code Review: REVIEW.md](https://code.claude.com/docs/en/code-review).

## In a pull request

The PR template has a **Review** section: tick that you self-reviewed against `REVIEW.md`, and for a
feature PR paste the `spec-reviewer` report. No criterion should be Missing when the PR is opened.

## Later

Two upgrades are possible once there is a reason for them:

- Enable managed Code Review, or run `claude-code-action` in CI, so every PR gets a `REVIEW.md` review
  without anyone asking. That needs an admin setting or an API key secret.
- Add `test` to the required checks in the `protect-main` ruleset, so a red test job blocks the merge.
