"""PreToolUse hook: chặn Claude sửa hoặc tạo file chứa bí mật.

Claude Code gửi JSON của lệnh gọi tool qua stdin. Thoát mã 2 thì lệnh bị chặn và stderr được
gửi lại cho Claude làm lý do. Thoát mã 0 thì cho qua.
"""

import json
import sys
from pathlib import PurePosixPath

# File mẫu được commit nên sửa bình thường
ALLOWED_SUFFIXES = (".example",)
SECRET_NAMES = {".env", "secrets.toml", "profiles.yml"}
SECRET_SUFFIXES = (".p8", ".pem")
SECRET_DIRS = {".snowflake"}
# Profile của CI chỉ dùng env_var(), không có bí mật
ALLOWED_PATHS = ("dbt/ci/profiles.yml",)


def is_secret(path: str) -> bool:
    p = PurePosixPath(path.replace("\\", "/"))
    if p.name.endswith(ALLOWED_SUFFIXES) or path.endswith(ALLOWED_PATHS):
        return False
    return (
        p.name in SECRET_NAMES
        or p.name.endswith(SECRET_SUFFIXES)
        or any(part in SECRET_DIRS for part in p.parts)
    )


def main() -> int:
    data = json.load(sys.stdin)
    path = data.get("tool_input", {}).get("file_path", "")
    if path and is_secret(path):
        print(
            f"Blocked: {path} holds secrets and must stay out of Claude edits and git. "
            "Ask the user to change it by hand.",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
