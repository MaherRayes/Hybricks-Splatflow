from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..schema import LichtfeldConfig
from ..toolchain import Toolchain


@dataclass(frozen=True)
class LichtfeldTrainArgs:
    data_path: Path
    output_path: Path
    config: LichtfeldConfig

    def to_command(self, toolchain: Toolchain) -> tuple[list[str], dict[str, str]]:
        tool = toolchain.lichtfeld_exec()
        cfg = self.config

        cmd: list[str] = [
            *tool.prefix,
            "--data-path",
            str(self.data_path),
            "--output-path",
            str(self.output_path),
            "--iter",
            str(cfg.iterations),
            "--resize_factor",
            str(cfg.resize_factor),
            "--strategy",
            cfg.strategy,
            "--max-cap",
            str(cfg.max_cap),
            "--train",
            "--no-splash",
        ]

        if cfg.gut:
            cmd.append("--gut")
        if cfg.ppisp_controller:
            cmd.append("--ppisp-controller")
        if cfg.mip_filter:
            cmd.append("--enable-mip")
        if cfg.headless:
            cmd.append("--headless")
        if cfg.eval:
            cmd.append("--eval")
        if cfg.save_eval_images:
            cmd.append("--save-eval-images")
        if cfg.test_every:
            cmd += ["--test-every", str(cfg.test_every)]
        return cmd, tool.env
