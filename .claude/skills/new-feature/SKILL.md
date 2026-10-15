---
name: new-feature
description: Start a new feature the spec-driven way. Creates specs/NNN-name/ from the template and drafts spec.md, or with "plan NNN" drafts plan.md and tasks.md from an approved spec.
argument-hint: "<issue number or one-line intent> | plan <NNN>"
disable-model-invocation: true
---

# New feature

Arguments: `$ARGUMENTS`

The process is described in `specs/README.md`. Read it first. Each stage below ends by stopping for a
person to review. Never write code, plans or tasks for a spec that is not `Status: Approved`.

## Stage 1: spec (arguments are an issue number or an intent)

1. If the argument is an issue number, read that GitHub issue. Otherwise use the text as the intent.
2. Read the parts of `docs/Project-Spec.md` the intent touches. Always read §6 (scope), §16
   (Definition of Done) and §17 (decision log). If the intent is out of scope under §6.2 or conflicts
   with a Final decision in §17, say so and stop before creating anything.
3. Pick the next free number: the highest `NNN` in `specs/` plus one, three digits. Pick a short name of
   two to four lowercase words joined by hyphens.
4. Create the branch `feat/NNN-short-name` from an up-to-date `main`.
5. Copy `specs/_template/spec.md` to `specs/NNN-short-name/spec.md` and fill it in:
   - Describe **what** and **why** only. No file names, libraries or SQL in the spec.
   - Every requirement must be testable. Every acceptance criterion is Given / When / Then.
   - List every Project-Spec section the feature would change.
   - Fill "Data contract changes" and "Decisions" honestly, including "None".
   - Anything you had to guess goes under "Open questions" with `[NEEDS CLARIFICATION]`. Do not
     invent answers to make the spec look complete.
6. Stop. Show the open questions as a short numbered list the person can answer in one word each,
   with your recommendation marked. Do not continue to stage 2 in the same turn.

When the person answers, update the spec, remove the answered questions, and set `Status: Approved`
only when they say it is approved.

## Stage 2: plan and tasks (arguments are `plan NNN`)

1. Read `specs/NNN-*/spec.md`. If its status is not `Approved`, stop and say what is missing.
2. Read the code and docs the spec touches. Follow `CLAUDE.md` and `.claude/rules/`.
3. Fill `plan.md` from the template:
   - Every requirement and acceptance criterion maps to something in the approach and the test table.
   - Under "Risks and rollback", call out anything that touches Snowflake RAW, SCD2 history or needs a
     full refresh. Commands that delete RAW are never part of a plan without the person asking.
   - List the Project-Spec sections and docs to update.
4. Fill `tasks.md`: small ordered tasks, each test before the code it proves, last task is docs.
5. Stop and ask for review of both files. Implementation starts only after the person says so.

## Stage 3: build

Work through `tasks.md` in order, ticking tasks off. Run `make check` before calling the feature done.
Then run the `spec-reviewer` subagent and fix what it reports as Missing or Partly before opening the PR.
In the PR, link the spec folder under "Why", set the spec to `Status: Implemented`, and update the
affected Project-Spec sections in the same PR.
