import json
import threading

import pytest

from lib import state


@pytest.fixture(autouse=True)
def isolated_home(monkeypatch, tmp_path):
    monkeypatch.setenv("CRON_ITERATE_HOME", str(tmp_path))
    return tmp_path


def test_state_path_lives_under_base_dir(isolated_home):
    assert state.state_path() == isolated_home / "state.json"


def test_load_state_defaults_when_missing(isolated_home):
    assert state.load_state() == {"last_index": -1}


def test_save_state_then_load_state_round_trips(isolated_home):
    state.save_state({"last_index": 3, "extra": "value"})

    assert state.load_state() == {"last_index": 3, "extra": "value"}


def test_save_state_creates_parent_directories(isolated_home, monkeypatch):
    nested_home = isolated_home / "nested" / "dir"
    monkeypatch.setenv("CRON_ITERATE_HOME", str(nested_home))

    state.save_state({"last_index": 0})

    assert (nested_home / "state.json").exists()


def test_save_state_does_not_leave_tmp_file_behind(isolated_home):
    state.save_state({"last_index": 1})

    assert not (isolated_home / "state.json.tmp").exists()
    assert (isolated_home / "state.json").exists()


def test_next_repo_index_starts_at_zero(isolated_home):
    assert state.next_repo_index(3) == 0


def test_next_repo_index_advances_and_persists(isolated_home):
    assert state.next_repo_index(3) == 0
    assert state.next_repo_index(3) == 1
    assert state.next_repo_index(3) == 2

    saved = json.loads((isolated_home / "state.json").read_text())
    assert saved["last_index"] == 2


def test_next_repo_index_wraps_around(isolated_home):
    state.save_state({"last_index": 2})

    assert state.next_repo_index(3) == 0


def test_next_repo_index_creates_lock_file(isolated_home):
    state.next_repo_index(3)

    assert state.lock_path().exists()


def test_next_repo_index_is_race_free_under_concurrency(isolated_home):
    num_repos = 5
    call_count = 20
    results = []
    results_lock = threading.Lock()

    def worker():
        result = state.next_repo_index(num_repos)
        with results_lock:
            results.append(result)

    threads = [threading.Thread(target=worker) for _ in range(call_count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == call_count
    saved = json.loads((isolated_home / "state.json").read_text())
    assert saved["last_index"] == (call_count - 1) % num_repos
