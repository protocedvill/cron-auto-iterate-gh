"""Render prompt templates and invoke headless Claude Code."""

import subprocess
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


def render_prompt(template_name: str, **kwargs) -> str:
    template = (PROMPTS_DIR / f"{template_name}.md").read_text()
    for key, value in kwargs.items():
        template = template.replace("{" + key + "}", value)
    return template


def run_claude(
    repo_path: Path,
    prompt: str,
    max_turns: int,
    timeout_seconds: int,
    log_path: Path,
) -> bool:
    """Run headless claude in repo_path. Returns True if the process exited 0.

    A non-zero/timed-out exit does not necessarily mean nothing changed -
    callers should inspect the working tree (via git_ops) regardless of the
    return value, but should treat a non-True result as a signal to be more
    cautious (e.g. it's still gated by the same guardrail/test checks either way).
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "claude",
        "-p",
        prompt,
        "--dangerously-skip-permissions",
        "--max-turns",
        str(max_turns),
    ]
    with open(log_path, "w") as log_file:
        try:
            result = subprocess.run(
                cmd,
                cwd=repo_path,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                timeout=timeout_seconds,
                text=True,
            )
            return result.returncode == 0
        except subprocess.TimeoutExpired:
            log_file.write(f"\n[iterate.py] TIMEOUT after {timeout_seconds}s\n")
            return False
