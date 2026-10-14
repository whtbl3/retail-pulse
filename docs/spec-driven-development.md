# Spec-driven development in this repo

This page explains step 3 of the SDLC roadmap: every new feature starts from a short written spec that a
person reviews before any code is written. The working rules are in [`specs/README.md`](../specs/README.md);
this page explains why they look the way they do and how to try GitHub Spec Kit against them.

## Why write a spec first

With an AI agent writing most of the code, typing is no longer the slow part. The slow part is finding out
late that the code solves the wrong problem. A spec moves that discovery to the start, where fixing it
means editing a paragraph instead of reworking a PR.

The spec also gives Claude something stable to work against. Without it, every session re-derives the
intent from the chat, and small misunderstandings pile up. With it, Claude reads `spec.md` and checks its
work against the acceptance criteria.

> **Read more:** [The AI-native SDLC playbook](https://claude.com/resources/articles/the-ai-native-sdlc-playbook)
> (the plan, design and build stages this follows),
> [Martin Fowler: Understanding spec-driven development](https://martinfowler.com/articles/exploring-gen-ai/sdd-3-tools.html)
> (spec-first, spec-anchored and spec-as-source).

## What level of "spec-driven" this is

Fowler's article describes three levels:

| Level | Meaning | Here? |
| --- | --- | --- |
| Spec-first | Write a spec before the code, then mostly forget it | Partly |
| Spec-anchored | Keep the spec and update it when the feature changes | **Yes** |
| Spec-as-source | The spec is the only thing people edit; code is generated from it | No |

This repo is **spec-anchored**. `docs/Project-Spec.md` is the long-lived spec for the whole project, and each
`specs/NNN-*/` folder records one change to it. Spec-as-source is not a goal: SQL models and SCD2 logic need
to be read and reviewed as code.

## The pieces

| Piece | File | What it does |
| --- | --- | --- |
| Intent issue | `.github/ISSUE_TEMPLATE/intent.yml` | A GitHub issue form: problem, outcome, out of scope. Forces "what" before "how" |
| Spec templates | `specs/_template/` | `spec.md`, `plan.md`, `tasks.md` with the sections every feature needs |
| `/new-feature` skill | `.claude/skills/new-feature/SKILL.md` | Tells Claude how to fill the templates, and where to stop for review |
| Process | `specs/README.md` | The flow from intent to merged PR, and when to skip it |

The skill has `disable-model-invocation: true`, so Claude never starts it on its own. You type
`/new-feature` when you want it. A skill is advice Claude follows, not a hard rule: the review stops depend
on you reading the spec before approving it.

The spec template has sections that matter for this project in particular: "Data contract changes" (new
columns, grain or load strategy) and "Decisions" (anything that changes a Final decision in spec §17). The
plan template asks for "Risks and rollback" because some mistakes here, like losing RAW history, cannot be
undone.

## Trying GitHub Spec Kit

[Spec Kit](https://github.com/github/spec-kit) is GitHub's toolkit for the same idea. It ships agent skills
(`/speckit-specify`, `/speckit-plan`, `/speckit-tasks`, `/speckit-implement` and more) and keeps its files in
`.specify/` and `specs/`. The templates here use the same file names (`spec.md`, `plan.md`, `tasks.md`), so the
output of both is easy to compare.

Spec Kit is **not installed in this repo**. To try it without changing `main`:

```bash
git switch -c try/spec-kit            # throwaway branch, never merged
uv tool install specify-cli           # installs the `specify` command
specify init --here --integration claude
```

With `--integration claude`, Spec Kit installs its skills into `.claude/skills/` next to `new-feature`. That is
why the trial stays on its own branch. The `--integration` key for Claude Code and the flags for an existing project may change between releases.
Check the [existing-project guide](https://github.github.io/spec-kit/guides/existing-projects.html) and the
[integrations list](https://github.github.io/spec-kit/reference/integrations.html) before running it.

Then run one small feature through both flows and compare:

- How long it takes to get to an approved spec.
- Whether Spec Kit's `/speckit-clarify` and `/speckit-analyze` catch problems the light template misses.
- How much of what it generates you would actually keep.

If Spec Kit wins, adopting it is a separate PR that replaces `specs/_template/` and the `/new-feature` skill.

> **Read more:** [Spec Kit quickstart](https://github.github.io/spec-kit/quickstart.html).
