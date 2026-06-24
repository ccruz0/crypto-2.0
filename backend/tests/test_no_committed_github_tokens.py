"""Guard test: no live-looking GitHub token may be committed to the repo.

Delegates to scripts/check_no_committed_github_tokens.py so the same logic
backs both this test and the pre-commit hook.
"""

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECKER = REPO_ROOT / "scripts" / "check_no_committed_github_tokens.py"


def test_no_committed_github_tokens() -> None:
    assert CHECKER.is_file(), f"checker script missing: {CHECKER}"
    result = subprocess.run(
        [sys.executable, str(CHECKER)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        "Live-looking GitHub token found in tracked files.\n" + result.stderr
    )
