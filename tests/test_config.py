from pathlib import Path

import pytest

from lib import config


def test_base_dir_defaults_to_var_lib_cron_iterate(monkeypatch):
    monkeypatch.delenv("CRON_ITERATE_HOME", raising=False)

    assert config.base_dir() == Path("/var/lib/cron-iterate")


def test_base_dir_honors_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("CRON_ITERATE_HOME", str(tmp_path))

    assert config.base_dir() == tmp_path


def test_config_path_defaults_to_base_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("CRON_ITERATE_HOME", str(tmp_path))

    assert config.config_path() == tmp_path / "config.yaml"


def test_config_path_returns_explicit_path_untouched(tmp_path):
    explicit = tmp_path / "custom.yaml"

    assert config.config_path(explicit) == explicit


def test_load_config_missing_file_raises(tmp_path):
    with pytest.raises(config.ConfigError, match="not found"):
        config.load_config(tmp_path / "missing.yaml")


def test_load_config_requires_at_least_one_repo(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("repos: []\n")

    with pytest.raises(config.ConfigError, match="no repos"):
        config.load_config(path)


def test_load_config_requires_name_and_remote(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("repos:\n  - name: only-name\n")

    with pytest.raises(config.ConfigError, match="remote"):
        config.load_config(path)


def test_load_config_rejects_duplicate_repo_names(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        "repos:\n"
        "  - name: dup\n"
        "    remote: git@example.com:a/dup.git\n"
        "  - name: dup\n"
        "    remote: git@example.com:b/dup.git\n"
    )

    with pytest.raises(config.ConfigError, match="duplicate repo name"):
        config.load_config(path)


def test_load_config_applies_defaults(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        "repos:\n"
        "  - name: repo-a\n"
        "    remote: git@example.com:org/repo-a.git\n"
    )

    result = config.load_config(path)

    assert len(result.repos) == 1
    repo = result.repos[0]
    assert repo.name == "repo-a"
    assert repo.remote == "git@example.com:org/repo-a.git"
    assert repo.todo_file == config.DEFAULT_TODO_FILE
    assert repo.max_turns == config.DEFAULT_MAX_TURNS
    assert repo.timeout_seconds == config.DEFAULT_TIMEOUT_SECONDS
    assert repo.forbidden_paths == config.DEFAULT_FORBIDDEN_PATHS
    assert repo.committer_name == config.DEFAULT_COMMITTER_NAME
    assert repo.committer_email == config.DEFAULT_COMMITTER_EMAIL


def test_load_config_top_level_defaults_override_builtin_defaults(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        "defaults:\n"
        "  max_turns: 5\n"
        "  timeout_seconds: 60\n"
        "  committer_name: custom-bot\n"
        "  committer_email: bot@example.com\n"
        "repos:\n"
        "  - name: repo-a\n"
        "    remote: git@example.com:org/repo-a.git\n"
    )

    repo = config.load_config(path).repos[0]

    assert repo.max_turns == 5
    assert repo.timeout_seconds == 60
    assert repo.committer_name == "custom-bot"
    assert repo.committer_email == "bot@example.com"


def test_load_config_per_repo_overrides_top_level_defaults(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        "defaults:\n"
        "  max_turns: 5\n"
        "repos:\n"
        "  - name: repo-a\n"
        "    remote: git@example.com:org/repo-a.git\n"
        "    max_turns: 99\n"
        "    todo_file: BACKLOG.md\n"
        "    branch: feature-x\n"
        "    test_cmd: pytest\n"
    )

    repo = config.load_config(path).repos[0]

    assert repo.max_turns == 99
    assert repo.todo_file == "BACKLOG.md"
    assert repo.branch == "feature-x"
    assert repo.test_cmd == "pytest"


def test_repo_config_path_property(monkeypatch, tmp_path):
    monkeypatch.setenv("CRON_ITERATE_HOME", str(tmp_path))
    repo = config.RepoConfig(name="myrepo", remote="git@example.com:org/myrepo.git")

    assert repo.path == tmp_path / "repos" / "myrepo"
