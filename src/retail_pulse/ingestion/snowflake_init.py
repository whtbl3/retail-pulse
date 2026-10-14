"""Set up Snowflake (warehouse, database, roles, users, CI) from infras/snowflake/init.sql."""

from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

SQL_FILE = Path(__file__).parents[3] / "infras" / "snowflake" / "init.sql"
KEY_DIR = Path(".snowflake")  # already in .gitignore
# Snowflake user -> key file name; the placeholder in init.sql is __<USER>_PUBLIC_KEY__
USERS = {
    "DLT_LOADER": "dlt_loader",
    "DBT_TRANSFORMER": "dbt_transformer",
    "GITHUB_CI": "github_ci",
}


def load_statements(keys: dict[str, str]) -> list[str]:
    """Drop full-line comments, substitute each user's public key, split on semicolons."""
    lines = [ln for ln in SQL_FILE.read_text().splitlines() if not ln.lstrip().startswith("--")]
    sql = "\n".join(lines)
    for user, key in keys.items():
        sql = sql.replace(f"__{user}_PUBLIC_KEY__", key)
    return [s.strip() for s in sql.split(";") if s.strip()]


def read_public_key(path: Path) -> str:
    """PEM public key -> one base64 line (drops the -----BEGIN/END----- lines)."""
    return "".join(ln for ln in path.read_text().splitlines() if "-----" not in ln).strip()


def ensure_keys(public_key: Path) -> None:
    """Use .pub if present; derive .pub from a lone .p8; otherwise create a new pair."""
    from cryptography.hazmat.primitives import serialization as ser
    from cryptography.hazmat.primitives.asymmetric import rsa

    private_key = public_key.with_suffix(".p8")
    public_key.parent.mkdir(parents=True, exist_ok=True)
    if private_key.exists():
        key = ser.load_pem_private_key(private_key.read_bytes(), password=None)
        print(f"Using existing private key {private_key}, derived {public_key}")
    else:
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        private_key.write_bytes(
            key.private_bytes(ser.Encoding.PEM, ser.PrivateFormat.PKCS8, ser.NoEncryption())
        )
        private_key.chmod(0o600)
        print(f"Created new key pair: {private_key}")
    public_key.write_bytes(
        key.public_key().public_bytes(ser.Encoding.PEM, ser.PublicFormat.SubjectPublicKeyInfo)
    )


def admin_settings() -> dict[str, str]:
    """ACCOUNTADMIN credentials from environment variables or .env.

    Needs SNOWFLAKE_ACCOUNT, SNOWFLAKE_ADMIN_USER, SNOWFLAKE_ADMIN_PASSWORD. If SNOWFLAKE_ACCOUNT
    is missing, it uses `host` from .dlt/secrets.toml (the same Snowflake account as dlt).
    """
    from dotenv import dotenv_values

    values = {**dotenv_values(".env"), **os.environ}
    secrets = Path(".dlt/secrets.toml")
    if "SNOWFLAKE_ACCOUNT" not in values and secrets.exists():
        import tomllib

        host = tomllib.loads(secrets.read_text())["destination"]["snowflake"]["credentials"]["host"]
        values["SNOWFLAKE_ACCOUNT"] = host
    needed = ["SNOWFLAKE_ACCOUNT", "SNOWFLAKE_ADMIN_USER", "SNOWFLAKE_ADMIN_PASSWORD"]
    missing = [k for k in needed if not values.get(k)]
    if missing:
        raise SystemExit(
            f"Missing {', '.join(missing)}. Set them in .env or `export` them before running "
            "(the ACCOUNTADMIN account, not DLT_LOADER)."
        )
    return {k: values[k] for k in needed}


def mask(stmt: str, keys: dict[str, str]) -> str:
    for key in filter(None, keys.values()):
        stmt = stmt.replace(key, "<public key>")
    return stmt


def main() -> None:
    parser = argparse.ArgumentParser(description="Set up Snowflake for RetailPulse")
    parser.add_argument("--key-dir", type=Path, default=KEY_DIR)
    parser.add_argument("--dry-run", action="store_true", help="Print statements, do not connect")
    args = parser.parse_args()

    keys: dict[str, str] = {}
    for user, name in USERS.items():
        pub = args.key_dir / f"{name}.pub"
        if not pub.exists() and not args.dry_run:
            ensure_keys(pub)
        keys[user] = read_public_key(pub) if pub.exists() else "<public key>"  # dry-run: no key yet
    statements = load_statements(keys)

    if args.dry_run:
        for i, stmt in enumerate(statements, 1):
            print(f"-- [{i}/{len(statements)}]\n{mask(stmt, keys)};\n")
        print(f"Dry-run: {len(statements)} statements, not connected to Snowflake.")
        return

    import snowflake.connector  # lazy import: dry-run needs no connection

    admin = admin_settings()
    conn = snowflake.connector.connect(
        account=admin["SNOWFLAKE_ACCOUNT"],
        user=admin["SNOWFLAKE_ADMIN_USER"],
        password=admin["SNOWFLAKE_ADMIN_PASSWORD"],
        role="ACCOUNTADMIN",
    )
    try:
        cur = conn.cursor()
        for stmt in statements:
            first_line = re.sub(r"\s+", " ", mask(stmt, keys))[:80]
            print(f"> {first_line}")
            cur.execute(stmt)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
