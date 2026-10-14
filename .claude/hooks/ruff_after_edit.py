"""PostToolUse hook: chạy ruff trên file Python vừa được Claude sửa.

Tự format và sửa lỗi lint sửa được. Còn lỗi thì thoát mã 2 để Claude thấy lỗi và sửa tiếp.
Bỏ qua F401 (import chưa dùng): Claude hay thêm import trước rồi mới dùng ở lần sửa sau, nếu
hook xóa import đó giữa chừng thì lần sửa sau lỗi. CI vẫn bắt F401 khi mở PR.
Không có uv thì bỏ qua, không chặn công việc.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def main() -> int:
    data = json.load(sys.stdin)
    path = data.get("tool_input", {}).get("file_path", "")
    if not path.endswith(".py") or not Path(path).is_file() or shutil.which("uv") is None:
        return 0

    # Chạy từ gốc repo để ruff đọc cấu hình trong pyproject.toml
    cwd = os.environ.get("CLAUDE_PROJECT_DIR") or None
    run = ["uv", "run", "--quiet", "ruff"]
    subprocess.run([*run, "format", "--quiet", path], cwd=cwd, check=False)
    check = subprocess.run(
        [*run, "check", "--fix", "--extend-ignore", "F401", "--quiet", path],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    if check.returncode != 0:
        print(check.stdout + check.stderr, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
