from __future__ import annotations

import os
import shutil
import subprocess
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence

from .errors import CommandFailedError


LineCallback = Callable[[str], None]


@dataclass(frozen=True)
class RunOptions:
    cwd: Path | None = None
    env: Mapping[str, str] | None = None
    tail_lines: int = 200


class CommandRunner:
    def which(self, exe: str) -> str | None:
        return shutil.which(exe)

    def run(
        self,
        command: Sequence[str],
        *,
        options: RunOptions | None = None,
        on_line: LineCallback | None = None,
    ) -> None:
        options = options or RunOptions()
        env = os.environ.copy()
        if options.env:
            env.update({k: str(v) for k, v in options.env.items()})

        tail = deque(maxlen=options.tail_lines)
        start = time.time()

        proc = subprocess.Popen(
            list(map(str, command)),
            cwd=str(options.cwd) if options.cwd else None,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True,
        )

        assert proc.stdout is not None
        try:
            for line in proc.stdout:
                line = line.rstrip("\n")
                tail.append(line)
                if on_line:
                    on_line(line)
        finally:
            proc.stdout.close()

        returncode = proc.wait()
        _ = time.time() - start

        if returncode != 0:
            raise CommandFailedError(command=command, returncode=returncode, tail="\n".join(tail))

    def run_capture(
        self,
        command: Sequence[str],
        *,
        options: RunOptions | None = None,
    ) -> str:
        options = options or RunOptions()
        env = os.environ.copy()
        if options.env:
            env.update({k: str(v) for k, v in options.env.items()})

        proc = subprocess.run(
            list(map(str, command)),
            cwd=str(options.cwd) if options.cwd else None,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            universal_newlines=True,
        )
        out = proc.stdout or ""
        if proc.returncode != 0:
            tail = "\n".join(out.splitlines()[-options.tail_lines :])
            raise CommandFailedError(command=command, returncode=proc.returncode, tail=tail)
        return out
