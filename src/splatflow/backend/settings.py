from __future__ import annotations

import json
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any

from .paths import AppPaths


@dataclass
class ToolPaths:
    colmap: str | None = None
    lichtfeld: str | None = None


@dataclass
class ColmapInstall:
    """How SplatFlow should obtain COLMAP when it is not found in PATH.

    On Windows, the official COLMAP releases include a `COLMAP.bat` wrapper
    that sets up required library paths. We prefer using that official
    distribution by default.
    """

    source: str = "official"  # "official" | "conda"
    version: str = "latest"  # release tag like "3.13.0" or "latest"
    build: str = "cuda"  # "cuda" | "nocuda"


@dataclass
class Settings:
    tool_paths: ToolPaths = field(default_factory=ToolPaths)
    auto_install_tools: bool = True
    colmap: ColmapInstall = field(default_factory=ColmapInstall)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return data

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "Settings":
        tool_paths = ToolPaths(**(data.get("tool_paths") or {}))
        colmap = ColmapInstall(**(data.get("colmap") or {}))
        return Settings(
            tool_paths=tool_paths,
            auto_install_tools=bool(data.get("auto_install_tools", True)),
            colmap=colmap,
        )


class SettingsStore:
    def __init__(self, paths: AppPaths) -> None:
        self.paths = paths.ensure()
        self.path = self.paths.config_dir / "settings.json"

    def load(self) -> Settings:
        if not self.path.exists():
            return Settings()
        data = json.loads(self.path.read_text(encoding="utf-8"))
        return Settings.from_dict(data)

    def save(self, settings: Settings) -> None:
        self.path.write_text(json.dumps(settings.to_dict(), indent=2), encoding="utf-8")
