"""Config loading: .env + importance.yaml. Hot-reloads importance.yaml on read."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path(__file__).resolve().parent.parent))
load_dotenv(HERMES_HOME / ".env")

IMPORTANCE_PATH = HERMES_HOME / "config" / "importance.yaml"
SECRETS_DIR = HERMES_HOME / "secrets"
STATE_PATH = HERMES_HOME / "state.sqlite"
PROMPTS_DIR = HERMES_HOME / "prompts"


@dataclass
class Importance:
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls) -> "Importance":
        if not IMPORTANCE_PATH.exists():
            example = HERMES_HOME / "config" / "importance.example.yaml"
            return cls(raw=yaml.safe_load(example.read_text()))
        return cls(raw=yaml.safe_load(IMPORTANCE_PATH.read_text()))

    @property
    def email(self) -> dict[str, Any]:
        return self.raw.get("email", {})

    @property
    def slack(self) -> dict[str, Any]:
        return self.raw.get("slack", {})

    @property
    def voice(self) -> dict[str, Any]:
        return self.raw.get("voice", {})

    @property
    def budget(self) -> dict[str, Any]:
        return self.raw.get("budget", {})


def env(key: str, default: str | None = None) -> str:
    val = os.environ.get(key, default)
    if val is None:
        raise RuntimeError(f"Missing required env var: {key}")
    return val


def env_int(key: str, default: int) -> int:
    return int(os.environ.get(key, default))
