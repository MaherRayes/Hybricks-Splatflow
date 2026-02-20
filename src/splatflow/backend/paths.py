from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_config_dir, user_data_dir


@dataclass(frozen=True)
class AppPaths:
    app_name: str = "SplatFlow"
    app_author: str = "SplatFlow"
    data_dir_override: str | None = None
    config_dir_override: str | None = None

    @property
    def data_dir(self) -> Path:
        if self.data_dir_override:
            return Path(self.data_dir_override)
        return Path(user_data_dir(self.app_name, self.app_author))

    @property
    def config_dir(self) -> Path:
        if self.config_dir_override:
            return Path(self.config_dir_override)
        return Path(user_config_dir(self.app_name, self.app_author))

    @property
    def tools_dir(self) -> Path:
        return self.data_dir / "tools"

    @property
    def jobs_dir(self) -> Path:
        return self.data_dir / "jobs"

    def ensure(self) -> "AppPaths":
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.tools_dir.mkdir(parents=True, exist_ok=True)
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        return self
