from lib import agent


def test_render_prompt_substitutes_kwargs(tmp_path, monkeypatch):
    monkeypatch.setattr(agent, "PROMPTS_DIR", tmp_path)
    (tmp_path / "greet.md").write_text("Hello {name}")

    assert agent.render_prompt("greet", name="world") == "Hello world"


def test_render_prompt_survives_literal_braces(tmp_path, monkeypatch):
    monkeypatch.setattr(agent, "PROMPTS_DIR", tmp_path)
    (tmp_path / "task.md").write_text("Task:\n{task}\n")

    task = 'Fix the config: {"key": "value"}'

    assert agent.render_prompt("task", task=task) == f"Task:\n{task}\n"
