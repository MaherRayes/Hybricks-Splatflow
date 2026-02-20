from __future__ import annotations

from pathlib import Path

from splatflow.backend.paths import AppPaths
from splatflow.backend.settings import Settings, ToolPaths
from splatflow.backend.toolchain import Toolchain
from splatflow.backend.schema import FrameSamplingConfig, ColmapConfig, LichtfeldConfig
from splatflow.backend.tools.sharp_frames import SharpFramesArgs
from splatflow.backend.tools.colmap import ColmapProject, feature_extractor_cmd, matcher_cmd, undistort_cmd
from splatflow.backend.tools.lichtfeld import LichtfeldTrainArgs


class FakeRunner:
    def __init__(self, which_map: dict[str, str], help_map: dict[str, str] | None = None) -> None:
        self.which_map = which_map
        self.help_map = help_map or {}

    def which(self, exe: str) -> str | None:
        return self.which_map.get(exe)

    def run(self, *args, **kwargs):  # pragma: no cover
        raise RuntimeError("FakeRunner.run should not be called in these tests")

    def run_capture(self, command, *, options=None):
        cmd = list(map(str, command))
        if "-h" not in cmd:
            raise RuntimeError("FakeRunner.run_capture only supports help calls")
        try:
            idx = cmd.index("-h")
        except ValueError:
            return ""
        # we invoke help as: <prefix> <command> -h
        if idx < 1:
            return ""
        subcmd = cmd[idx - 1]
        return self.help_map.get(subcmd, "")


def test_sharp_frames_builds_expected_command_video(tmp_path: Path) -> None:
    paths = AppPaths(data_dir_override=str(tmp_path / "data"), config_dir_override=str(tmp_path / "cfg")).ensure()
    settings = Settings(tool_paths=ToolPaths(), auto_install_tools=False)
    runner = FakeRunner({"sharp-frames": "/usr/bin/sharp-frames"})
    tc = Toolchain(paths=paths, settings=settings, runner=runner)  # type: ignore[arg-type]

    cfg = FrameSamplingConfig(enabled=True, selection_method="best-n", fps=12, num_frames=123)
    args = SharpFramesArgs(input_path=Path("in.mp4"), output_dir=Path("out"), input_type="video", config=cfg)
    cmd, _ = args.to_command(tc)
    assert cmd[0] == "/usr/bin/sharp-frames"
    assert "--fps" in cmd
    assert "12" in cmd
    assert "--num-frames" in cmd
    assert "123" in cmd


def test_colmap_feature_extractor_resolves_hybrid_flag_names(tmp_path: Path) -> None:
    paths = AppPaths(data_dir_override=str(tmp_path / "data"), config_dir_override=str(tmp_path / "cfg")).ensure()
    settings = Settings(tool_paths=ToolPaths(), auto_install_tools=False)
    help_text = """
        --ImageReader.camera_model arg (=SIMPLE_RADIAL)
        --ImageReader.single_camera arg (=0)
        --FeatureExtraction.use_gpu arg (=1)
        --SiftExtraction.max_image_size arg (=3200)
        --SiftExtraction.num_threads arg (=-1)
        --SiftExtraction.max_num_features arg (=8192)
    """
    runner = FakeRunner({"colmap": "/usr/bin/colmap"}, {"feature_extractor": help_text})
    tc = Toolchain(paths=paths, settings=settings, runner=runner)  # type: ignore[arg-type]

    proj = ColmapProject(
        images_dir=Path("images"),
        database_path=Path("database.db"),
        sparse_dir=Path("sparse"),
        undistorted_dir=Path("undistorted"),
    )
    cfg = ColmapConfig(use_gpu=False, single_camera=True, camera_model="OPENCV", max_image_size=4000)
    cmd, _ = feature_extractor_cmd(tc, proj, cfg)
    assert cmd[0] == "/usr/bin/colmap"
    assert "feature_extractor" in cmd
    assert "--ImageReader.camera_model" in cmd
    assert "OPENCV" in cmd
    assert "--FeatureExtraction.use_gpu" in cmd
    assert "0" in cmd
    assert "--SiftExtraction.max_image_size" in cmd
    assert "4000" in cmd


def test_colmap_feature_extractor_uses_featureextraction_when_available(tmp_path: Path) -> None:
    paths = AppPaths(data_dir_override=str(tmp_path / "data"), config_dir_override=str(tmp_path / "cfg")).ensure()
    settings = Settings(tool_paths=ToolPaths(), auto_install_tools=False)
    help_text = """
        --FeatureExtraction.max_image_size arg (=3200)
        --FeatureExtraction.num_threads arg (=-1)
        --FeatureExtraction.use_gpu arg (=1)
        --SiftExtraction.max_num_features arg (=8192)
    """
    runner = FakeRunner({"colmap": "/usr/bin/colmap"}, {"feature_extractor": help_text})
    tc = Toolchain(paths=paths, settings=settings, runner=runner)  # type: ignore[arg-type]

    proj = ColmapProject(
        images_dir=Path("images"),
        database_path=Path("database.db"),
        sparse_dir=Path("sparse"),
        undistorted_dir=Path("undistorted"),
    )
    cfg = ColmapConfig(use_gpu=True, max_image_size=1234, num_threads=7)
    cmd, _ = feature_extractor_cmd(tc, proj, cfg)
    assert "--FeatureExtraction.use_gpu" in cmd
    assert "--FeatureExtraction.max_image_size" in cmd
    assert "1234" in cmd
    assert "--FeatureExtraction.num_threads" in cmd
    assert "7" in cmd


def test_colmap_feature_extractor_omits_gpu_flag_if_not_supported(tmp_path: Path) -> None:
    paths = AppPaths(data_dir_override=str(tmp_path / "data"), config_dir_override=str(tmp_path / "cfg")).ensure()
    settings = Settings(tool_paths=ToolPaths(), auto_install_tools=False)
    help_text = """
        --FeatureExtraction.max_image_size arg (=3200)
        --SiftExtraction.max_num_features arg (=8192)
    """
    runner = FakeRunner({"colmap": "/usr/bin/colmap"}, {"feature_extractor": help_text})
    tc = Toolchain(paths=paths, settings=settings, runner=runner)  # type: ignore[arg-type]

    proj = ColmapProject(
        images_dir=Path("images"),
        database_path=Path("database.db"),
        sparse_dir=Path("sparse"),
        undistorted_dir=Path("undistorted"),
    )
    cfg = ColmapConfig(use_gpu=True)
    cmd, _ = feature_extractor_cmd(tc, proj, cfg)
    assert not any("use_gpu" in x for x in cmd)


def test_lichtfeld_train_has_required_args(tmp_path: Path) -> None:
    paths = AppPaths(data_dir_override=str(tmp_path / "data"), config_dir_override=str(tmp_path / "cfg")).ensure()
    lf = tmp_path / "LichtFeld-Studio"
    lf.write_text("x")
    settings = Settings(tool_paths=ToolPaths(lichtfeld=str(lf)), auto_install_tools=False)
    runner = FakeRunner({})
    tc = Toolchain(paths=paths, settings=settings, runner=runner)  # type: ignore[arg-type]

    cfg = LichtfeldConfig(iterations=111, max_cap=222, strategy="mcmc", resize_factor="2")
    args = LichtfeldTrainArgs(data_path=Path("dataset"), output_path=Path("out"), config=cfg)
    cmd, _ = args.to_command(tc)
    assert cmd[0] == str(lf)
    assert "--data-path" in cmd and "dataset" in cmd
    assert "--output-path" in cmd and "out" in cmd
    assert "--iter" in cmd and "111" in cmd
    assert "--max-cap" in cmd and "222" in cmd


def test_lichtfeld_train_includes_optional_flags_when_enabled(tmp_path: Path) -> None:
    paths = AppPaths(data_dir_override=str(tmp_path / "data"), config_dir_override=str(tmp_path / "cfg")).ensure()
    lf = tmp_path / "LichtFeld-Studio"
    lf.write_text("x")
    settings = Settings(tool_paths=ToolPaths(lichtfeld=str(lf)), auto_install_tools=False)
    runner = FakeRunner({})
    tc = Toolchain(paths=paths, settings=settings, runner=runner)  # type: ignore[arg-type]

    cfg = LichtfeldConfig(
        iterations=111,
        max_cap=222,
        strategy="mcmc",
        resize_factor="2",
        gut=True,
        ppisp_controller=True,
        mip_filter=True,
    )
    args = LichtfeldTrainArgs(data_path=Path("dataset"), output_path=Path("out"), config=cfg)
    cmd, _ = args.to_command(tc)
    assert "--gut" in cmd
    assert "--ppisp-controller" in cmd
    assert "--enable-mip" in cmd
