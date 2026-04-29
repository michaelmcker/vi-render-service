"""LLM dispatch.

The main agent operates on **Codex** — her ChatGPT-subscription-backed CLI.
`claude -p` is one of the tools Codex can call when Claude is a better fit
(typically: voice-grounded drafting, longer creative synthesis).

Selection order for a Hermes call:
  1. Explicit `backend=` arg ('codex' or 'claude') — caller wins.
  2. Per-prompt override via `LLM_BACKEND_<PROMPT>` env var
     (e.g. LLM_BACKEND_DRAFT_REPLY=claude).
  3. HERMES_LLM_DEFAULT env var (default: 'codex').

Both backends are CLI subprocesses on the daemon Mac — no API keys, both
covered by her existing subscriptions.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from pathlib import Path

log = logging.getLogger("hermes.llm")

CODEX_BIN = shutil.which("codex") or os.environ.get("HERMES_CODEX_BIN", "/usr/local/bin/codex")
CLAUDE_BIN = shutil.which("claude") or os.environ.get("HERMES_CLAUDE_BIN", "/usr/local/bin/claude")

# Codex CLI invocation. Override via HERMES_CODEX_ARGS if upstream changes flags.
# Default: `codex exec --skip-git-repo-check` — non-interactive, no git nag.
CODEX_ARGS = os.environ.get("HERMES_CODEX_ARGS", "exec --skip-git-repo-check").split()

DEFAULT_BACKEND = os.environ.get("HERMES_LLM_DEFAULT", "codex")


class LLMError(RuntimeError):
    pass


def run(prompt_path: Path, payload: str, *, expect_json: bool = False,
        timeout: int = 120, backend: str | None = None) -> str | dict:
    """Dispatch to the right CLI. See module docstring for selection order."""
    chosen = backend or _per_prompt_backend(prompt_path) or DEFAULT_BACKEND
    if chosen == "codex":
        return codex_run(prompt_path, payload, expect_json=expect_json, timeout=timeout)
    if chosen == "claude":
        return claude_run(prompt_path, payload, expect_json=expect_json, timeout=timeout)
    raise LLMError(f"unknown backend: {chosen!r} (expected 'codex' or 'claude')")


def _per_prompt_backend(prompt_path: Path) -> str | None:
    """LLM_BACKEND_<UPPERCASED_PROMPT_NAME> env var — lets Nikki force a
    specific backend per prompt without touching code. Example:
        LLM_BACKEND_DRAFT_REPLY=claude
    pins all draft_reply.md calls to Claude.
    """
    key = f"LLM_BACKEND_{prompt_path.stem.upper()}"
    return os.environ.get(key)


# ────────────────────────── Codex (primary) ──────────────────────────

def codex_run(prompt_path: Path, payload: str, *, expect_json: bool = False,
              timeout: int = 120) -> str | dict:
    """Pipe `<system_prompt>\n\n<payload>` to `codex exec`. Returns stdout
    text, or the parsed JSON object if expect_json=True (the prompt itself
    must instruct JSON-only output).
    """
    if not Path(CODEX_BIN).exists():
        raise LLMError(
            f"`codex` CLI not found at {CODEX_BIN}. Install Codex (the OpenAI "
            "agent CLI), authenticate via `codex login`, and ensure it is on "
            "PATH for the launchd user."
        )
    system = prompt_path.read_text()
    full_input = f"{system}\n\n{payload}"
    args = [CODEX_BIN, *CODEX_ARGS]

    log.debug("calling codex (%d-byte input)", len(full_input))
    try:
        proc = subprocess.run(
            args, input=full_input, capture_output=True, text=True,
            timeout=timeout, check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise LLMError(f"codex timed out after {timeout}s") from e

    if proc.returncode != 0:
        raise LLMError(
            f"codex exited {proc.returncode}: "
            f"{(proc.stderr or proc.stdout).strip()[:500]}"
        )

    out = (proc.stdout or "").strip()
    if not expect_json:
        return out
    return _parse_json_loose(out)


# ────────────────────────── Claude (tool) ──────────────────────────

def claude_run(prompt_path: Path, payload: str, *, expect_json: bool = False,
               timeout: int = 120) -> str | dict:
    """Shell out to `claude -p` for prompts where Claude is the better fit.

    Codex can also call this as a tool during its own reasoning — the
    daemon's direct calls and Codex's tool calls share the same wrapper.
    """
    if not Path(CLAUDE_BIN).exists():
        raise LLMError(
            f"`claude` CLI not found at {CLAUDE_BIN}. Install Claude Code "
            "and ensure the launchd user is signed in."
        )
    system = prompt_path.read_text()
    args = [CLAUDE_BIN, "-p", "--system-prompt", system]
    if expect_json:
        args += ["--output-format", "json"]

    log.debug("calling claude -p (%d-byte payload)", len(payload))
    try:
        proc = subprocess.run(
            args, input=payload, capture_output=True, text=True,
            timeout=timeout, check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise LLMError(f"claude -p timed out after {timeout}s") from e

    if proc.returncode != 0:
        raise LLMError(
            f"claude -p exited {proc.returncode}: "
            f"{(proc.stderr or proc.stdout).strip()[:500]}"
        )

    out = (proc.stdout or "").strip()
    if not expect_json:
        return out
    return _parse_json_loose(out)


# ────────────────────────── helpers ──────────────────────────

def _parse_json_loose(text: str) -> dict:
    """Try strict JSON, then unwrap a single envelope.result (claude -p), then
    pull out the first {...} block as a last resort.
    """
    if not text:
        raise LLMError("LLM returned empty output where JSON was expected")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    try:
        envelope = json.loads(text)
        inner = envelope.get("result", envelope) if isinstance(envelope, dict) else envelope
        if isinstance(inner, str):
            return json.loads(inner)
        if isinstance(inner, dict):
            return inner
    except (json.JSONDecodeError, AttributeError):
        pass
    # Last resort: grab the first {...} block.
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass
    raise LLMError(f"could not parse LLM output as JSON: {text[:300]!r}")
