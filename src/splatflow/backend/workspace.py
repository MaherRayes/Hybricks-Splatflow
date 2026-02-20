from __future__ import annotations

import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}


@dataclass(frozen=True)
class Workspace:
    root: Path

    @property
    def images_dir(self) -> Path:
        return self.root / "images"

    @property
    def colmap_dir(self) -> Path:
        return self.root / "colmap"

    @property
    def colmap_db(self) -> Path:
        return self.colmap_dir / "database.db"

    @property
    def colmap_sparse(self) -> Path:
        return self.colmap_dir / "sparse"

    @property
    def colmap_undistorted(self) -> Path:
        return self.colmap_dir / "undistorted"

    @property
    def logs_dir(self) -> Path:
        return self.root / "logs"

    def ensure(self) -> "Workspace":
        self.root.mkdir(parents=True, exist_ok=True)
        self.images_dir.mkdir(parents=True, exist_ok=True)
        self.colmap_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        return self

    @staticmethod
    def create(jobs_dir: Path, name: str | None = None) -> "Workspace":
        jobs_dir.mkdir(parents=True, exist_ok=True)
        safe = (name or "job").strip().replace(" ", "_")
        ts = time.strftime("%Y%m%d-%H%M%S")
        root = jobs_dir / f"{safe}-{ts}"
        return Workspace(root=root).ensure()


def iter_images(directory: Path) -> Iterable[Path]:
    for p in sorted(directory.iterdir()):
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS:
            yield p


def copy_images(src_dir: Path, dst_dir: Path) -> int:
    dst_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for img in iter_images(src_dir):
        shutil.copy2(img, dst_dir / img.name)
        count += 1
    return count
