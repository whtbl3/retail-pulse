"""PostToolUse hook: run ruff on the Python file Claude just edited.

Formats and fixes what lint can fix. Leftover errors exit with code 2 so Claude sees and fixes them.
Ignores F401 (unused import): Claude often adds an import before using it in a later edit; if
the hook removed it in between, the next edit would break. CI still catches F401 on the PR.
Without uv the hook does nothing and never blocks work.
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

    # Run from the repo root so ruff reads the config in pyproject.toml
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
