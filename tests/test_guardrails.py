from lib import guardrails
from lib.config import DEFAULT_FORBIDDEN_PATHS


def test_find_violations_matches_dotgit_directory():
    violations = guardrails.find_violations([".git/config"], [".git/**"])

    assert violations == [".git/config"]


def test_find_violations_matches_nested_pem_via_double_star():
    violations = guardrails.find_violations(
        ["deep/nested/dir/key.pem"], ["**/*.pem"]
    )

    assert violations == ["deep/nested/dir/key.pem"]


def test_find_violations_ignores_non_matching_files():
    violations = guardrails.find_violations(
        ["src/main.py", "README.md"], DEFAULT_FORBIDDEN_PATHS
    )

    assert violations == []


def test_find_violations_only_reports_each_file_once():
    # id_rsa.pub matches both "**/id_rsa*" style patterns if duplicated;
    # ensure a file matching multiple patterns is only reported once.
    violations = guardrails.find_violations(
        ["id_rsa"], ["**/id_rsa*", "id_rsa*"]
    )

    assert violations == ["id_rsa"]


def test_find_violations_preserves_order_and_reports_multiple_files():
    changed = ["src/app.py", ".env", "notes.txt", "backend/secrets/token.txt"]
    violations = guardrails.find_violations(changed, DEFAULT_FORBIDDEN_PATHS)

    assert violations == [".env", "backend/secrets/token.txt"]


def test_find_violations_top_level_env_pattern_misses_nested_env():
    # Documents the current (known-buggy) behavior of the default
    # ".env*" pattern: fnmatch's "*" does not cross "/", so nested env
    # files are not caught without a "**/" prefix.
    violations = guardrails.find_violations(["backend/.env"], [".env*"])

    assert violations == []


def test_find_violations_empty_forbidden_paths_allows_everything():
    violations = guardrails.find_violations(["anything.py"], [])

    assert violations == []
