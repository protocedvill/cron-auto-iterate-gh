"""Round-robin pointer persistence (state.json) for cron-auto-iterate-gh."""

import json
from pathlib import Path

from lib.config import base_dir


def state_path() -> Path:
    return base_dir() / "state.json"


def load_state() -> dict:
    path = state_path()
    if not path.exists():
        return {"last_index": -1}
    with open(path) as f:
        return json.load(f)


def save_state(state: dict) -> None:
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w") as f:
        json.dump(state, f)
    tmp.replace(path)


def next_repo_index(num_repos: int) -> int:
    """Advance and persist the round-robin pointer, returning the new index."""
    state = load_state()
    index = (state.get("last_index", -1) + 1) % num_repos
    state["last_index"] = index
    save_state(state)
    return index
