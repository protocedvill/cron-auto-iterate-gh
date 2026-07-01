"""Git operations for cron-auto-iterate-gh.

All functions operate on a single repo checkout by path. Kept deliberately
low-level/explicit (no GitPython dependency) so behavior is easy to audit.
"""

import subprocess
from pathlib import Path


class GitError(Exception):
    pass


def _run(repo_path: Path, args: list[str], check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(
        ["git", *args],
        cwd=repo_path,
        capture_output=True,
        text=True,
    )
    if check and result.returncode != 0:
        raise GitError(
            f"git {' '.join(args)} failed in {repo_path}: {result.stderr.strip()}"
        )
    return result


def clone_if_missing(repo_path: Path, remote: str) -> bool:
    """Clone remote into repo_path if it doesn't already exist. Returns True if cloned."""
    if repo_path.exists():
        return False
    repo_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "clone", remote, str(repo_path)],
        capture_output=True,
        text=True,
        check=True,
    )
    return True


def get_current_branch(repo_path: Path) -> str:
    return _run(repo_path, ["rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()


def is_clean(repo_path: Path) -> bool:
    return _run(repo_path, ["status", "--porcelain"]).stdout.strip() == ""


def fetch(repo_path: Path) -> None:
    _run(repo_path, ["fetch", "--prune"])


def is_synced(repo_path: Path, branch: str) -> bool:
    """True if HEAD is neither ahead of nor behind origin/<branch>."""
    result = _run(
        repo_path,
        ["rev-list", "--left-right", "--count", f"HEAD...origin/{branch}"],
        check=False,
    )
    if result.returncode != 0:
        # e.g. origin/<branch> doesn't exist yet locally
        return False
    ahead, behind = result.stdout.split()
    return ahead == "0" and behind == "0"


def get_head_commit(repo_path: Path) -> str:
    return _run(repo_path, ["rev-parse", "HEAD"]).stdout.strip()


def changed_files(repo_path: Path) -> list[str]:
    """Tracked (modified/staged) + untracked-but-not-ignored files relative to HEAD."""
    tracked = _run(repo_path, ["diff", "--name-only", "HEAD"]).stdout.splitlines()
    untracked = _run(
        repo_path, ["ls-files", "--others", "--exclude-standard"]
    ).stdout.splitlines()
    return sorted(set(tracked) | set(untracked))


def has_changes(repo_path: Path) -> bool:
    return len(changed_files(repo_path)) > 0


def reset_hard(repo_path: Path, commit: str) -> None:
    _run(repo_path, ["reset", "--hard", commit])
    _run(repo_path, ["clean", "-fd"])


def commit_all(repo_path: Path, message: str) -> None:
    _run(repo_path, ["add", "-A"])
    _run(repo_path, ["commit", "-m", message])


def push(repo_path: Path, branch: str) -> None:
    _run(repo_path, ["push", "origin", f"HEAD:{branch}"])
