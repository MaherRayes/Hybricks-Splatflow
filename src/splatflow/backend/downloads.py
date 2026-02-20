from __future__ import annotations

import io
import os
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import requests


@dataclass(frozen=True)
class DownloadResult:
    url: str
    path: Path
    bytes: int


def download_file(url: str, dest: Path, *, timeout_s: int = 60) -> DownloadResult:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=timeout_s) as r:
        r.raise_for_status()
        total = 0
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)
                    total += len(chunk)
    return DownloadResult(url=url, path=dest, bytes=total)


def extract_tar_bz2_member(archive: Path, member: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, mode="r:bz2") as tf:
        m = tf.getmember(member)
        with tf.extractfile(m) as src:
            assert src is not None
            with open(dest, "wb") as out:
                out.write(src.read())
    _make_executable(dest)


def extract_zip(archive: Path, dest_dir: Path) -> None:
    dest_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, "r") as z:
        z.extractall(dest_dir)


def find_files(root: Path, names: Iterable[str]) -> list[Path]:
    wanted = {n.lower() for n in names}
    matches: list[Path] = []
    for p in root.rglob("*"):
        if p.is_file() and p.name.lower() in wanted:
            matches.append(p)
    return matches


def _make_executable(path: Path) -> None:
    if os.name != "nt":
        mode = path.stat().st_mode
        path.chmod(mode | 0o111)
