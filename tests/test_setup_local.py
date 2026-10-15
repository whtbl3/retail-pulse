"""`make setup`: only the Snowflake login is asked for; every other config value is filled in."""

import shutil
from pathlib import Path

import pytest

from retail_pulse import setup_local

REPO = Path(__file__).parents[1]


@pytest.mark.parametrize(
    "raw",
    [
        "abcdefg-xy12345",
        "ABCDEFG.XY12345",
        "https://abcdefg-xy12345.snowflakecomputing.com/",
        " abcdefg-xy12345.snowflakecomputing.com ",
    ],
)
def test_account_identifier_is_normalized(raw):
    assert setup_local.normalize_account(raw) == "ABCDEFG-XY12345"


def test_set_env_replaces_existing_and_appends_missing():
    text = "A=1\n# B=old\n"
    text = setup_local.set_env(text, "A", "2")
    text = setup_local.set_env(text, "B", "new")
    text = setup_local.set_env(text, "C", "3")
    assert setup_local.read_env(text) == {"A": "2", "B": "new", "C": "3"}


def test_dlt_secrets_use_the_account_and_a_key_path():
    example = (REPO / ".dlt" / "secrets.toml.example").read_text()
    out = setup_local.render_dlt_secrets(example, "ORG-ACC", Path("/repo/.snowflake/dlt_loader.p8"))
    assert 'host = "ORG-ACC"' in out
    assert 'private_key_path = "/repo/.snowflake/dlt_loader.p8"' in out
    assert "\nprivate_key = " not in out


@pytest.fixture
def repo(tmp_path, monkeypatch):
    shutil.copy(REPO / ".env.example", tmp_path / ".env.example")
    (tmp_path / ".dlt").mkdir()
    shutil.copy(REPO / ".dlt" / "secrets.toml.example", tmp_path / ".dlt" / "secrets.toml.example")
    (tmp_path / "dbt").mkdir()
    shutil.copy(REPO / "dbt" / "profiles.yml.example", tmp_path / "dbt" / "profiles.yml.example")
    monkeypatch.setattr(setup_local, "REPO", tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("DBT_PROFILES_DIR", raising=False)
    return tmp_path


def test_fresh_setup_asks_only_for_the_account_and_writes_every_file(repo):
    asked = []

    def ask(prompt):
        asked.append(prompt)
        return "abcdefg.xy12345"

    setup_local.main(["--skip-snowflake"], ask=ask)

    assert len(asked) == 1
    env = setup_local.read_env((repo / ".env").read_text())
    assert env["SNOWFLAKE_ACCOUNT"] == "ABCDEFG-XY12345"
    assert env["DBT_PRIVATE_KEY_PATH"] == str(repo / ".snowflake" / "dbt_transformer.p8")
    assert env["PG_PASSWORD"] not in ("", "change-me")
    secrets_toml = (repo / ".dlt" / "secrets.toml").read_text()
    assert 'host = "ABCDEFG-XY12345"' in secrets_toml
    assert str(repo / ".snowflake" / "dlt_loader.p8") in secrets_toml
    assert (repo / "home" / ".dbt" / "profiles.yml").exists()


def test_second_run_changes_nothing_and_asks_nothing(repo):
    setup_local.main(["--skip-snowflake"], ask=lambda _: "ORG-ACC")
    before = {p: p.read_text() for p in [repo / ".env", repo / ".dlt" / "secrets.toml"]}

    def ask(prompt):
        raise AssertionError(f"unexpected prompt: {prompt}")

    setup_local.main(["--skip-snowflake"], ask=ask)
    assert {p: p.read_text() for p in before} == before


def test_existing_env_keeps_its_postgres_password_and_gets_the_placeholders_fixed(repo):
    example = (repo / ".env.example").read_text()
    (repo / ".env").write_text(setup_local.set_env(example, "PG_PASSWORD", "mine"))

    setup_local.main(["--skip-snowflake"], ask=lambda _: "ORG-ACC")

    env = setup_local.read_env((repo / ".env").read_text())
    assert env["PG_PASSWORD"] == "mine"
    assert env["SNOWFLAKE_ACCOUNT"] == "ORG-ACC"
    assert not env["DBT_PRIVATE_KEY_PATH"].startswith("/absolute/path/to/")


def test_snowflake_init_gets_the_admin_password_in_memory_only(repo, monkeypatch):
    seen = {}

    def fake_run(cmd, cwd, env, check):
        seen.update(env)

    monkeypatch.setattr(setup_local.subprocess, "run", fake_run)
    monkeypatch.setattr(setup_local.getpass, "getpass", lambda _: "s3cret")

    setup_local.main([], ask=lambda prompt: "ADMIN" if "user" in prompt else "ORG-ACC")

    assert seen["SNOWFLAKE_ADMIN_USER"] == "ADMIN"
    assert seen["SNOWFLAKE_ADMIN_PASSWORD"] == "s3cret"
    assert "s3cret" not in (repo / ".env").read_text()
