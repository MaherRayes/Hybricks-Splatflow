from __future__ import annotations

from pathlib import Path

from splatflow.backend.paths import AppPaths
from splatflow.backend.pipeline import SplatPipeline
from splatflow.backend.schema import PipelineConfig


class RecordingRunner:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    def which(self, exe: str) -> str | None:
        # pretend tools are installed
        mapping = {
            "colmap": "/usr/bin/colmap",
            "sharp-frames": "/usr/bin/sharp-frames",
            "LichtFeld-Studio": "/usr/bin/LichtFeld-Studio",
            "LichtFeld-Studio.exe": "/usr/bin/LichtFeld-Studio.exe",
        }
        return mapping.get(exe)

    def run(self, command, *, options=None, on_line=None):
        cmd = list(map(str, command))
        self.commands.append(cmd)

        # simulate colmap mapper output
        if "mapper" in cmd:
            out_idx = cmd.index("--output_path") + 1
            sparse_dir = Path(cmd[out_idx])
            (sparse_dir / "0").mkdir(parents=True, exist_ok=True)

        if on_line:
            on_line("ok")

    def run_capture(self, command, *, options=None):
        # allow toolchain.colmap_options() to run in tests
        return ""


def test_pipeline_smoke_images(tmp_path: Path) -> None:
    img_dir = tmp_path / "imgs"
    img_dir.mkdir()
    for i in range(3):
        (img_dir / f"{i}.jpg").write_bytes(b"fake")

    out_dir = tmp_path / "out"
    cfg = PipelineConfig.defaults("images", str(img_dir), str(out_dir))
    cfg.frame_sampling.enabled = False

    paths = AppPaths(data_dir_override=str(tmp_path / "data"), config_dir_override=str(tmp_path / "cfg")).ensure()
    runner = RecordingRunner()

    pipe = SplatPipeline(paths=paths, runner=runner)  # type: ignore[arg-type]
    res = pipe.run(cfg)

    assert res.output_dir.exists()

    dataset_images = res.output_dir / "dataset" / "images"
    dataset_colmap = res.output_dir / "dataset" / "colmap"
    assert dataset_images.exists()
    assert dataset_colmap.exists()
    assert (dataset_images / "0.jpg").exists()
    assert (dataset_colmap / "sparse" / "0").exists()
    # ensure colmap commands were planned
    joined = [" ".join(c) for c in runner.commands]
    assert any("feature_extractor" in c for c in joined)
    assert any("exhaustive_matcher" in c for c in joined)
    assert any("mapper" in c for c in joined)
    assert any("image_undistorter" in c for c in joined)
