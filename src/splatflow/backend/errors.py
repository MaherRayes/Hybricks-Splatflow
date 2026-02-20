from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


class SplatFlowError(Exception):
    """Base exception for SplatFlow."""


class ValidationError(SplatFlowError):
    pass


class ToolNotFoundError(SplatFlowError):
    pass


@dataclass(frozen=True)
class CommandFailedError(SplatFlowError):
    command: Sequence[str]
    returncode: int
    tail: str = ""

    def __str__(self) -> str:
        cmd = " ".join(map(str, self.command))
        msg = f"Command failed ({self.returncode}): {cmd}"
        if self.tail:
            msg += f"\n\n--- output (tail) ---\n{self.tail}"
        return msg
