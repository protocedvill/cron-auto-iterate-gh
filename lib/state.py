"""Round-robin pointer persistence (state.json) for cron-auto-iterate-gh."""

import fcntl
import json
from pathlib import Path

from lib.config import base_dir


def state_path() -> Path:
    return base_dir() / "state.json"


def lock_path() -> Path:
    return base_dir() / "state.json.lock"


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
    """Advance and persist the round-robin pointer, returning the new index.

    Guarded by an flock on state.json.lock so overlapping iterate.py
    invocations can't race the read-modify-write.
    """
    path = lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        try:
            state = load_state()
            index = (state.get("last_index", -1) + 1) % num_repos
            state["last_index"] = index
            save_state(state)
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)
    return index
