"""Modelos Claude permitidos para encargos agénticos."""
from typing import Final, Literal

ClaudeModel = Literal[
    "claude-sonnet-5",
    "claude-fable-5",
    "claude-opus-4-8",
    "claude-haiku-4-5",
]

DEFAULT_CLAUDE_MODEL: Final[ClaudeModel] = "claude-sonnet-5"