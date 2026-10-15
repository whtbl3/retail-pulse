"""One-command local setup: ask for the Snowflake account and admin login, fill in the rest.

`make setup` runs this. It is safe to run again: it only fills values that are missing or still
the example placeholders, and never overwrites a config file that already exists.

1. `.env`: created from `.env.example` if missing; the Snowflake account and the dbt key path are
   filled in, and so is `DBT_DEV_SCHEMA` (your own dbt dev schemas, from your user name); a new
   `.env` also gets a random Postgres password.
2. Snowflake: `snowflake-init` creates the key pairs in `.snowflake/` and the users, roles and
   warehouse. The admin password is passed to it in memory and never written to disk.
3. `.dlt/secrets.toml` and `~/.dbt/profiles.yml`: created from their examples if missing.
"""

from __future__ import annotations

import argparse
import getpass
import os
import re
import secrets
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

REPO = Path(__file__).parents[2]
ACCOUNT_PLACEHOLDER = "ORGNAME-ACCOUNTNAME"
KEY_PATH_PLACEHOLDER = "/absolute/path/to/"
DEV_SCHEMA_PLACEHOLDER = "DBT_YOURNAME"


def normalize_account(raw: str) -> str:
    """Accept the identifier in the forms Snowsight shows and return ORGNAME-ACCOUNTNAME."""
    account = raw.strip()
    account = re.sub(r"^https?://", "", account)
    account = account.removesuffix("/").removesuffix(".snowflakecomputing.com")
    return account.replace(".", "-").upper()


def read_env(text: str) -> dict[str, str]:
    values = {}
    for line in text.splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
    return values


def set_env(text: str, key: str, value: str) -> str:
    """Replace `KEY=...` (also a commented `# KEY=...`), or append it if absent."""
    pattern = re.compile(rf"^#?\s*{re.escape(key)}=.*$", re.MULTILINE)
    line = f"{key}={value}"
    if pattern.search(text):
        return pattern.sub(lambda _: line, text, count=1)
    return text.rstrip("\n") + f"\n{line}\n"


def dev_schema_name(user: str) -> str:
    """The developer's own dbt schema prefix (spec 003): `phuc.lh` becomes `DBT_PHUC_LH`."""
    return "DBT_" + re.sub(r"[^A-Z0-9]+", "_", user.upper()).strip("_")


def is_placeholder(key: str, value: str | None) -> bool:
    if not value:
        return True
    if key == "DBT_DEV_SCHEMA":
        return value == DEV_SCHEMA_PLACEHOLDER
    if key == "SNOWFLAKE_ACCOUNT":
        return value == ACCOUNT_PLACEHOLDER
    if key == "DBT_PRIVATE_KEY_PATH":
        return value.startswith(KEY_PATH_PLACEHOLDER) or not Path(value).is_absolute()
    return False


def render_dlt_secrets(example: str, account: str, key_path: Path) -> str:
    """The example file with the account filled in and the key read from a file path."""
    text = re.sub(r'^host = ".*"$', f'host = "{account}"', example, flags=re.MULTILINE)
    text = re.sub(r"^private_key = .*\n", "", text, flags=re.MULTILINE)
    return re.sub(
        r"^# private_key_path = .*$",
        f'private_key_path = "{key_path}"',
        text,
        flags=re.MULTILINE,
    )


def prepare_env(repo: Path, ask: Callable[[str], str]) -> tuple[dict[str, str], list[str]]:
    """Create or complete .env. Returns its values and a list of what changed."""
    env_path, changes = repo / ".env", []
    if env_path.exists():
        text = env_path.read_text()
    else:
        text = (repo / ".env.example").read_text()
        text = set_env(text, "PG_PASSWORD", secrets.token_urlsafe(16))
        changes.append(".env created from .env.example with a random PG_PASSWORD")
    values = read_env(text)

    if is_placeholder("SNOWFLAKE_ACCOUNT", values.get("SNOWFLAKE_ACCOUNT")):
        account = normalize_account(ask("Snowflake account identifier (ORGNAME-ACCOUNTNAME): "))
        text = set_env(text, "SNOWFLAKE_ACCOUNT", account)
        changes.append(f".env: SNOWFLAKE_ACCOUNT={account}")

    if is_placeholder("DBT_PRIVATE_KEY_PATH", values.get("DBT_PRIVATE_KEY_PATH")):
        key_path = repo / ".snowflake" / "dbt_transformer.p8"
        text = set_env(text, "DBT_PRIVATE_KEY_PATH", str(key_path))
        changes.append(f".env: DBT_PRIVATE_KEY_PATH={key_path}")

    if is_placeholder("DBT_DEV_SCHEMA", values.get("DBT_DEV_SCHEMA")):
        schema = dev_schema_name(getpass.getuser())
        text = set_env(text, "DBT_DEV_SCHEMA", schema)
        changes.append(f".env: DBT_DEV_SCHEMA={schema} (your dbt dev schemas {schema}_*)")

    if changes:
        env_path.write_text(text)
    return read_env(text), changes


def write_if_missing(path: Path, content: str) -> bool:
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return True


def run_snowflake_init(repo: Path, env: dict[str, str], ask: Callable[[str], str]) -> None:
    """Run snowflake-init with the admin login in its environment only."""
    admin_user = env.get("SNOWFLAKE_ADMIN_USER") or ask("Snowflake admin user (ACCOUNTADMIN): ")
    admin_password = env.get("SNOWFLAKE_ADMIN_PASSWORD") or getpass.getpass(
        "Snowflake admin password (not saved): "
    )
    child_env = {
        **os.environ,
        "SNOWFLAKE_ACCOUNT": env["SNOWFLAKE_ACCOUNT"],
        "SNOWFLAKE_ADMIN_USER": admin_user,
        "SNOWFLAKE_ADMIN_PASSWORD": admin_password,
    }
    cmd = [sys.executable, "-m", "retail_pulse.ingestion.snowflake_init"]
    subprocess.run(cmd, cwd=repo, env=child_env, check=True)


def main(argv: list[str] | None = None, ask: Callable[[str], str] = input) -> None:
    parser = argparse.ArgumentParser(description="Set up .env, Snowflake, dlt and dbt config")
    parser.add_argument(
        "--skip-snowflake", action="store_true", help="Only write config files; do not connect"
    )
    args = parser.parse_args(argv)
    repo = REPO

    env, changes = prepare_env(repo, ask)
    ci_key = repo / ".snowflake" / "github_ci.p8"
    new_ci_key = not ci_key.exists()

    if not args.skip_snowflake:
        run_snowflake_init(repo, env, ask)

    dlt_key = repo / ".snowflake" / "dlt_loader.p8"
    example = (repo / ".dlt" / "secrets.toml.example").read_text()
    secrets_toml = render_dlt_secrets(example, env["SNOWFLAKE_ACCOUNT"], dlt_key)
    if write_if_missing(repo / ".dlt" / "secrets.toml", secrets_toml):
        changes.append(".dlt/secrets.toml created")

    profiles_dir = Path(env.get("DBT_PROFILES_DIR") or Path.home() / ".dbt").expanduser()
    profile = (repo / "dbt" / "profiles.yml.example").read_text()
    if write_if_missing(profiles_dir / "profiles.yml", profile):
        changes.append(f"{profiles_dir / 'profiles.yml'} created")
    else:
        profile_path = profiles_dir / "profiles.yml"
        existing = profile_path.read_text()
        if "retail_pulse:" not in existing:
            print(
                f"Note: add the retail_pulse profile in dbt/profiles.yml.example to {profile_path}"
            )
        elif "prod:" not in existing or "DBT_DEV_SCHEMA" not in existing:
            # Never overwritten: the file may hold other projects or the developer's own edits
            print(
                f"Note: {profile_path} is from before spec 003. Copy the dev and prod outputs from "
                "dbt/profiles.yml.example: dev uses schema env_var('DBT_DEV_SCHEMA'), and Dagster "
                "needs the prod output (docs/phases/12-environments.md)."
            )

    print("\nSetup done." if changes or not args.skip_snowflake else "\nNothing to change.")
    for change in changes:
        print(f"  - {change}")
    if new_ci_key and ci_key.exists():
        print(
            "\nNew CI key: update the GitHub secret CI_PRIVATE_KEY (Settings > Secrets and "
            "variables > Actions)\nwith the content of .snowflake/github_ci.p8, or dbt-slim-ci "
            "will fail."
        )
    print(
        "\nNext: make dagster-up. On a brand-new setup only, run make seed first to load data; "
        "it deletes Snowflake RAW, so never run it on a setup that already has history."
    )


if __name__ == "__main__":
    main()
