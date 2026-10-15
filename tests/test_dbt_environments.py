"""dbt environments (spec 003): which schemas each target writes, and which grants it declares.

Every check runs `dbt parse` or `dbt ls`, which compile the project without connecting to Snowflake,
so the profiles get dummy credentials. `dev` comes from dbt/profiles.yml.example (what a developer
copies), `ci` and `prod` from dbt/ci/profiles.yml (what GitHub Actions uses).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).parents[1]
DBT_DIR = REPO / "dbt"
DBT = str(Path(sys.executable).parent / "dbt")
PRODUCTION = {"STAGING", "INTERMEDIATE", "MARTS"}
GRANTS = {"select": ["REPORTER", "CI_RUNNER"]}
ENV = {
    "SNOWFLAKE_ACCOUNT": "unused",
    "DBT_PRIVATE_KEY_PATH": "/dev/null",
    "CI_PRIVATE_KEY_PATH": "/dev/null",
    "CI_SCHEMA": "PR_7",
    "DBT_DEV_SCHEMA": "DBT_TEST",
}

pytestmark = pytest.mark.skipif(
    not (DBT_DIR / "dbt_packages" / "dbt_utils").exists(), reason="run `make dbt-deps` first"
)


def dev_profiles(tmp: Path) -> Path:
    folder = tmp / "dev-profiles"
    folder.mkdir(exist_ok=True)
    shutil.copy(DBT_DIR / "profiles.yml.example", folder / "profiles.yml")
    return folder


def run_dbt(
    args: list[str],
    tmp: Path,
    profiles: Path,
    target: str | None = None,
    env: dict[str, str] | None = None,
    project: Path = DBT_DIR,
) -> subprocess.CompletedProcess:
    clean = {k: v for k, v in os.environ.items() if not k.startswith(("DBT_", "CI_", "SNOWFLAKE_"))}
    cmd = [DBT, *args, "--project-dir", str(project), "--profiles-dir", str(profiles)]
    cmd += ["--log-path", str(tmp / "logs"), "--no-partial-parse"]
    if target:
        cmd += ["--target", target]
    return subprocess.run(
        cmd, env={**clean, **(ENV if env is None else env)}, capture_output=True, text=True
    )


def parse(tmp: Path, profiles: Path, target: str | None = None, env=None) -> dict:
    out = tmp / f"target-{target or 'default'}"
    result = run_dbt(["parse", "--target-path", str(out)], tmp, profiles, target, env)
    assert result.returncode == 0, result.stdout[-3000:]
    return json.loads((out / "manifest.json").read_text())


def models(manifest: dict) -> list[dict]:
    return [n for n in manifest["nodes"].values() if n["resource_type"] == "model"]


def layer(node: dict) -> str:
    return node["path"].split("/")[0]


@pytest.fixture(scope="module")
def tmp(tmp_path_factory) -> Path:
    return tmp_path_factory.mktemp("dbt-env")


@pytest.fixture(scope="module")
def dev(tmp) -> dict:
    return parse(tmp, dev_profiles(tmp), "dev")


@pytest.fixture(scope="module")
def prod(tmp) -> dict:
    return parse(tmp, DBT_DIR / "ci", "prod")


@pytest.fixture(scope="module")
def ci(tmp) -> dict:
    return parse(tmp, DBT_DIR / "ci", "ci")


# --- Schemas (R1, R3, R8, AC1, AC3) ---


def test_dev_writes_only_to_the_developer_schemas(dev):
    for node in models(dev):
        assert node["database"] == "RETAIL_PULSE"
        assert node["schema"].upper() == f"DBT_TEST_{layer(node).upper()}", node["name"]


def test_the_default_target_is_dev(tmp):
    manifest = parse(tmp, dev_profiles(tmp))
    assert {n["schema"].upper() for n in models(manifest)} == {
        f"DBT_TEST_{name}" for name in PRODUCTION
    }


def test_prod_keeps_the_production_schema_names(prod):
    for node in models(prod):
        assert node["database"] == "RETAIL_PULSE"
        assert node["schema"].upper() == layer(node).upper(), node["name"]


def test_ci_writes_to_the_pull_request_schemas(ci):
    for node in models(ci):
        assert node["database"] == "RETAIL_PULSE_CI"
        assert node["schema"].upper() == f"PR_7_{layer(node).upper()}", node["name"]


@pytest.mark.parametrize("schema", ["MARTS", "staging", "RAW"])
def test_dev_refuses_a_production_schema(tmp, schema):
    result = run_dbt(
        ["parse", "--target-path", str(tmp / "refused")],
        tmp,
        dev_profiles(tmp),
        "dev",
        {**ENV, "DBT_DEV_SCHEMA": schema},
    )
    assert result.returncode != 0
    assert "production schema" in result.stdout


def test_dev_needs_the_developer_schema(tmp):
    env = {k: v for k, v in ENV.items() if k != "DBT_DEV_SCHEMA"}
    result = run_dbt(
        ["parse", "--target-path", str(tmp / "unnamed")], tmp, dev_profiles(tmp), "dev", env
    )
    assert result.returncode != 0
    assert "DBT_DEV_SCHEMA" in result.stdout


# --- Grants (R5, R6, AC4b, AC5) ---


def test_prod_marts_grant_read_to_preset_and_ci(prod):
    marts = [n for n in models(prod) if layer(n) == "marts"]
    assert marts
    for node in marts:
        assert node["config"]["grants"] == GRANTS, node["name"]
    for node in models(prod):
        if layer(node) != "marts":
            assert not node["config"]["grants"], node["name"]


@pytest.mark.parametrize("environment", ["dev", "ci"])
def test_dev_and_ci_declare_no_grants(environment, request):
    manifest = request.getfixturevalue(environment)
    assert all(not n["config"]["grants"] for n in models(manifest))


# --- Slim dev build (R2, AC1b) ---


def test_a_dev_build_selects_only_the_changed_model_and_its_dependents(tmp, prod):
    state = tmp / "target-prod"
    project = tmp / "project"
    shutil.copytree(
        DBT_DIR, project, ignore=shutil.ignore_patterns("target", "logs", "dbt_packages")
    )
    (project / "dbt_packages").symlink_to(DBT_DIR / "dbt_packages")
    profiles = dev_profiles(tmp)

    def selected() -> set[str]:
        result = run_dbt(
            ["ls", "-s", "state:modified+", "--state", str(state), "--resource-type", "model"]
            + ["--output", "name", "--target-path", str(tmp / "ls"), "--quiet"],
            tmp,
            profiles,
            "dev",
            project=project,
        )
        assert result.returncode == 0, result.stdout[-3000:]
        return {line.strip() for line in result.stdout.splitlines() if line.strip()}

    # Same code as production: the target differs (schemas, grants) but nothing counts as changed
    assert selected() == set()

    model = project / "models" / "staging" / "stg_store.sql"
    model.write_text(model.read_text() + "\n-- edited\n")
    children = {
        prod["nodes"][c]["name"]
        for c in prod["child_map"]["model.retail_pulse.stg_store"]
        if c.startswith("model.")
    }
    downstream, frontier = set(children), set(children)
    while frontier:
        frontier = {
            prod["nodes"][c]["name"]
            for n in frontier
            for c in prod["child_map"][f"model.retail_pulse.{n}"]
            if c.startswith("model.")
        } - downstream
        downstream |= frontier
    assert children
    assert selected() == {"stg_store", *downstream}


# --- Cleanup (R7, R9) ---
# `dbt run-operation` opens a Snowflake connection before running a macro, so the drop macro is
# rendered here with Jinja and stand-ins for dbt's target, run_query and exceptions.


class Refused(Exception):
    pass


def drop_schemas(target_name: str, schema: str, database: str = "RETAIL_PULSE_CI") -> list[str]:
    import jinja2

    queries: list[str] = []

    def refuse(message):
        raise Refused(message)

    env = jinja2.Environment(extensions=["jinja2.ext.do"])
    source = (DBT_DIR / "macros" / "drop_target_schemas.sql").read_text()
    module = env.from_string(source).make_module(
        {
            "target": {"name": target_name, "schema": schema, "database": database},
            "run_query": queries.append,
            "log": lambda *args, **kwargs: "",
            "exceptions": {"raise_compiler_error": refuse},
        }
    )
    module.drop_target_schemas()
    return queries


def test_dropping_schemas_drops_only_the_target_schemas():
    assert drop_schemas("ci", "PR_7") == [
        f"drop schema if exists RETAIL_PULSE_CI.PR_7{suffix} cascade"
        for suffix in ("", "_staging", "_intermediate", "_marts")
    ]


@pytest.mark.parametrize(
    ("target_name", "schema"),
    [("prod", "PUBLIC"), ("prod", "DBT_X"), ("dev", "MARTS"), ("dev", "raw")],
)
def test_dropping_schemas_refuses_production(target_name, schema):
    with pytest.raises(Refused, match="refuses to drop production"):
        drop_schemas(target_name, schema, "RETAIL_PULSE")
