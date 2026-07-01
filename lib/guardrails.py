"""Forbidden-path guardrail checks.

fnmatch treats '*' as matching any character including '/', which is
exactly what we want for patterns like ".git/**" or "**/*.pem" without
needing a dedicated glob library.
"""

import fnmatch


def find_violations(changed_files: list[str], forbidden_paths: list[str]) -> list[str]:
    """Return the subset of changed_files that match any forbidden pattern."""
    violations = []
    for file_path in changed_files:
        for pattern in forbidden_paths:
            if fnmatch.fnmatch(file_path, pattern):
                violations.append(file_path)
                break
    return violations
