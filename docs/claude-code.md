# Working with Claude Code in this repo

This page explains the Claude Code configuration files in this repo.
This is step 1 of the SDLC development roadmap: give Claude a "memory" of the repo's conventions and automatic guardrails,
before the later steps (quality gates in CI, a spec for each feature, review, operations).

## Files and their roles

| File | What it is | When it is used |
|---|---|---|
| `CLAUDE.md` | General guidance: commands, easy-to-break rules, workflow, language | Claude reads it at the start of **every** session |
| `.claude/rules/dbt.md` | dbt-specific conventions | Loaded only when Claude reads or edits files in `dbt/` |
| `.claude/settings.json` | Permissions (allow, ask, deny) and hooks | Enforced by Claude Code; Claude cannot skip them on its own |
| `.claude/hooks/protect_secrets.py` | Hook that blocks edits to secret files | Before every time Claude edits or creates a file |
| `.claude/hooks/ruff_after_edit.py` | Hook that formats and lints Python files | After every time Claude edits a `.py` file |
| `.claude/agents/spec-reviewer.md` | Subagent that checks a branch against its spec, report only | When you ask for it, and in step 3 of `/new-feature` (see [code-review.md](code-review.md)) |
| `REVIEW.md` | What counts as Important vs Nit in a review | Whenever Claude or a person reviews a PR |
| `.claude/skills/new-feature/SKILL.md` | Steps for starting a feature from a spec | Only when you type `/new-feature` (see [spec-driven-development.md](spec-driven-development.md)) |

The most important boundary: `CLAUDE.md` and rules are **advice**; Claude can forget or misread them.
Settings and hooks are **law**; they run as code, so they always hold. Anything that must be true at all times needs a law behind it.

> **Further reading:** [How Claude remembers your project](https://code.claude.com/docs/en/memory) (CLAUDE.md and rules),
> [Steering Claude Code](https://claude.com/resources/articles/steering-claude-code-skills-hooks-rules-subagents-and-more)
> (when to use CLAUDE.md, a rule, a skill, a hook or a subagent).

## `CLAUDE.md`: what goes in and why

Principle: every line must answer the question "if this line were removed, would Claude get something wrong?". When the file is long,
Claude ignores some rules, so keep it under 200 lines and do not repeat what the code already makes obvious.

- **Commands:** commands Claude cannot guess. For example, `make test` needs `make up` first; without Postgres the tests are skipped,
  not marked red. *If removed:* Claude thinks the tests passed when they were actually skipped.
- **Rules that are easy to break:** the Final decisions in the spec where one mistake loses data. For example, `make seed`
  deletes RAW on Snowflake (the only place that keeps SCD2 history). This line says IMPORTANT because the damage cannot be undone.
- **Workflow:** every change goes through a PR, when to use plan mode, and changing a Final decision means updating the decision log.
- **Language:** everything in the repo is in English, including code comments, docs and commit messages.

`CLAUDE.md` does not import the whole `docs/Project-Spec.md` with `@` because the spec is over 500 lines: an import would load all of it into every
session and dilute the guidance. Instead, the file points to the spec so Claude reads the right section when needed.

## `.claude/rules/dbt.md`: path-scoped rules

The file starts with `paths: ["dbt/**"]`, so the rules load only when Claude works on dbt. Editing Python does not spend
context on dbt rules. The content summarizes conventions already in spec §10 and
`docs/design/analytical-data-modeling.md`: model names by layer, `-1`/`-2` keys, how SCD2 is built, incremental `fct_sales`.

## `.claude/settings.json`: permissions

Claude Code evaluates permissions in the order **deny, then ask, then allow**; the first matching rule decides.

| Group | Commands | Why |
|---|---|---|
| allow | `make test`, `make lint`, `make dbt-parse`, `uv run pytest`, `uv run ruff`... | Safe commands run often; no need to ask every time |
| ask | `make seed`, `reseed`, `db-reset`, `clean-raw`, `snowflake-init`, `dbt-full-refresh`, `git push ... main` | Deletes RAW, changes Snowflake or pushes straight to `main`: always asks you, even in auto mode |
| deny | `git push --force`, reading `.env`, `.dlt/secrets.toml`, `dbt/profiles.yml`, `.snowflake/`, `*.p8`, `*.pem` | Never needed; reading secret files would put passwords into the conversation |

Bash rules match the text of the command. Claude Code splits compound commands (`cd x && make seed`), so the rules still catch them, but they
do not catch a command written in a very different way (for example through `sh -c`). So this is a guardrail for common actions, not
an absolute security wall.

> **Further reading:** [Configure permissions](https://code.claude.com/docs/en/permissions).

## The two hooks

A hook is a script that Claude Code runs automatically at a fixed point. Claude Code sends the tool call details (as JSON) to the
script's stdin. Exit code `0` lets the action through; exit code `2` reports an error, and the stderr content is sent back to Claude.

**`protect_secrets.py` (PreToolUse, before editing a file).** If the target file is `.env`, `secrets.toml`, `profiles.yml`,
`*.p8`, `*.pem` or lives in `.snowflake/`, the edit is blocked. Template files `*.example` and `dbt/ci/profiles.yml` (environment
variables only) can still be edited.
*Why it is needed even with `.gitignore`:* `.gitignore` only prevents commits; it does not stop Claude from overwriting your real passwords.

**`ruff_after_edit.py` (PostToolUse, after editing a file).** For `.py` files, runs `ruff format` and `ruff check --fix`.
If errors remain that cannot be fixed automatically, it returns code 2 so Claude sees them and fixes them right away, instead of waiting for CI to go red.
The hook ignores F401 (unused import) because Claude often adds an import in one edit and uses it in the next; removing the import
in between would break the next edit. CI still catches F401.

Both hooks are written in standard-library Python so they run on any machine with `python3`, without installing `jq`.

> **Further reading:** [Hooks reference](https://code.claude.com/docs/en/hooks) (events and the meaning of exit codes).

## Verification

Test a hook without opening Claude by sending fake JSON to stdin:

```bash
echo '{"tool_input":{"file_path":".env"}}' | python3 .claude/hooks/protect_secrets.py; echo $?
# prints "Blocked: ..." and 2
echo '{"tool_input":{"file_path":".env.example"}}' | python3 .claude/hooks/protect_secrets.py; echo $?
# prints 0
```

In Claude Code: type `/context` to see that `CLAUDE.md` is loaded, `/hooks` to see the two hooks, and `/permissions` to see
the allow, ask and deny rules.

## Changes from before

Previously `.gitignore` ignored the whole `.claude` folder. Now it only ignores machine-specific parts: `.claude/settings.local.json`,
`.claude/worktrees/` and `CLAUDE.local.md`. If your machine has other files in `.claude/` (for example personal skills), they
will show up as untracked; move them to `~/.claude/` or add them to `.gitignore`.

## When to edit these files

- Claude repeats the same mistake: add a line to `CLAUDE.md` (or to a rule if it only concerns one area of the code).
- A rule in `CLAUDE.md` is ignored even though it is clearly written: turn it into a hook or a deny/ask rule.
- A repeated multi-step process (for example adding a dbt model): write it as a skill in `.claude/skills/`, like `new-feature`.
- Personal preferences that do not apply to the whole repo: put them in `.claude/settings.local.json` or `~/.claude/`, not in the shared files.
