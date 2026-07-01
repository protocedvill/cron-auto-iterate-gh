"""Load and validate config.yaml for cron-auto-iterate-gh.

See plan.md for the full config format and rationale. The runtime base
directory (where repos/, logs/, state.json and config.yaml itself live) is
/var/lib/cron-iterate by default, overridable via CRON_ITERATE_HOME so the
tool can be exercised locally without the dedicated system user.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

DEFAULT_TODO_FILE = "TODO.md"
DEFAULT_MAX_TURNS = 40
DEFAULT_TIMEOUT_SECONDS = 900
DEFAULT_FORBIDDEN_PATHS = [
    ".git/**",
    ".env*",
    "**/*.pem",
    "**/id_rsa*",
    ".github/workflows/**",
    "**/secrets/**",
]
DEFAULT_COMMITTER_NAME = "cron-auto-iterate-gh"
DEFAULT_COMMITTER_EMAIL = "cron-iterate@localhost"


class ConfigError(Exception):
    pass


def base_dir() -> Path:
    return Path(os.environ.get("CRON_ITERATE_HOME", "/var/lib/cron-iterate"))


def config_path(path: Path | None = None) -> Path:
    """Resolve which config.yaml a run will actually use - deploy.sh never
    copies config.yaml (so editing the live one isn't clobbered by a code
    redeploy), which means the dev repo's config.yaml and the live one at
    base_dir()/config.yaml are two independent files that can silently
    drift apart. Centralized here so callers log the same path they load."""
    return path or (base_dir() / "config.yaml")


@dataclass
class RepoConfig:
    name: str
    remote: str
    test_cmd: str | None = None
    todo_file: str = DEFAULT_TODO_FILE
    branch: str | None = None
    max_turns: int = DEFAULT_MAX_TURNS
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    forbidden_paths: list = field(default_factory=lambda: list(DEFAULT_FORBIDDEN_PATHS))
    committer_name: str = DEFAULT_COMMITTER_NAME
    committer_email: str = DEFAULT_COMMITTER_EMAIL

    @property
    def path(self) -> Path:
        return base_dir() / "repos" / self.name


@dataclass
class Config:
    repos: list[RepoConfig]


def _require(mapping: dict, key: str, context: str) -> object:
    if key not in mapping or mapping[key] in (None, ""):
        raise ConfigError(f"{context}: missing required field '{key}'")
    return mapping[key]


def load_config(path: Path | None = None) -> Config:
    path = config_path(path)
    if not path.exists():
        raise ConfigError(f"config file not found: {path}")

    with open(path) as f:
        raw = yaml.safe_load(f) or {}

    raw_repos = raw.get("repos") or []
    if not raw_repos:
        raise ConfigError("config has no repos configured")

    defaults = raw.get("defaults") or {}
    default_max_turns = defaults.get("max_turns", DEFAULT_MAX_TURNS)
    default_timeout = defaults.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
    default_forbidden = defaults.get("forbidden_paths", DEFAULT_FORBIDDEN_PATHS)
    default_committer_name = defaults.get("committer_name", DEFAULT_COMMITTER_NAME)
    default_committer_email = defaults.get("committer_email", DEFAULT_COMMITTER_EMAIL)

    repos = []
    seen_names = set()
    for i, entry in enumerate(raw_repos):
        context = f"repos[{i}]"
        name = _require(entry, "name", context)
        remote = _require(entry, "remote", context)
        if name in seen_names:
            raise ConfigError(f"{context}: duplicate repo name '{name}'")
        seen_names.add(name)

        repos.append(
            RepoConfig(
                name=name,
                remote=remote,
                test_cmd=entry.get("test_cmd"),
                todo_file=entry.get("todo_file", DEFAULT_TODO_FILE),
                branch=entry.get("branch"),
                max_turns=entry.get("max_turns", default_max_turns),
                timeout_seconds=entry.get("timeout_seconds", default_timeout),
                forbidden_paths=entry.get("forbidden_paths", default_forbidden),
                committer_name=entry.get("committer_name", default_committer_name),
                committer_email=entry.get("committer_email", default_committer_email),
            )
        )

    return Config(repos=repos)
