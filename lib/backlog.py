"""Read the TODO.md checklist backlog in a target repo.

The agent (not this script) is responsible for writing to TODO.md -
checking off implemented items or appending new brainstormed ones. This
module only needs to read it to decide implement-vs-brainstorm mode and to
extract the task text for the prompt.
"""

import re
from pathlib import Path

HEADER = "# Auto-iteration backlog\n"
_CHECKBOX_RE = re.compile(r"^- \[([ xX])\]\s+(.*)$")


def ensure_exists(repo_path: Path, todo_file: str) -> None:
    path = repo_path / todo_file
    if not path.exists():
        path.write_text(HEADER + "\n")


def _parse_items(repo_path: Path, todo_file: str) -> list[dict]:
    path = repo_path / todo_file
    if not path.exists():
        return []
    items = []
    for line in path.read_text().splitlines():
        match = _CHECKBOX_RE.match(line.strip())
        if match:
            checked = match.group(1).lower() == "x"
            items.append({"checked": checked, "text": match.group(2).strip()})
    return items


def first_unchecked(repo_path: Path, todo_file: str) -> str | None:
    for item in _parse_items(repo_path, todo_file):
        if not item["checked"]:
            return item["text"]
    return None


def has_unchecked(repo_path: Path, todo_file: str) -> bool:
    return first_unchecked(repo_path, todo_file) is not None
