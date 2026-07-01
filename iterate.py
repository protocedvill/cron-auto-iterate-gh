#!/usr/bin/env python3
"""cron-auto-iterate-gh entrypoint.

Picks one configured repo (round-robin), has headless Claude Code either
implement the next TODO.md item or brainstorm new ones, validates the
result, and pushes it. See plan.md for the full design and run sequence.

Intended to be invoked once per systemd timer tick, running as the
unprivileged cron-iterate system user with cwd irrelevant (paths are
derived from CRON_ITERATE_HOME / /var/lib/cron-iterate).
"""

import argparse
import hashlib
import logging
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from lib import agent, backlog, git_ops, guardrails, state
from lib.config import Config, ConfigError, RepoConfig, base_dir, load_config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("iterate")


class AbortRun(Exception):
    """Raised to cleanly stop processing the selected repo for this run."""


def version_info() -> str:
    """Identify exactly which code is running - logged on every invocation so
    `journalctl -u cron-iterate` alone answers "am I running stale code?"
    without needing filesystem access to /opt (which is root-owned).
    """
    script_path = Path(__file__).resolve()
    file_hash = hashlib.sha256(script_path.read_bytes()).hexdigest()[:12]
    version_file = script_path.parent / "VERSION"
    if version_file.exists():
        deploy_stamp = version_file.read_text().strip()
    else:
        deploy_stamp = "no VERSION file found (deployed without deploy.sh, or a version predating this feature)"
    return f"iterate.py sha256={file_hash} path={script_path} | {deploy_stamp}"


def pick_repo(config: Config, forced_name: str | None) -> RepoConfig:
    if forced_name:
        for repo in config.repos:
            if repo.name == forced_name:
                return repo
        raise ConfigError(f"no repo named '{forced_name}' in config")
    index = state.next_repo_index(len(config.repos))
    return config.repos[index]


def run_for_repo(repo_cfg: RepoConfig) -> None:
    repo_path = repo_cfg.path

    if git_ops.clone_if_missing(repo_path, repo_cfg.remote):
        logger.info("cloned %s into %s", repo_cfg.remote, repo_path)

    branch = repo_cfg.branch or git_ops.get_current_branch(repo_path)
    logger.info("[%s] path=%s branch=%s", repo_cfg.name, repo_path, branch)

    dirty = git_ops.status_porcelain(repo_path)
    if dirty:
        raise AbortRun(
            "working tree is not clean - `git status --porcelain` shows:\n" + dirty
        )

    git_ops.fetch(repo_path)
    counts = git_ops.ahead_behind(repo_path, branch)
    if counts is None:
        raise AbortRun(
            f"no origin/{branch} tracking ref found after fetch "
            "(remote branch renamed/deleted, or 'branch:' in config.yaml is wrong?)"
        )
    if counts != (0, 0):
        ahead, behind = counts
        raise AbortRun(
            f"not in sync with origin/{branch}: {ahead} commit(s) ahead, "
            f"{behind} commit(s) behind"
        )

    # Nothing has touched the working tree yet at this point. Everything
    # from here on (writing TODO.md, running the agent, running test_cmd)
    # can fail in ways we didn't anticipate - always roll back to this
    # commit on ANY exception so a crash never leaves the shared clone
    # dirty for the next scheduled run.
    pre_commit = git_ops.get_head_commit(repo_path)
    try:
        _iterate_once(repo_cfg, repo_path, branch, pre_commit)
    except Exception:
        git_ops.reset_hard(repo_path, pre_commit)
        raise


def _iterate_once(repo_cfg: RepoConfig, repo_path: Path, branch: str, pre_commit: str) -> None:
    backlog.ensure_exists(repo_path, repo_cfg.todo_file)
    task = backlog.first_unchecked(repo_path, repo_cfg.todo_file)

    if task:
        mode = "implement"
        prompt = agent.render_prompt("implement_task", task=task)
        logger.info("[%s] implement mode: %s", repo_cfg.name, task)
    else:
        mode = "brainstorm"
        prompt = agent.render_prompt("brainstorm")
        logger.info("[%s] brainstorm mode (no open TODO items)", repo_cfg.name)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log_path = base_dir() / "logs" / f"{repo_cfg.name}-{timestamp}.log"

    completed_cleanly = agent.run_claude(
        repo_path, prompt, repo_cfg.max_turns, repo_cfg.timeout_seconds, log_path
    )
    if not completed_cleanly:
        logger.warning(
            "[%s] claude process exited non-zero or timed out (log: %s); "
            "still checking the working tree for a salvageable diff",
            repo_cfg.name,
            log_path,
        )

    changed = git_ops.changed_files(repo_path)
    if not changed:
        raise AbortRun("agent made no changes")

    violations = guardrails.find_violations(changed, repo_cfg.forbidden_paths)
    if violations:
        raise AbortRun(f"forbidden path(s) touched: {violations}")

    if mode == "brainstorm" and changed != [repo_cfg.todo_file]:
        raise AbortRun(f"brainstorm mode touched unexpected files: {changed}")

    if mode == "implement" and repo_cfg.test_cmd:
        result = subprocess.run(
            repo_cfg.test_cmd, shell=True, cwd=repo_path, capture_output=True, text=True
        )
        if result.returncode != 0:
            raise AbortRun(
                f"validation command '{repo_cfg.test_cmd}' failed:\n{result.stdout}\n{result.stderr}"
            )

    if mode == "implement":
        message = f"Auto-iterate: {task}\n\nCo-Authored-By: Claude <noreply@anthropic.com>"
    else:
        message = "chore: add auto-iteration ideas to TODO.md\n\nCo-Authored-By: Claude <noreply@anthropic.com>"

    git_ops.commit_all(repo_path, message, repo_cfg.committer_name, repo_cfg.committer_email)
    git_ops.push(repo_path, branch)
    logger.info("[%s] pushed %s change to %s", repo_cfg.name, mode, branch)


def run_diagnostics(repo_cfg: RepoConfig) -> None:
    """Read-only report on one repo's state. Never runs the agent, never
    commits/pushes/resets. `git fetch` is the only network/state-updating
    call made (same as a real run would do); nothing else is touched.
    """
    print(f"\n=== {repo_cfg.name} ===")
    print(f"remote:      {repo_cfg.remote}")
    print(f"local path:  {repo_cfg.path}")

    if not repo_cfg.path.exists():
        print("status:      NOT CLONED YET (will be cloned fresh on the next real run)")
        return

    branch = repo_cfg.branch or git_ops.get_current_branch(repo_cfg.path)
    print(f"branch:      {branch}")

    dirty = git_ops.status_porcelain(repo_cfg.path)
    if dirty:
        print("working tree: DIRTY")
        for line in dirty.splitlines():
            print(f"  {line}")
    else:
        print("working tree: clean")

    try:
        git_ops.fetch(repo_cfg.path)
        counts = git_ops.ahead_behind(repo_cfg.path, branch)
        if counts is None:
            print(f"sync status: UNKNOWN (no origin/{branch} tracking ref found)")
        elif counts == (0, 0):
            print("sync status: in sync with origin")
        else:
            print(f"sync status: {counts[0]} ahead, {counts[1]} behind origin/{branch}")
    except git_ops.GitError as e:
        print(f"sync status: ERROR - {e}")

    task = backlog.first_unchecked(repo_cfg.path, repo_cfg.todo_file)
    if task:
        print(f"next backlog item: {task}")
    else:
        print("backlog: no open TODO.md items (next run will brainstorm new ones)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, help="override path to config.yaml")
    parser.add_argument(
        "--repo", help="force a specific repo by name instead of round-robin selection"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="read-only diagnostics for the selected repo(s) (or all repos, if --repo "
        "isn't given) - does not run the agent or modify anything",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="debug logging, including every git command run"
    )
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    logger.info(version_info())

    try:
        config = load_config(args.config)
    except ConfigError as e:
        logger.error("config error: %s", e)
        return 1

    if args.check:
        repos_to_check = [r for r in config.repos if not args.repo or r.name == args.repo]
        if args.repo and not repos_to_check:
            logger.error("no repo named '%s' in config", args.repo)
            return 1
        for repo_cfg in repos_to_check:
            run_diagnostics(repo_cfg)
        return 0

    try:
        repo_cfg = pick_repo(config, args.repo)
    except ConfigError as e:
        logger.error("config error: %s", e)
        return 1

    logger.info("selected repo: %s", repo_cfg.name)

    try:
        run_for_repo(repo_cfg)
    except AbortRun as e:
        logger.warning("[%s] run aborted: %s", repo_cfg.name, e)
        return 1
    except Exception:
        logger.exception("[%s] unexpected error", repo_cfg.name)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
