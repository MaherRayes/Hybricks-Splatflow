from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..schema import ColmapConfig
from ..toolchain import Toolchain


@dataclass(frozen=True)
class ColmapProject:
    images_dir: Path
    database_path: Path
    sparse_dir: Path
    undistorted_dir: Path

    @property
    def sparse_model_dir(self) -> Path:
        return self.sparse_dir / "0"


def _pick_option(options: set[str] | frozenset[str], candidates: list[str]) -> str | None:
    for c in candidates:
        if c in options:
            return c
    return None


def feature_extractor_cmd(toolchain: Toolchain, proj: ColmapProject, cfg: ColmapConfig) -> tuple[list[str], dict[str, str]]:
    tool = toolchain.colmap_exec()
    opts = toolchain.colmap_options("feature_extractor")
    cmd = [
        *tool.prefix,
        "feature_extractor",
        "--database_path",
        str(proj.database_path),
        "--image_path",
        str(proj.images_dir),
        "--ImageReader.camera_model",
        cfg.camera_model,
        "--ImageReader.single_camera",
        "1" if cfg.single_camera else "0",
    ]

    gpu_opt = _pick_option(opts, ["FeatureExtraction.use_gpu", "SiftExtraction.use_gpu"])
    if gpu_opt:
        cmd += [f"--{gpu_opt}", "1" if cfg.use_gpu else "0"]

    max_size_opt = _pick_option(opts, ["FeatureExtraction.max_image_size", "SiftExtraction.max_image_size"])
    if max_size_opt:
        cmd += [f"--{max_size_opt}", str(cfg.max_image_size)]

    threads_opt = _pick_option(opts, ["FeatureExtraction.num_threads", "SiftExtraction.num_threads"])
    if threads_opt:
        cmd += [f"--{threads_opt}", str(cfg.num_threads)]

    if "SiftExtraction.max_num_features" in opts:
        cmd += ["--SiftExtraction.max_num_features", str(cfg.sift_max_num_features)]

    return cmd, tool.env


def matcher_cmd(toolchain: Toolchain, proj: ColmapProject, cfg: ColmapConfig) -> tuple[list[str], dict[str, str]]:
    tool = toolchain.colmap_exec()
    if cfg.matcher == "sequential":
        opts = toolchain.colmap_options("sequential_matcher")
        gpu_opt = _pick_option(opts, ["FeatureMatching.use_gpu", "SiftMatching.use_gpu"])
        overlap_opt = "SequentialMatching.overlap" if "SequentialMatching.overlap" in opts else None
        cmd = [
            *tool.prefix,
            "sequential_matcher",
            "--database_path",
            str(proj.database_path),
        ]
        if gpu_opt:
            cmd += [f"--{gpu_opt}", "1" if cfg.use_gpu else "0"]
        if overlap_opt:
            cmd += [f"--{overlap_opt}", str(cfg.sequential_overlap)]
    else:
        opts = toolchain.colmap_options("exhaustive_matcher")
        gpu_opt = _pick_option(opts, ["FeatureMatching.use_gpu", "SiftMatching.use_gpu"])
        cmd = [
            *tool.prefix,
            "exhaustive_matcher",
            "--database_path",
            str(proj.database_path),
        ]
        if gpu_opt:
            cmd += [f"--{gpu_opt}", "1" if cfg.use_gpu else "0"]
    return cmd, tool.env


def mapper_cmd(toolchain: Toolchain, proj: ColmapProject) -> tuple[list[str], dict[str, str]]:
    tool = toolchain.colmap_exec()
    cmd = [
        *tool.prefix,
        "mapper",
        "--database_path",
        str(proj.database_path),
        "--image_path",
        str(proj.images_dir),
        "--output_path",
        str(proj.sparse_dir),
    ]
    return cmd, tool.env


def undistort_cmd(toolchain: Toolchain, proj: ColmapProject, cfg: ColmapConfig) -> tuple[list[str], dict[str, str]]:
    tool = toolchain.colmap_exec()
    cmd = [
        *tool.prefix,
        "image_undistorter",
        "--image_path",
        str(proj.images_dir),
        "--input_path",
        str(proj.sparse_model_dir),
        "--output_path",
        str(proj.undistorted_dir),
        "--output_type",
        "COLMAP",
        "--max_image_size",
        str(cfg.max_image_size),
    ]
    return cmd, tool.env
