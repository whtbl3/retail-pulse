"""Which environment each dbt command and workflow uses (spec 003). Reads files only."""

from __future__ import annotations

import subprocess
from pathlib import Path

import yaml

REPO = Path(__file__).parents[1]
WORKFLOWS = REPO / ".github" / "workflows"


def recipe(target: str, **variables: str) -> list[str]:
    """The commands `make <target>` would run, without running them."""
    args = ["make", "-n", "--no-print-directory", target]
    args += [f"{k}={v}" for k, v in variables.items()]
    result = subprocess.run(args, cwd=REPO, capture_output=True, text=True, check=True)
    return result.stdout.splitlines()


def dbt_lines(lines: list[str], command: str) -> list[str]:
    return [line for line in lines if f"dbt {command}" in line]


def test_the_default_build_is_a_slim_dev_build():
    [build] = dbt_lines(recipe("dbt-build"), "build")
    assert "--target" not in build
    assert "--select 'state:modified+'" in build
    assert "--defer --state target/prod-state" in build


def test_the_dev_build_selection_can_be_overridden():
    [build] = dbt_lines(recipe("dbt-build", SELECT="+fct_sales"), "build")
    assert "--select '+fct_sales'" in build
    assert "--target" not in build


def test_the_prod_state_is_parsed_from_main_for_prod():
    lines = recipe("dbt-prod-state")
    assert any("worktree add" in line and "origin/main" in line for line in lines)
    [parse] = dbt_lines(lines, "parse")
    assert "--target prod" in parse


def test_only_the_explicit_commands_build_prod():
    [build] = dbt_lines(recipe("dbt-build-prod"), "build")
    assert "--target prod" in build
    [refresh] = dbt_lines(recipe("dbt-full-refresh"), "build")
    assert "--target prod" in refresh and "--full-refresh" in refresh
    # dbt-test first parses production (dbt-prod-state) to see what changed; it builds nothing there
    for target in ("dbt-parse", "dbt-test", "dbt-docs", "dbt-dev-clean"):
        lines = [line for line in recipe(target) if "prod-state" not in line]
        assert not any("--target prod" in line for line in lines), target


def test_dev_clean_drops_the_dev_schemas():
    [operation] = dbt_lines(recipe("dbt-dev-clean"), "run-operation")
    assert "drop_target_schemas" in operation
    assert "--target" not in operation


def steps(workflow: str, job: str) -> list[dict]:
    return yaml.safe_load((WORKFLOWS / workflow).read_text())["jobs"][job]["steps"]


def test_ci_keeps_the_pull_request_schemas_after_the_build():
    run = [s.get("run", "") for s in steps("ci.yml", "dbt-slim-ci")]
    build = next(i for i, r in enumerate(run) if "dbt build" in r)
    drops = [i for i, r in enumerate(run) if "drop_" in r]
    assert drops and all(i < build for i in drops)
    assert not any("drop_ci_schemas" in r for r in run)


def test_pull_request_schemas_are_dropped_when_the_pull_request_closes():
    workflow = yaml.safe_load((WORKFLOWS / "ci-cleanup.yml").read_text())
    # PyYAML reads the `on` key as True
    assert workflow[True] == {"pull_request": {"types": ["closed"]}}
    [job] = workflow["jobs"].values()
    assert job["env"]["CI_SCHEMA"] == "PR_${{ github.event.pull_request.number }}"
    assert job["env"]["DBT_PROFILES_DIR"] == "dbt/ci"
    assert any("run-operation drop_target_schemas" in s.get("run", "") for s in job["steps"])
