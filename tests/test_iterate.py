import iterate


def test_version_info_includes_iterate_lib_and_prompts_hash():
    info = iterate.version_info()

    assert info.startswith("iterate.py+lib+prompts sha256=")
    assert "path=" in info


def test_version_info_changes_when_a_lib_file_changes(tmp_path, monkeypatch):
    import shutil
    from pathlib import Path

    repo_root = Path(iterate.__file__).resolve().parent
    fake_root = tmp_path / "fake_root"
    shutil.copytree(repo_root / "lib", fake_root / "lib")
    shutil.copytree(repo_root / "prompts", fake_root / "prompts")
    shutil.copy(repo_root / "iterate.py", fake_root / "iterate.py")

    monkeypatch.setattr(iterate, "__file__", str(fake_root / "iterate.py"))
    before = iterate.version_info()

    (fake_root / "lib" / "state.py").write_text(
        (fake_root / "lib" / "state.py").read_text() + "\n# tweak\n"
    )
    after = iterate.version_info()

    assert before != after
