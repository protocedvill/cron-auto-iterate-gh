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

    if not git_ops.is_clean(repo_path):
        raise AbortRun("working tree is not clean")

    git_ops.fetch(repo_path)
    if not git_ops.is_synced(repo_path, branch):
        raise AbortRun(f"not in sync with origin/{branch}")

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

    pre_commit = git_ops.get_head_commit(repo_path)
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
        git_ops.reset_hard(repo_path, pre_commit)
        raise AbortRun("agent made no changes")

    violations = guardrails.find_violations(changed, repo_cfg.forbidden_paths)
    if violations:
        git_ops.reset_hard(repo_path, pre_commit)
        raise AbortRun(f"forbidden path(s) touched: {violations}")

    if mode == "brainstorm" and changed != [repo_cfg.todo_file]:
        git_ops.reset_hard(repo_path, pre_commit)
        raise AbortRun(f"brainstorm mode touched unexpected files: {changed}")

    if mode == "implement" and repo_cfg.test_cmd:
        result = subprocess.run(
            repo_cfg.test_cmd, shell=True, cwd=repo_path, capture_output=True, text=True
        )
        if result.returncode != 0:
            git_ops.reset_hard(repo_path, pre_commit)
            raise AbortRun(
                f"validation command '{repo_cfg.test_cmd}' failed:\n{result.stdout}\n{result.stderr}"
            )

    if mode == "implement":
        message = f"Auto-iterate: {task}\n\nCo-Authored-By: Claude <noreply@anthropic.com>"
    else:
        message = "chore: add auto-iteration ideas to TODO.md\n\nCo-Authored-By: Claude <noreply@anthropic.com>"

    git_ops.commit_all(repo_path, message)
    git_ops.push(repo_path, branch)
    logger.info("[%s] pushed %s change to %s", repo_cfg.name, mode, branch)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, help="override path to config.yaml")
    parser.add_argument(
        "--repo", help="force a specific repo by name instead of round-robin selection"
    )
    args = parser.parse_args()

    try:
        config = load_config(args.config)
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
