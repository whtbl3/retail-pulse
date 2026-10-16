# Feature specs

Each new feature gets its own folder here, `specs/NNN-short-name/`, before any code is written.
The folder holds three files, copied from [`_template/`](_template/):

| File | Answers | Written when |
| --- | --- | --- |
| `spec.md` | **What** and **why**: problem, scope, requirements, acceptance criteria | First, then reviewed by a person |
| `plan.md` | **How**: approach, files, risks, test strategy | After the spec is Approved |
| `tasks.md` | **In what order**: small tasks, tests first | After the plan is reviewed |

`docs/Project-Spec.md` stays the source of truth for the whole project. A feature spec describes a change
to it. When the feature is merged, the affected Project-Spec sections are updated in the same PR, and the
feature spec stays here as the record of why the change was made.

## The flow

1. **Intent.** Open a GitHub issue with the "Intent" template: the problem, the outcome and what is out
   of scope. No solution yet.
2. **Spec.** Copy `_template/` to `specs/NNN-short-name/`, draft `spec.md` and list open questions.
   Answer them and set `Status: Approved`.
3. **Plan and tasks.** Draft `plan.md` and `tasks.md` from the approved spec, then review them.
4. **Build.** Work through `tasks.md` on a `feat/NNN-short-name` branch, test first.
5. **Review and merge.** Before the PR, a spec check (see [`docs/code-review.md`](../docs/code-review.md))
   reads the branch against the spec and reports each acceptance criterion as Met, Partly or Missing. The PR links the spec folder and that
   report. Reviewers follow [`REVIEW.md`](../REVIEW.md) and check the code against the acceptance
   criteria, not just the diff. `Status` becomes `Implemented` in the same PR.

Steps 2 and 3 end with a person reading the result. That review is the point of the process: a wrong
spec caught early costs a few lines, a wrong spec caught in review costs the whole PR.

## When to skip it

Bug fixes, docs, refactors with no behavior change and anything whose diff fits in one sentence go
straight to a PR. A spec is for changes to behavior, data contracts or a Final decision.

## Numbering

`NNN` is the next free three-digit number in this folder (`001`, `002`, ...). The short name is a few
lowercase words joined by hyphens, for example `001-postgres-cdc`. Numbers are never reused.
