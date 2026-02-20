from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..schema import FrameSamplingConfig, InputType
from ..toolchain import Toolchain


@dataclass(frozen=True)
class SharpFramesArgs:
    input_path: Path
    output_dir: Path
    input_type: InputType
    config: FrameSamplingConfig

    def to_command(self, toolchain: Toolchain) -> tuple[list[str], dict[str, str]]:
        tool = toolchain.sharp_frames_exe()
        cfg = self.config

        cmd: list[str] = [*tool.prefix, str(self.input_path), str(self.output_dir)]
        cmd += ["--selection-method", cfg.selection_method]

        if self.input_type == "video":
            cmd += ["--fps", str(cfg.fps)]

        cmd += ["--format", cfg.format]
        if cfg.width:
            cmd += ["--width", str(cfg.width)]
        if cfg.force_overwrite:
            cmd += ["--force-overwrite"]

        if cfg.selection_method == "best-n":
            cmd += ["--num-frames", str(cfg.num_frames), "--min-buffer", str(cfg.min_buffer)]
        elif cfg.selection_method == "batched":
            cmd += ["--batch-size", str(cfg.batch_size), "--batch-buffer", str(cfg.batch_buffer)]
        elif cfg.selection_method == "outlier-removal":
            cmd += [
                "--outlier-window-size",
                str(cfg.outlier_window_size),
                "--outlier-sensitivity",
                str(cfg.outlier_sensitivity),
            ]

        return cmd, tool.env
