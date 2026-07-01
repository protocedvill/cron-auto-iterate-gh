from lib import backlog


def test_ensure_exists_creates_file_with_header(tmp_path):
    backlog.ensure_exists(tmp_path, "TODO.md")

    path = tmp_path / "TODO.md"
    assert path.exists()
    assert path.read_text().startswith(backlog.HEADER)


def test_ensure_exists_leaves_existing_file_untouched(tmp_path):
    path = tmp_path / "TODO.md"
    path.write_text("# Custom\n\n- [ ] keep me\n")

    backlog.ensure_exists(tmp_path, "TODO.md")

    assert path.read_text() == "# Custom\n\n- [ ] keep me\n"


def test_first_unchecked_returns_missing_file_as_none(tmp_path):
    assert backlog.first_unchecked(tmp_path, "TODO.md") is None


def test_first_unchecked_returns_first_unchecked_item(tmp_path):
    (tmp_path / "TODO.md").write_text(
        "# Auto-iteration backlog\n\n"
        "- [x] done already\n"
        "- [ ] first pending task\n"
        "- [ ] second pending task\n"
    )

    assert backlog.first_unchecked(tmp_path, "TODO.md") == "first pending task"


def test_first_unchecked_ignores_non_checkbox_lines(tmp_path):
    (tmp_path / "TODO.md").write_text(
        "# Auto-iteration backlog\n\nsome notes\n\n- [ ] the real task\n"
    )

    assert backlog.first_unchecked(tmp_path, "TODO.md") == "the real task"


def test_first_unchecked_handles_uppercase_x(tmp_path):
    (tmp_path / "TODO.md").write_text("- [X] done\n- [ ] pending\n")

    assert backlog.first_unchecked(tmp_path, "TODO.md") == "pending"


def test_first_unchecked_returns_none_when_all_checked(tmp_path):
    (tmp_path / "TODO.md").write_text("- [x] one\n- [X] two\n")

    assert backlog.first_unchecked(tmp_path, "TODO.md") is None


def test_has_unchecked_true_when_pending_item_exists(tmp_path):
    (tmp_path / "TODO.md").write_text("- [ ] pending\n")

    assert backlog.has_unchecked(tmp_path, "TODO.md") is True


def test_has_unchecked_false_when_no_file(tmp_path):
    assert backlog.has_unchecked(tmp_path, "TODO.md") is False


def test_has_unchecked_false_when_all_checked(tmp_path):
    (tmp_path / "TODO.md").write_text("- [x] done\n")

    assert backlog.has_unchecked(tmp_path, "TODO.md") is False
