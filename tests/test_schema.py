from __future__ import annotations

from pathlib import Path

import pytest

from splatflow.backend.schema import PipelineConfig
from splatflow.backend.errors import ValidationError


def test_defaults_video_enables_sampling_and_sequential(tmp_path: Path) -> None:
    cfg = PipelineConfig.defaults("video", str(tmp_path / "input.mp4"), str(tmp_path / "out"))
    assert cfg.frame_sampling.enabled is True
    assert cfg.colmap.matcher == "sequential"


def test_validation_rejects_missing_images_dir(tmp_path: Path) -> None:
    cfg = PipelineConfig.defaults("images", str(tmp_path / "missing"), str(tmp_path / "out"))
    with pytest.raises(ValidationError):
        cfg.validate()


def test_validation_rejects_bad_sampling_params(tmp_path: Path) -> None:
    img_dir = tmp_path / "imgs"
    img_dir.mkdir()
    (img_dir / "a.jpg").write_bytes(b"fake")

    cfg = PipelineConfig.defaults("images", str(img_dir), str(tmp_path / "out"))
    cfg.frame_sampling.enabled = True
    cfg.frame_sampling.selection_method = "best-n"
    cfg.frame_sampling.num_frames = 0
    with pytest.raises(ValidationError):
        cfg.validate()
