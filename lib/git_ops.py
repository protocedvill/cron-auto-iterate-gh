"""Git operations for cron-auto-iterate-gh.

All functions operate on a single repo checkout by path. Kept deliberately
low-level/explicit (no GitPython dependency) so behavior is easy to audit.
"""

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger("iterate.git")


class GitError(Exception):
    pass


def _run(repo_path: Path, args: list[str], check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(
        ["git", *args],
        cwd=repo_path,
        capture_output=True,
        text=True,
    )
    logger.debug(
        "git %s (cwd=%s) -> rc=%s stdout=%r stderr=%r",
        " ".join(args),
        repo_path,
        result.returncode,
        result.stdout.strip(),
        result.stderr.strip(),
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
    result = subprocess.run(
        ["git", "clone", remote, str(repo_path)],
        capture_output=True,
        text=True,
    )
    logger.debug(
        "git clone %s %s -> rc=%s stdout=%r stderr=%r",
        remote,
        repo_path,
        result.returncode,
        result.stdout.strip(),
        result.stderr.strip(),
    )
    if result.returncode != 0:
        raise GitError(f"git clone {remote} failed: {result.stderr.strip()}")
    return True


def get_current_branch(repo_path: Path) -> str:
    """`rev-parse --abbrev-ref HEAD` fails on a freshly cloned empty repo
    (zero commits -> HEAD is an unborn branch, nothing for rev-parse to
    resolve). `symbolic-ref` reads the branch name directly without
    requiring a commit to exist, so it works in both cases."""
    return _run(repo_path, ["symbolic-ref", "--short", "HEAD"]).stdout.strip()


def has_any_commits(repo_path: Path) -> bool:
    return _run(repo_path, ["rev-parse", "HEAD"], check=False).returncode == 0


def get_remote_url(repo_path: Path, name: str = "origin") -> str:
    return _run(repo_path, ["remote", "get-url", name]).stdout.strip()


def status_porcelain(repo_path: Path) -> str:
    """Raw `git status --porcelain` output - empty string means clean."""
    return _run(repo_path, ["status", "--porcelain"]).stdout.strip()


def is_clean(repo_path: Path) -> bool:
    return status_porcelain(repo_path) == ""


def fetch(repo_path: Path) -> None:
    _run(repo_path, ["fetch", "--prune"])


def ahead_behind(repo_path: Path, branch: str) -> tuple[int, int] | None:
    """(ahead, behind) counts of HEAD vs origin/<branch>, or None if that
    remote-tracking ref doesn't exist locally (e.g. never fetched)."""
    result = _run(
        repo_path,
        ["rev-list", "--left-right", "--count", f"HEAD...origin/{branch}"],
        check=False,
    )
    if result.returncode != 0:
        return None
    ahead, behind = result.stdout.split()
    return int(ahead), int(behind)


def is_synced(repo_path: Path, branch: str) -> bool:
    """True if HEAD is neither ahead of nor behind origin/<branch>."""
    counts = ahead_behind(repo_path, branch)
    return counts == (0, 0)


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


def _commit(repo_path: Path, commit_args: list[str], committer_name: str, committer_email: str) -> None:
    """Commit with an explicit identity passed via -c, rather than relying on
    the cron-iterate account having git user.name/user.email configured
    globally - keeps the tool self-contained with no extra install step."""
    _run(
        repo_path,
        ["-c", f"user.name={committer_name}", "-c", f"user.email={committer_email}", *commit_args],
    )


def commit_all(repo_path: Path, message: str, committer_name: str, committer_email: str) -> None:
    _run(repo_path, ["add", "-A"])
    _commit(repo_path, ["commit", "-m", message], committer_name, committer_email)


def commit_empty(repo_path: Path, message: str, committer_name: str, committer_email: str) -> None:
    """For --dry-run: makes an empty commit instead of staging changes, since
    the agent was never invoked and there's nothing to stage."""
    _commit(repo_path, ["commit", "--allow-empty", "-m", message], committer_name, committer_email)


def push(repo_path: Path, branch: str) -> None:
    _run(repo_path, ["push", "origin", f"HEAD:{branch}"])
