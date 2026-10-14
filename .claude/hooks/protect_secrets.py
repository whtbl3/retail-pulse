"""PreToolUse hook: stop Claude from editing or creating files that hold secrets.

Claude Code sends the tool call as JSON on stdin. Exit code 2 blocks the call and stderr is
sent back to Claude as the reason. Exit code 0 lets it through.
"""

import json
import sys
from pathlib import PurePosixPath

# Example files are committed, so editing them is fine
ALLOWED_SUFFIXES = (".example",)
SECRET_NAMES = {".env", "secrets.toml", "profiles.yml"}
SECRET_SUFFIXES = (".p8", ".pem")
SECRET_DIRS = {".snowflake"}
# The CI profile only uses env_var() and holds no secrets
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
