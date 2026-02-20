from __future__ import annotations

import shutil
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable

from .errors import ToolNotFoundError, ValidationError
from .paths import AppPaths
from .process import CommandRunner, RunOptions
from .schema import PipelineConfig
from .settings import SettingsStore
from .toolchain import Toolchain
from .workspace import Workspace, copy_images, iter_images
from .tools.sharp_frames import SharpFramesArgs
from .tools.colmap import (
    ColmapProject,
    feature_extractor_cmd,
    matcher_cmd,
    mapper_cmd,
    undistort_cmd,
)
from .tools.lichtfeld import LichtfeldTrainArgs


LogCallback = Callable[[str], None]
StageCallback = Callable[[str], None]

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".m4v", ".webm"}


@dataclass(frozen=True)
class PipelineResult:
    workspace_dir: Path
    output_dir: Path


class SplatPipeline:
    def __init__(self, *, paths: AppPaths | None = None, runner: CommandRunner | None = None) -> None:
        self.paths = (paths or AppPaths()).ensure()
        self.runner = runner or CommandRunner()
        self.settings_store = SettingsStore(self.paths)

    def run(
        self,
        config: PipelineConfig,
        *,
        on_log: LogCallback | None = None,
        on_stage: StageCallback | None = None,
    ) -> PipelineResult:
        config.validate()

        workspace = Workspace.create(self.paths.jobs_dir, name="splatflow")
        log_path = workspace.logs_dir / "pipeline.log"

        def emit(line: str) -> None:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
            if on_log:
                on_log(line)

        def stage(name: str) -> None:
            emit(f"\n=== {name} ===")
            if on_stage:
                on_stage(name)

        settings = self.settings_store.load()
        toolchain = Toolchain(paths=self.paths, settings=settings, runner=self.runner)

        output_root = Path(config.output.output_dir)
        output_root.mkdir(parents=True, exist_ok=True)
        output_dir = output_root / workspace.root.name
        output_dir.mkdir(parents=True, exist_ok=True)

        # 1) ingest
        stage("Ingest")
        self._ingest(config, workspace, toolchain, emit)

        # 2) colmap
        stage("COLMAP")
        self._run_colmap(config, workspace, toolchain, emit)

        # 2.5) export dataset artifacts
        stage("Export")
        self._export_artifacts(workspace, output_dir, emit)

        # 3) lichtfeld
        stage("LichtFeld Studio")
        self._run_lichtfeld(config, workspace, toolchain, output_dir, emit)

        emit("\nDone.")
        if not config.output.keep_intermediates:
            shutil.rmtree(workspace.root, ignore_errors=True)

        return PipelineResult(workspace_dir=workspace.root, output_dir=output_dir)


    def _list_videos_in_dir(self, directory: Path) -> list[Path]:
        videos: list[Path] = []
        for p in sorted(directory.iterdir()):
            if p.is_file() and p.suffix.lower() in VIDEO_EXTS:
                videos.append(p)
        return videos

    def _ingest(
        self,
        config: PipelineConfig,
        workspace: Workspace,
        toolchain: Toolchain,
        emit: LogCallback,
    ) -> None:
        src = Path(config.input.path)

        if config.input.type == "video":
            if not config.frame_sampling.enabled:
                raise ValidationError("Video input requires frame_sampling.enabled = True")
            videos = [src] if src.is_file() else self._list_videos_in_dir(src)
            if not videos:
                raise ValidationError(f"No video files found in: {src}")

            tmp_root = workspace.root / "tmp_frames"
            if tmp_root.exists():
                shutil.rmtree(tmp_root, ignore_errors=True)
            tmp_root.mkdir(parents=True, exist_ok=True)

            n = len(videos)
            emit(f"Sampling frames from {n} video(s)...")

            for i, vid in enumerate(videos):
                out_dir = tmp_root / f"v{i:03d}"
                out_dir.mkdir(parents=True, exist_ok=True)

                fs_cfg = config.frame_sampling
                if fs_cfg.selection_method == "best-n" and n > 1:
                    per = max(1, fs_cfg.num_frames // n)
                    rem = fs_cfg.num_frames % n
                    fs_cfg = replace(fs_cfg, num_frames=per + (1 if i < rem else 0))

                args = SharpFramesArgs(
                    input_path=vid,
                    output_dir=out_dir,
                    input_type=config.input.type,
                    config=fs_cfg,
                )
                cmd, env = args.to_command(toolchain)
                emit("Running: " + " ".join(map(str, cmd)))
                self.runner.run(cmd, options=RunOptions(env=env), on_line=emit)

                prefix = vid.stem
                for j, img in enumerate(iter_images(out_dir)):
                    name = f"{prefix}_{i:03d}_{j:06d}{img.suffix.lower()}"
                    shutil.copy2(img, workspace.images_dir / name)
            self._ensure_images(workspace, emit)
            return

        # images directory
        if config.frame_sampling.enabled:
            args = SharpFramesArgs(
                input_path=src,
                output_dir=workspace.images_dir,
                input_type=config.input.type,
                config=config.frame_sampling,
            )
            cmd, env = args.to_command(toolchain)
            emit("Running: " + " ".join(map(str, cmd)))
            self.runner.run(cmd, options=RunOptions(env=env), on_line=emit)
            self._ensure_images(workspace, emit)
        else:
            n = copy_images(src, workspace.images_dir)
            emit(f"Copied {n} images to workspace.")
            self._ensure_images(workspace, emit)


    def _ensure_images(self, workspace: Workspace, emit: LogCallback) -> None:
        count = sum(1 for _ in iter_images(workspace.images_dir))
        if count == 0:
            raise ValidationError(
                "No images found after ingest. If you used iPhone HEIC photos, convert them to JPG/PNG first."
            )
        emit(f"Using {count} images.")
    def _run_colmap(
        self,
        config: PipelineConfig,
        workspace: Workspace,
        toolchain: Toolchain,
        emit: LogCallback,
    ) -> None:
        workspace.colmap_sparse.mkdir(parents=True, exist_ok=True)
        workspace.colmap_undistorted.mkdir(parents=True, exist_ok=True)

        proj = ColmapProject(
            images_dir=workspace.images_dir,
            database_path=workspace.colmap_db,
            sparse_dir=workspace.colmap_sparse,
            undistorted_dir=workspace.colmap_undistorted,
        )

        # sanity: tool presence early
        try:
            _ = toolchain.colmap_exec()
        except ToolNotFoundError as e:
            raise

        cmds = [
            feature_extractor_cmd(toolchain, proj, config.colmap),
            matcher_cmd(toolchain, proj, config.colmap),
            mapper_cmd(toolchain, proj),
            undistort_cmd(toolchain, proj, config.colmap),
        ]

        for cmd, env in cmds:
            emit("Running: " + " ".join(map(str, cmd)))
            self.runner.run(cmd, options=RunOptions(env=env), on_line=emit)

        if not proj.sparse_model_dir.exists():
            raise ValidationError(
                "COLMAP did not produce a sparse model (expected sparse/0). "
                "Try increasing image count, using exhaustive matcher, or improving overlap."
            )

    def _export_artifacts(self, workspace: Workspace, output_dir: Path, emit: LogCallback) -> None:
        dataset_dir = output_dir / "dataset"
        images_out = dataset_dir / "images"
        colmap_out = dataset_dir / "colmap"

        if dataset_dir.exists():
            shutil.rmtree(dataset_dir, ignore_errors=True)
        dataset_dir.mkdir(parents=True, exist_ok=True)

        shutil.copytree(workspace.images_dir, images_out, dirs_exist_ok=True)
        shutil.copytree(workspace.colmap_dir, colmap_out, dirs_exist_ok=True)
        emit(f"Exported images to: {images_out}")
        emit(f"Exported COLMAP data to: {colmap_out}")

    def _run_lichtfeld(
        self,
        config: PipelineConfig,
        workspace: Workspace,
        toolchain: Toolchain,
        output_dir: Path,
        emit: LogCallback,
    ) -> None:
        data_path = workspace.colmap_undistorted
        args = LichtfeldTrainArgs(data_path=data_path, output_path=output_dir, config=config.lichtfeld)
        cmd, env = args.to_command(toolchain)
        emit("Running: " + " ".join(map(str, cmd)))
        self.runner.run(cmd, options=RunOptions(env=env), on_line=emit)