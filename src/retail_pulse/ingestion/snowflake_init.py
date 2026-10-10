"""Khởi tạo Snowflake (warehouse, database, role, user, CI) từ infras/snowflake/init.sql."""

from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

SQL_FILE = Path(__file__).parents[3] / "infras" / "snowflake" / "init.sql"
KEY_DIR = Path(".snowflake")  # đã nằm trong .gitignore
# user Snowflake -> tên file key; placeholder trong init.sql là __<USER>_PUBLIC_KEY__
USERS = {
    "DLT_LOADER": "dlt_loader",
    "DBT_TRANSFORMER": "dbt_transformer",
    "GITHUB_CI": "github_ci",
}


def load_statements(keys: dict[str, str]) -> list[str]:
    """Bỏ chú thích cả dòng, thay public key của từng user, tách theo dấu chấm phẩy."""
    lines = [ln for ln in SQL_FILE.read_text().splitlines() if not ln.lstrip().startswith("--")]
    sql = "\n".join(lines)
    for user, key in keys.items():
        sql = sql.replace(f"__{user}_PUBLIC_KEY__", key)
    return [s.strip() for s in sql.split(";") if s.strip()]


def read_public_key(path: Path) -> str:
    """Public key dạng PEM -> một dòng base64 (bỏ dòng -----BEGIN/END-----)."""
    return "".join(ln for ln in path.read_text().splitlines() if "-----" not in ln).strip()


def ensure_keys(public_key: Path) -> None:
    """Có .pub thì dùng; chỉ có .p8 thì suy ra .pub; chưa có gì thì tạo cặp mới."""
    from cryptography.hazmat.primitives import serialization as ser
    from cryptography.hazmat.primitives.asymmetric import rsa

    private_key = public_key.with_suffix(".p8")
    public_key.parent.mkdir(parents=True, exist_ok=True)
    if private_key.exists():
        key = ser.load_pem_private_key(private_key.read_bytes(), password=None)
        print(f"Dùng private key có sẵn {private_key}, suy ra {public_key}")
    else:
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        private_key.write_bytes(
            key.private_bytes(ser.Encoding.PEM, ser.PrivateFormat.PKCS8, ser.NoEncryption())
        )
        private_key.chmod(0o600)
        print(f"Đã tạo cặp key mới: {private_key}")
    public_key.write_bytes(
        key.public_key().public_bytes(ser.Encoding.PEM, ser.PublicFormat.SubjectPublicKeyInfo)
    )


def admin_settings() -> dict[str, str]:
    """Tài khoản ACCOUNTADMIN lấy từ biến môi trường hoặc .env.

    Cần SNOWFLAKE_ACCOUNT, SNOWFLAKE_ADMIN_USER, SNOWFLAKE_ADMIN_PASSWORD. Thiếu SNOWFLAKE_ACCOUNT
    thì dùng `host` trong .dlt/secrets.toml (cùng tài khoản Snowflake với dlt).
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
            f"Thiếu {', '.join(missing)}. Đặt trong .env hoặc `export` trước khi chạy "
            "(tài khoản ACCOUNTADMIN, không phải DLT_LOADER)."
        )
    return {k: values[k] for k in needed}


def mask(stmt: str, keys: dict[str, str]) -> str:
    for key in filter(None, keys.values()):
        stmt = stmt.replace(key, "<public key>")
    return stmt


def main() -> None:
    parser = argparse.ArgumentParser(description="Khởi tạo Snowflake cho RetailPulse")
    parser.add_argument("--key-dir", type=Path, default=KEY_DIR)
    parser.add_argument("--dry-run", action="store_true", help="In các câu lệnh, không kết nối")
    args = parser.parse_args()

    keys: dict[str, str] = {}
    for user, name in USERS.items():
        pub = args.key_dir / f"{name}.pub"
        if not pub.exists() and not args.dry_run:
            ensure_keys(pub)
        keys[user] = read_public_key(pub) if pub.exists() else "<public key>"  # dry-run chưa có key
    statements = load_statements(keys)

    if args.dry_run:
        for i, stmt in enumerate(statements, 1):
            print(f"-- [{i}/{len(statements)}]\n{mask(stmt, keys)};\n")
        print(f"Dry-run: {len(statements)} câu lệnh, chưa kết nối Snowflake.")
        return

    import snowflake.connector  # import muộn: dry-run không cần kết nối

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
