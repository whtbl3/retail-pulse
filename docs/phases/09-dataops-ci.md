# Phase 9: CI/CD with GitHub Actions and slim CI for dbt

Goal: every pull request (PR) checks dbt changes automatically, **without touching real data** and **without
rebuilding everything**. This matches the "GitHub CI" block in the [root README](../../README.md).

## Why it is needed

You edit `dim_payment_method` and push straight to `main`. At 23:00 Dagster runs. The model has a logic bug but nothing
turns red, it just produces wrong numbers. The next morning the dashboard is off. CI stops that bug **before** it reaches `main`.

- **CI:** a machine checks every change before it is merged into `main` (like a kitchen testing a dish before it goes on the menu).
- **CD:** automatically ships the checked version to where it runs for real. This project **only has CI** so far; deploying
  means `git pull` and restarting Dagster by hand.

> **Further reading:** [Continuous Integration (Martin Fowler)](https://martinfowler.com/articles/continuousIntegration.html),
> the classic article on what CI is and why everyone should merge code into the main branch often.

Data differs from ordinary code in three ways, and the design below answers each one:
- A bug only makes numbers wrong, it does not crash the program, so CI must also run `dbt test`.
- Tests need real data but must not damage it, so there is a separate CI database that only reads production.
- Building everything on every PR burns Snowflake credits, so we use slim CI.

## How slim CI works

dbt compares the PR's `manifest.json` with the production manifest to find which models changed, then builds only those:

```bash
dbt build --select state:modified+ --defer --state <folder with the production manifest>
```

> **Further reading (dbt docs):** [Best practices for workflows](https://docs.getdbt.com/best-practices/best-practice-workflows)
> (the section on running only changed models, that is slim CI), [Node selector methods](https://docs.getdbt.com/reference/node-selection/methods)
> (how `state:modified` works) and [Defer](https://docs.getdbt.com/reference/node-selection/defer)
> (`--defer` and `--state`).

Example: PR number 7 edits `dim_payment_method`:
- **Built:** `dim_payment_method`, `fct_sales` (which uses this dimension) and their 30 tests. Written to
  `RETAIL_PULSE_CI.PR_7_MARTS`, without touching production.

  | | Your machine | CI for PR 7 |
  |---|---|---|
  | `fct_sales` | `RETAIL_PULSE.MARTS.fct_sales` | `RETAIL_PULSE_CI.PR_7_MARTS.fct_sales` |

- **Not built:** the other 6 dimensions, and all of staging and intermediate. Thanks to `--defer`, `ref()` to them points
  to production (`RETAIL_PULSE.marts.dim_product`...). That is why the CI user needs **read** access to the production schemas.
- **Cleanup:** the last step drops the `PR_7_*` schemas. PR number 8 running in parallel uses `PR_8_*`, so the two PRs
  do not overwrite each other. The per-PR schema name is set by the `generate_schema_name` macro; see
  [Custom schemas](https://docs.getdbt.com/docs/build/custom-schemas).

The list above comes from running `dbt ls --select state:modified+` locally with the exact changes of the test PR.
GitHub's detailed logs require login, so they cannot be read from outside.

## Setup (once, in this order)

**1. Prepare the admin account.** You need an `ACCOUNTADMIN` user and three variables in `.env`: `SNOWFLAKE_ACCOUNT`,
`SNOWFLAKE_ADMIN_USER`, `SNOWFLAKE_ADMIN_PASSWORD`.
*Why:* only `ACCOUNTADMIN` can create databases, roles and users. If a variable is missing, the command stops and creates nothing on Snowflake.

**2. Create the CI environment on Snowflake.**
```bash
make snowflake-init-dry   # preview, does not connect
make snowflake-init       # real run; safe to run many times
```
This creates: database `RETAIL_PULSE_CI` (where CI writes), warehouse `RETAIL_CI_WH` with resource monitor `RETAIL_CI_RM`
(cap of 2 credits/month), role `CI_RUNNER` (writes in the CI database, only reads production), user `GITHUB_CI` (key
pair login, file `.snowflake/github_ci.p8`).
*Why:* kept separate so a CI bug cannot overwrite real data or burn all credits.
*Check:* `DESC USER GITHUB_CI;` shows `RSA_PUBLIC_KEY_FP` in the form `SHA256:...`.
> **Further reading (Snowflake docs):** [Key-pair authentication](https://docs.snowflake.com/en/user-guide/key-pair-auth)
> (log in with a key instead of a password) and [Resource monitors](https://docs.snowflake.com/en/user-guide/resource-monitors)
> (set a credit cap, auto suspend the warehouse).

**3. Add two secrets to GitHub.** Settings, Secrets and variables, Actions, New **repository** secret:
`SNOWFLAKE_ACCOUNT` (same as in `.env`) and `CI_PRIVATE_KEY` (the full content of `.snowflake/github_ci.p8`, including
the BEGIN/END lines).
*Why:* the workflow reads these two secrets to log in. They must be repository secrets because the workflow does not
declare `environment:`; secrets stored in an Environment come through empty. Never paste the key into a chat or a commit.
> **Further reading:** [Using secrets in GitHub Actions](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets).

**4. Run the `Prod manifest` workflow.** Actions tab, click `manifest.yml` in the left column, **Run workflow**, choose `main`.
*Why:* it creates the production manifest (artifact `prod-manifest`) for PRs to compare against. Without it, the first PR builds everything.
A green run here does not prove the login works, because `dbt parse` does not connect to Snowflake.

**5. Open a test PR.** Create a branch, add a comment line to a model, open a PR; `lint` and `dbt-slim-ci` must be green.
Then close the PR and delete the branch, without merging.
*Why:* this is the first time CI really logs in to Snowflake. Testing first keeps config errors out of real PRs.

**6. Turn on `main` protection** as in the table below.
*Why last:* the required check picker only lists checks that have already run, and the rule would block pushing the workflow to `main`.

## GitHub settings

| Where | What to do | Why |
|---|---|---|
| Settings, General, Pull Requests | Enable only **Squash merging** (default to the PR title); enable **Automatically delete head branches** | Each PR becomes one clean commit; the branch is deleted after merge |
| Settings, Actions, General | **Require approval for all external contributors** | The repo is public, anyone can fork and open a PR; strangers cannot run workflows on their own |
| Same place | Workflow permissions: **Read repository contents**; leave "Allow GitHub Actions to create and approve pull requests" unchecked | Workflows only read; bots cannot approve PRs |
| Settings, Rules, Rulesets | Create ruleset `protect-main`: **Active**, targets the default branch, **bypass list empty** | The repo owner must also go through a PR |
| In the ruleset | **Restrict deletions** and **Block force pushes** | No accidental deletion or rewrite of `main` history |
| In the ruleset | **Require a pull request before merging** (approvals = 0; 1 for a team) | Otherwise direct pushes still work and CI is useless |
| In the ruleset | **Require status checks to pass**: `lint`, `test`, `dbt-slim-ci` | A red CI blocks the merge. `test` only shows in the picker after it has run once |

Secrets are not passed to PRs from forks (on purpose): if they were, an outsider could just edit the workflow in a fork
to print the key to the log.

**Does a docs-only PR have to run dbt?** No, and `ci.yml` already handles it: the `lint` and `dbt-slim-ci` checks always
**appear** on every PR, but an early step of the dbt job checks whether the PR changes `dbt/` (except the `*.example`
templates), `pyproject.toml`, `uv.lock` or `ci.yml` itself. If not, the dbt steps are skipped and the job turns green in a few seconds.
*Why not filter `paths` at the workflow level:* when a workflow is skipped, its check **stays Pending and blocks the merge**
([GitHub: handling skipped but required checks](https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/troubleshooting-required-status-checks)),
while a job skipped by a condition reports Success. *Without this approach:* docs PRs or Python-only PRs would hang
forever, or every PR would spend time running dbt even when it does not touch dbt.

> **Further reading (GitHub docs):** [About rulesets](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets)
> and [Available rules for rulesets](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets)
> (each rule in the table above), [Secure use reference](https://docs.github.com/en/actions/reference/security/secure-use)
> (why PRs from forks need care) and [Pull request merges](https://docs.github.com/en/pull-requests/reference/pull-request-merges)
> (squash merge).

## Local quality gates

CI only reports errors after you push. Checking locally first is faster to fix and saves a CI round.

**`make check`** runs exactly what CI runs for Python: `ruff check`, `ruff format --check` (does not change files), then
`make test`. Run it before opening a PR.
*Unlike `make lint`:* `lint` fixes files, `check` only checks and reports, like CI.
*Note:* `tests/test_orchestration.py` reads `dbt/target/manifest.json`, so run `make dbt-parse` once first.

**pre-commit** runs before each `git commit`, only on staged files: ruff, trailing whitespace removal, YAML/TOML
checks, blocking files larger than 1 MB and blocking private keys. Install it once per clone:
```bash
uv run pre-commit install
```
*If skipped:* commits still work, and errors only show up when CI runs. *Do not* run `pre-commit run --all-files` for now: it
fixes whitespace in about 40 dbt files, which makes slim CI rebuild almost every model. Leave that to a separate cleanup PR.

**The `test` job in CI** starts PostgreSQL 16 as a service, runs `dbt deps` and `dbt parse` (no Snowflake connection, so
it uses the CI profile with dummy values and needs no secrets), then `pytest`. Locally, tests that need Postgres are
skipped if you forget `make up`; in CI they always run.

> **Further reading:** [pre-commit](https://pre-commit.com/) and
> [Service containers in GitHub Actions](https://docs.github.com/en/actions/use-cases-and-examples/using-containerized-services/creating-postgresql-service-containers).

## Daily work (trunk-based)

One main branch, `main`. Each task gets a short-lived branch (a few hours to a few days), PRs stay small, and they merge
when CI is green. No GitFlow (`develop`, `release`): it is heavy and only fits release cycles.

> **Further reading:** [Trunk Based Development](https://trunkbaseddevelopment.com/) and especially
> [Short-lived feature branches](https://trunkbaseddevelopment.com/short-lived-feature-branches/); if you already know
> GitHub, see [GitHub flow](https://docs.github.com/en/get-started/using-github/github-flow).

```bash
git switch main && git pull
git switch -c fix/short-name
# make changes, then:
git add -A && git commit -m "..."
git push -u origin fix/short-name   # git prints the link to open a PR
```
Open the PR (GitHub fills in the template with its checklist), wait for the checks to turn green, click **Squash and merge**.
Then run `git switch main && git pull && git fetch --prune`, and `git branch -D <branch>` (squash makes Git think the branch is not merged).

## Files

| File | Job |
|---|---|
| `.github/workflows/ci.yml` | Every PR: `ruff`; `pytest` with PostgreSQL; dbt slim CI + schema cleanup (only when the PR changes dbt, see above) |
| `.github/pull_request_template.md` | PR description template, with the Definition of Done checklist (spec §16) |
| `.pre-commit-config.yaml` | Checks before each local commit (ruff, whitespace, YAML, private keys) |
| `.github/workflows/manifest.yml` | Every merge that changes `dbt/**`: `dbt parse --target prod`, saves the `prod-manifest` artifact |
| `dbt/ci/profiles.yml` | CI profile (targets `ci`, `prod`); uses only `env_var()`, so it is committed |
| `dbt/macros/generate_schema_name.sql` | For target `ci`, adds the `PR_<number>_` prefix |
| `dbt/macros/drop_ci_schemas.sql` | Drops the PR's schemas; refuses to run if the target is not `ci` |
| `infras/snowflake/init.sql` | The CI part is at the end of the file and runs with `make snowflake-init` |

## Notes

- **Manifest out of sync with production:** the manifest is created on merge into `main`, while production data is built
  by Dagster. If `full_pipeline` has not run since a merge, the next PR's `--defer` reads stale production tables.
  Acceptable for a one-person project.
- **`fct_sales` is incremental:** a new CI schema has no table yet, so the first build is a full run (~270 thousand rows, light).
- **Actions are not pinned by SHA.** On every run GitHub warns that `checkout@v4` and `setup-uv@v5` still use Node.js 20,
  and that `ubuntu-latest` moves to Ubuntu 26 from 19/10/2026. This does not turn CI red; if it breaks after that date, try `ubuntu-24.04`.
- **No `sqlfluff` yet:** the `dbt` templater (configured in `pyproject.toml`) needs a Snowflake connection to run.
  The `jinja` templater runs without a connection, but the first try reported 209 errors in 19/20 models
  (mostly indentation and whitespace). A SQL style must be chosen first, then fixed in a separate PR.

## Real runs

`make snowflake-init`, `Prod manifest` and the test PR all ran green on GitHub Actions and Snowflake (dbt build 17 seconds,
schema cleanup 5 seconds). Two errors were hit and fixed:
- `runner.temp` cannot be used in a job's `env`, so GitHub reported "Invalid workflow file". Fixed by using `$RUNNER_TEMP`
  in the step that writes the key and setting the variable through `$GITHUB_ENV`. Run `actionlint` before pushing a workflow.
- `.gitignore` blocked every `profiles.yml`, so `dbt/ci/profiles.yml` almost did not reach GitHub. Added
  `!dbt/ci/profiles.yml`.
