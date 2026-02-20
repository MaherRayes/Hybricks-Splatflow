from __future__ import annotations

import os
import platform
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

import requests

from .downloads import download_file, extract_tar_bz2_member, extract_zip, find_files
from .errors import ToolNotFoundError
from .paths import AppPaths
from .process import CommandRunner, RunOptions
from .settings import Settings


@dataclass(frozen=True)
class ToolExec:
    exe: Path
    prefix: list[str]
    env: dict[str, str]


_COLMAP_OPT_RE = re.compile(r"^\s*--([A-Za-z0-9_.-]+)\b")


class Toolchain:
    def __init__(self, *, paths: AppPaths, settings: Settings, runner: CommandRunner) -> None:
        self.paths = paths.ensure()
        self.settings = settings
        self.runner = runner

        self._colmap_options_cache: dict[str, frozenset[str]] = {}

        (self.paths.tools_dir / "colmap").mkdir(parents=True, exist_ok=True)
        (self.paths.tools_dir / "envs").mkdir(parents=True, exist_ok=True)
        (self.paths.tools_dir / "micromamba").mkdir(parents=True, exist_ok=True)
        (self.paths.tools_dir / "lichtfeld").mkdir(parents=True, exist_ok=True)

    # -------------------------
    # Helpers
    # -------------------------
    def _platform_tag(self) -> str:
        sysname = platform.system().lower()
        machine = platform.machine().lower()

        if sysname.startswith("windows"):
            return "win-64"
        if sysname == "darwin":
            return "osx-arm64" if machine in {"arm64", "aarch64"} else "osx-64"
        if sysname == "linux":
            return "linux-aarch64" if machine in {"arm64", "aarch64"} else "linux-64"

        raise ToolNotFoundError(f"Unsupported platform for auto-install: {platform.system()} {platform.machine()}")

    def _micromamba_member(self) -> str:
        # See micromamba docs: Windows tar contains Library/bin/micromamba.exe
        return "Library/bin/micromamba.exe" if os.name == "nt" else "bin/micromamba"

    def _env_bin_dirs(self, env_prefix: Path) -> list[Path]:
        if os.name == "nt":
            return [
                env_prefix / "Library" / "bin",
                env_prefix / "Scripts",
            ]
        return [env_prefix / "bin"]

    def _with_path(self, base_env: Mapping[str, str] | None, extra_dirs: Iterable[Path]) -> dict[str, str]:
        env = dict(base_env or {})
        existing = os.environ.get("PATH", "")
        extras = [str(d) for d in extra_dirs if d.exists()]
        env["PATH"] = os.pathsep.join(extras + [existing])
        return env

    # -------------------------
    # Micromamba + conda envs
    # -------------------------
    def ensure_micromamba(self) -> Path:
        mm_dir = self.paths.tools_dir / "micromamba"
        exe = mm_dir / ("micromamba.exe" if os.name == "nt" else "micromamba")
        if exe.exists():
            return exe

        if not self.settings.auto_install_tools:
            raise ToolNotFoundError(
                "micromamba not found. Enable auto_install_tools or install micromamba and configure its path."
            )

        tag = self._platform_tag()
        url = f"https://micro.mamba.pm/api/micromamba/{tag}/latest"
        archive = mm_dir / "micromamba.tar.bz2"
        download_file(url, archive)

        member = self._micromamba_member()
        extract_tar_bz2_member(archive, member, exe)
        return exe

    def ensure_env(self, name: str, packages: list[str]) -> Path:
        env_prefix = self.paths.tools_dir / "envs" / name
        marker = env_prefix / (".created" if os.name == "nt" else ".created")
        if marker.exists():
            return env_prefix

        if not self.settings.auto_install_tools:
            raise ToolNotFoundError(
                f"Conda env '{name}' not found. Enable auto_install_tools or install required tools manually."
            )

        micromamba = self.ensure_micromamba()
        root_prefix = self.paths.tools_dir / "mamba_root"
        root_prefix.mkdir(parents=True, exist_ok=True)

        env = {"MAMBA_ROOT_PREFIX": str(root_prefix)}
        cmd = [str(micromamba), "create", "-y", "-p", str(env_prefix), "-c", "conda-forge", *packages]
        self.runner.run(cmd, options=RunOptions(env=env))

        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("ok", encoding="utf-8")
        return env_prefix

    # -------------------------
    # COLMAP
    # -------------------------
    def _resolve_latest_colmap_release(self) -> str:
        headers = {"User-Agent": "SplatFlow"}
        r = requests.get(
            "https://github.com/colmap/colmap/releases/latest",
            allow_redirects=True,
            headers=headers,
            timeout=30,
        )
        r.raise_for_status()
        # typically ends in .../releases/tag/<version>
        m = re.search(r"/tag/([^/]+)$", r.url)
        tag = m.group(1) if m else r.url.rstrip("/").split("/")[-1]
        return tag[1:] if tag.lower().startswith("v") else tag

    def ensure_colmap_official(self) -> Path:
        if os.name != "nt":
            raise ToolNotFoundError(
                "Official COLMAP auto-download is currently supported on Windows only. "
                "Please install COLMAP manually or switch to the conda source."
            )

        if not self.settings.auto_install_tools:
            raise ToolNotFoundError(
                "COLMAP not found. Enable auto_install_tools or configure the COLMAP path in settings."
            )

        colmap_root = self.paths.tools_dir / "colmap"
        version = (self.settings.colmap.version or "latest").strip()
        if version.lower() == "latest":
            version = self._resolve_latest_colmap_release()

        build = (self.settings.colmap.build or "cuda").strip().lower()
        if build not in {"cuda", "nocuda"}:
            build = "cuda"

        asset = f"colmap-x64-windows-{build}.zip"
        install_dir = colmap_root / version / build
        marker = install_dir / ".installed"

        if marker.exists():
            existing = find_files(install_dir, ["COLMAP.bat", "colmap.bat"])
            if existing:
                return existing[0]
            marker.unlink(missing_ok=True)

        url = f"https://github.com/colmap/colmap/releases/download/{version}/{asset}"
        archive = colmap_root / version / asset
        download_file(url, archive)

        if install_dir.exists():
            shutil.rmtree(install_dir)
        extract_zip(archive, install_dir)

        candidates = find_files(install_dir, ["COLMAP.bat", "colmap.bat"])
        if not candidates:
            raise ToolNotFoundError("Downloaded COLMAP, but could not locate COLMAP.bat in the archive.")

        marker.write_text("ok", encoding="utf-8")
        return candidates[0]

    def colmap_exec(self) -> ToolExec:
        # 1) user-specified
        if self.settings.tool_paths.colmap:
            exe = Path(self.settings.tool_paths.colmap)
            if exe.exists():
                if os.name == "nt" and exe.suffix.lower() in {".bat", ".cmd"}:
                    return ToolExec(exe=exe, prefix=["cmd.exe", "/c", str(exe)], env={})
                return ToolExec(exe=exe, prefix=[str(exe)], env={})
            raise ToolNotFoundError(f"Configured COLMAP path does not exist: {exe}")

        # 2) PATH
        found = self.runner.which("colmap")
        if found:
            p = Path(found)
            if os.name == "nt" and p.suffix.lower() in {".bat", ".cmd"}:
                return ToolExec(exe=p, prefix=["cmd.exe", "/c", str(p)], env={})
            return ToolExec(exe=p, prefix=[found], env={})

        # 3) official release (Windows)
        if self.settings.colmap.source == "official":
            try:
                bat = self.ensure_colmap_official()
                return ToolExec(exe=bat, prefix=["cmd.exe", "/d", "/s", "/c", str(bat)], env={})
            except ToolNotFoundError:
                if not self.settings.auto_install_tools:
                    raise

        # 4) conda-forge fallback
        env_prefix = self.ensure_env("colmap", ["colmap"])
        micromamba = self.ensure_micromamba()

        extra_path = self._env_bin_dirs(env_prefix)
        env = self._with_path({}, extra_path)

        prefix = [str(micromamba), "run", "-p", str(env_prefix), "colmap"]
        return ToolExec(exe=Path("colmap"), prefix=prefix, env=env)

    def colmap_options(self, colmap_command: str) -> frozenset[str]:
        cached = self._colmap_options_cache.get(colmap_command)
        if cached is not None:
            return cached

        tool = self.colmap_exec()
        try:
            out = self.runner.run_capture(
                [*tool.prefix, colmap_command, "-h"],
                options=RunOptions(env=tool.env),
            )
        except Exception:
            opts: frozenset[str] = frozenset()
        else:
            found: set[str] = set()
            for line in out.splitlines():
                m = _COLMAP_OPT_RE.match(line)
                if m:
                    found.add(m.group(1))
            opts = frozenset(found)

        self._colmap_options_cache[colmap_command] = opts
        return opts

    # -------------------------
    # Sharp Frames
    # -------------------------
    def sharp_frames_exe(self) -> ToolExec:
        found = self.runner.which("sharp-frames")
        if found:
            return ToolExec(exe=Path(found), prefix=[found], env={})

        # fall back to `python -m sharp_frames`
        prefix = [sys.executable, "-m", "sharp_frames"]
        return ToolExec(exe=Path(sys.executable), prefix=prefix, env={})

    # -------------------------
    # LichtFeld Studio
    # -------------------------
    def lichtfeld_exec(self) -> ToolExec:
        # 1) user-specified
        if self.settings.tool_paths.lichtfeld:
            exe = Path(self.settings.tool_paths.lichtfeld)
            if exe.exists():
                return ToolExec(exe=exe, prefix=[str(exe)], env={})
            raise ToolNotFoundError(f"Configured LichtFeld path does not exist: {exe}")

        # 2) PATH
        for cand in ("LichtFeld-Studio", "LichtFeld-Studio.exe"):
            found = self.runner.which(cand)
            if found:
                return ToolExec(exe=Path(found), prefix=[found], env={})

        # 3) auto-download (best effort)
        if not self.settings.auto_install_tools:
            raise ToolNotFoundError("LichtFeld Studio not found. Please install it and configure its path.")

        exe = self._download_lichtfeld()
        return ToolExec(exe=exe, prefix=[str(exe)], env={})

    def _download_lichtfeld(self) -> Path:
        tool_dir = self.paths.tools_dir / "lichtfeld"
        tool_dir.mkdir(parents=True, exist_ok=True)

        platform_tag = self._platform_tag()
        keywords = self._lichtfeld_keywords(platform_tag)

        api = "https://api.github.com/repos/MrNeRF/LichtFeld-Studio/releases/latest"
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "SplatFlow"}
        r = requests.get(api, headers=headers, timeout=30)
        r.raise_for_status()
        data = r.json()

        assets = data.get("assets") or []
        url = None
        name = None
        for a in assets:
            n = (a.get("name") or "").lower()
            u = a.get("browser_download_url")
            if not u:
                continue
            if not n.endswith(".zip"):
                continue
            if any(k in n for k in keywords):
                url = u
                name = a.get("name") or "lichtfeld.zip"
                break

        if not url:
            raise ToolNotFoundError(
                "Could not auto-download LichtFeld Studio for this platform. "
                "Install it manually and set its path in settings."
            )

        archive = tool_dir / (name or "lichtfeld.zip")
        download_file(url, archive)
        extract_dir = tool_dir / "extracted"
        if extract_dir.exists():
            import shutil
            shutil.rmtree(extract_dir)
        extract_zip(archive, extract_dir)

        inner = next((p for p in extract_dir.rglob("*.zip") if p.is_file()), None)
        inner_dir = extract_dir / "inner"
        if inner:
            if inner_dir.exists():
                import shutil
                shutil.rmtree(inner_dir)
            extract_zip(inner, inner_dir)

        for root in ([inner_dir, extract_dir] if inner else [extract_dir]):
            candidates = find_files(root, ["LichtFeld-Studio.exe", "LichtFeld-Studio"])
            if candidates:
                return candidates[0]

        raise ToolNotFoundError("Downloaded LichtFeld Studio, but couldn't locate the executable.")

    def _lichtfeld_keywords(self, platform_tag: str) -> list[str]:
        if platform_tag.startswith("win"):
            return ["win", "windows", "portable", "x64", "64"]
        if platform_tag.startswith("linux"):
            return ["linux", "ubuntu", "x64", "64"]
        if platform_tag.startswith("osx"):
            return ["mac", "osx", "darwin", "arm64", "x64", "64"]
        return []
