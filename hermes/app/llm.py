"""Wraps `claude -p` so the daemon stays subscription-only (no API keys).

`claude` must be installed, authenticated, and on PATH for the launchd user.
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path

log = logging.getLogger("hermes.llm")

CLAUDE_BIN = shutil.which("claude") or "/usr/local/bin/claude"


class LLMError(RuntimeError):
    pass


def run(prompt_path: Path, payload: str, *, expect_json: bool = False, timeout: int = 90) -> str | dict:
    """Invoke `claude -p` with the system prompt at prompt_path and stdin=payload.

    Args:
        prompt_path: file containing the system/instruction prompt.
        payload: user content (email body, slack message, thread, etc.).
        expect_json: if True, parse stdout as JSON and return the dict.
        timeout: seconds before giving up.
    """
    if not Path(CLAUDE_BIN).exists():
        raise LLMError(
            f"`claude` CLI not found at {CLAUDE_BIN}. "
            "Install Claude Code and ensure the launchd user is signed in."
        )

    system = prompt_path.read_text()
    args = [CLAUDE_BIN, "-p", "--system-prompt", system]
    if expect_json:
        args += ["--output-format", "json"]

    log.debug("calling claude -p (%d-byte payload)", len(payload))
    try:
        proc = subprocess.run(
            args, input=payload, capture_output=True, text=True, timeout=timeout, check=False
        )
    except subprocess.TimeoutExpired as e:
        raise LLMError(f"claude -p timed out after {timeout}s") from e

    if proc.returncode != 0:
        raise LLMError(
            f"claude -p exited {proc.returncode}: {proc.stderr.strip() or proc.stdout.strip()}"
        )

    out = proc.stdout.strip()
    if not expect_json:
        return out

    try:
        return json.loads(out)
    except json.JSONDecodeError:
        # `claude -p --output-format json` wraps the model's text in an envelope;
        # the model's JSON object lives in `result`. Try once more.
        try:
            envelope = json.loads(out)
            inner = envelope.get("result", envelope)
            if isinstance(inner, str):
                return json.loads(inner)
            return inner
        except (json.JSONDecodeError, AttributeError) as e:
            raise LLMError(f"could not parse claude output as JSON: {out[:300]!r}") from e
