"""Khởi tạo Snowflake (warehouse, database, role, user) từ infras/snowflake/init.sql."""

from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

SQL_FILE = Path(__file__).parents[3] / "infras" / "snowflake" / "init.sql"
PLACEHOLDER = "__RSA_PUBLIC_KEY__"


def load_statements(public_key: str) -> list[str]:
    """Bỏ chú thích cả dòng, thay public key, tách theo dấu chấm phẩy."""
    lines = [ln for ln in SQL_FILE.read_text().splitlines() if not ln.lstrip().startswith("--")]
    sql = "\n".join(lines).replace(PLACEHOLDER, public_key)
    return [s.strip() for s in sql.split(";") if s.strip()]


def read_public_key(path: Path) -> str:
    """Public key dạng PEM -> một dòng base64 (bỏ dòng -----BEGIN/END-----)."""
    return "".join(ln for ln in path.read_text().splitlines() if "-----" not in ln).strip()


def mask(stmt: str, public_key: str) -> str:
    return stmt.replace(public_key, "<public key>") if public_key else stmt


def main() -> None:
    parser = argparse.ArgumentParser(description="Khởi tạo Snowflake cho RetailPulse")
    parser.add_argument("--public-key", type=Path, default=Path("snowflake/dlt_loader.pub"))
    parser.add_argument("--dry-run", action="store_true", help="In các câu lệnh, không kết nối")
    args = parser.parse_args()

    if args.public_key.exists():
        key = read_public_key(args.public_key)
    elif args.dry_run:
        key = ""  # dry-run không cần key thật
    else:
        raise SystemExit(f"Không thấy {args.public_key}. Tạo key pair theo docs/phases/03.")
    statements = load_statements(key or "<public key>")

    if args.dry_run:
        for i, stmt in enumerate(statements, 1):
            print(f"-- [{i}/{len(statements)}]\n{mask(stmt, key)};\n")
        print(f"Dry-run: {len(statements)} câu lệnh, chưa kết nối Snowflake.")
        return

    import snowflake.connector  # import muộn: dry-run không cần kết nối

    conn = snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_ADMIN_USER"],
        password=os.environ["SNOWFLAKE_ADMIN_PASSWORD"],
        role="ACCOUNTADMIN",
    )
    try:
        cur = conn.cursor()
        for stmt in statements:
            first_line = re.sub(r"\s+", " ", mask(stmt, key))[:80]
            print(f"> {first_line}")
            cur.execute(stmt)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
