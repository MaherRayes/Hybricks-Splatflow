from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from .errors import ValidationError


InputType = Literal["images", "video"]
SharpFramesSelection = Literal["best-n", "batched", "outlier-removal"]
SharpFramesFormat = Literal["jpg", "png"]
ColmapMatcher = Literal["exhaustive", "sequential"]
LichtfeldStrategy = Literal["adc", "mcmc"]
ResizeFactor = Literal["auto", "1", "2", "4", "8"]


def _as_path(p: str | Path) -> Path:
    return p if isinstance(p, Path) else Path(p)


@dataclass
class InputConfig:
    type: InputType
    path: str

    def validate(self) -> None:
        p = _as_path(self.path)
        if self.type == "images":
            if not p.exists() or not p.is_dir():
                raise ValidationError(f"Input images path must be a directory: {p}")
        else:
            if not p.exists():
                raise ValidationError(f"Input video path does not exist: {p}")
            if not (p.is_file() or p.is_dir()):
                raise ValidationError(f"Input video path must be a file or directory: {p}")


@dataclass
class FrameSamplingConfig:
    enabled: bool = True
    selection_method: SharpFramesSelection = "best-n"
    fps: int = 10
    format: SharpFramesFormat = "jpg"
    width: int = 0
    force_overwrite: bool = False

    # best-n
    num_frames: int = 300
    min_buffer: int = 3

    # batched
    batch_size: int = 5
    batch_buffer: int = 2

    # outlier removal
    outlier_window_size: int = 15
    outlier_sensitivity: int = 50

    def validate(self) -> None:
        if not self.enabled:
            return
        if self.fps <= 0:
            raise ValidationError("Frame sampling FPS must be > 0")
        if self.width < 0:
            raise ValidationError("Frame sampling width must be >= 0")
        if self.selection_method == "best-n":
            if self.num_frames <= 0:
                raise ValidationError("num_frames must be > 0 for best-n")
            if self.min_buffer < 0:
                raise ValidationError("min_buffer must be >= 0 for best-n")
        elif self.selection_method == "batched":
            if self.batch_size <= 0:
                raise ValidationError("batch_size must be > 0 for batched")
            if self.batch_buffer < 0:
                raise ValidationError("batch_buffer must be >= 0 for batched")
        elif self.selection_method == "outlier-removal":
            if self.outlier_window_size <= 0:
                raise ValidationError("outlier_window_size must be > 0 for outlier-removal")
            if not (0 <= self.outlier_sensitivity <= 100):
                raise ValidationError("outlier_sensitivity must be in [0, 100]")


@dataclass
class ColmapConfig:
    matcher: ColmapMatcher = "exhaustive"
    use_gpu: bool = True
    camera_model: str = "PINHOLE"
    single_camera: bool = True
    max_image_size: int = 3200

    # advanced
    sift_max_num_features: int = 8192
    num_threads: int = -1
    sequential_overlap: int = 10  # only used for sequential matcher

    def validate(self) -> None:
        if self.max_image_size <= 0:
            raise ValidationError("COLMAP max_image_size must be > 0")
        if self.sift_max_num_features <= 0:
            raise ValidationError("COLMAP sift_max_num_features must be > 0")
        if self.matcher == "sequential" and self.sequential_overlap <= 0:
            raise ValidationError("COLMAP sequential_overlap must be > 0")


@dataclass
class LichtfeldConfig:
    iterations: int = 30000
    resize_factor: ResizeFactor = "auto"
    strategy: LichtfeldStrategy = "adc"
    max_cap: int = 1_000_000
    headless: bool = True

    # advanced
    gut: bool = False
    ppisp_controller: bool = False
    mip_filter: bool = False
    eval: bool = False
    save_eval_images: bool = False
    test_every: int = 8

    def validate(self) -> None:
        if self.iterations <= 0:
            raise ValidationError("LichtFeld iterations must be > 0")
        if self.max_cap <= 0:
            raise ValidationError("LichtFeld max_cap must be > 0")
        if self.test_every <= 0:
            raise ValidationError("LichtFeld test_every must be > 0")


@dataclass
class OutputConfig:
    output_dir: str
    keep_intermediates: bool = True

    def validate(self) -> None:
        p = _as_path(self.output_dir)
        if p.exists() and not p.is_dir():
            raise ValidationError(f"Output directory path exists and is not a directory: {p}")


@dataclass
class PipelineConfig:
    input: InputConfig
    output: OutputConfig
    frame_sampling: FrameSamplingConfig = field(default_factory=FrameSamplingConfig)
    colmap: ColmapConfig = field(default_factory=ColmapConfig)
    lichtfeld: LichtfeldConfig = field(default_factory=LichtfeldConfig)

    def validate(self) -> None:
        self.input.validate()
        self.output.validate()
        self.frame_sampling.validate()
        self.colmap.validate()
        self.lichtfeld.validate()

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "PipelineConfig":
        return PipelineConfig(
            input=InputConfig(**data["input"]),
            output=OutputConfig(**data["output"]),
            frame_sampling=FrameSamplingConfig(**(data.get("frame_sampling") or {})),
            colmap=ColmapConfig(**(data.get("colmap") or {})),
            lichtfeld=LichtfeldConfig(**(data.get("lichtfeld") or {})),
        )

    @staticmethod
    def defaults(input_type: InputType, input_path: str, output_dir: str) -> "PipelineConfig":
        cfg = PipelineConfig(
            input=InputConfig(type=input_type, path=input_path),
            output=OutputConfig(output_dir=output_dir),
        )
        if input_type == "video":
            cfg.frame_sampling.enabled = True
            cfg.colmap.matcher = "sequential"
        else:
            cfg.frame_sampling.enabled = False
            cfg.colmap.matcher = "exhaustive"
        return cfg
