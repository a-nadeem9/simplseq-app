"""Local runner for SIMPLseq.

The GUI calls the repository-local ``simplseq`` CLI. On Windows, the actual
workflow is launched through WSL because SIMPLseq's scientific runtime is
Linux-first.
"""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


DEFAULT_CPUS = 4
DEFAULT_MEMORY = "12 GB"


@dataclass(frozen=True)
class CommandResult:
    command: list[str]
    returncode: int
    stdout: str
    stderr: str


def run_command(command: list[str], cwd: Path, timeout: int | None = None) -> CommandResult:
    completed = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout,
    )
    return CommandResult(command, completed.returncode, completed.stdout, completed.stderr)


def start_command(command: list[str], cwd: Path, stdout_path: Path, stderr_path: Path) -> CommandResult:
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stderr_path.parent.mkdir(parents=True, exist_ok=True)
    stdout_handle = stdout_path.open("w", encoding="utf-8")
    stderr_handle = stderr_path.open("w", encoding="utf-8")
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    popen_kwargs = {}
    if os.name == "nt":
        popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    else:
        popen_kwargs["start_new_session"] = True
    subprocess.Popen(
        command,
        cwd=cwd,
        text=True,
        stdout=stdout_handle,
        stderr=stderr_handle,
        **popen_kwargs,
    )
    stdout_handle.close()
    stderr_handle.close()
    return CommandResult(
        command,
        0,
        f"Started SIMPLseq local run. Logs: {stdout_path.name}, {stderr_path.name}\n",
        "",
    )


def windows_to_wsl_path(path: Path) -> str:
    resolved = str(path.resolve())
    if os.name != "nt":
        return resolved
    completed = subprocess.run(
        ["wsl", "wslpath", "-a", resolved],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode == 0 and completed.stdout.strip():
        return completed.stdout.strip()
    drive = resolved[0].lower()
    rest = resolved[2:].replace("\\", "/")
    return f"/mnt/{drive}{rest}"


def local_cli_command(project_root: Path, samples: str, outdir: str, *, clean: bool, dry_run: bool) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "simplseq",
        "run-headless",
        "--samples",
        samples,
        "--out",
        outdir,
        "--cpus",
        str(DEFAULT_CPUS),
        "--memory",
        DEFAULT_MEMORY,
    ]
    if clean:
        command.append("--no-resume")
    if dry_run:
        command.append("--dry-run")
    if os.name == "nt":
        root_wsl = windows_to_wsl_path(project_root)
        wsl_command = ["simplseq", *command[3:]]
        bash_script = f"cd {shlex.quote(root_wsl)} && " + " ".join(shlex.quote(part) for part in wsl_command)
        return ["wsl", "bash", "-lc", bash_script]
    return command


def run_local_pipeline(
    project_root: Path,
    samples: str,
    outdir: str,
    runtime: str | None = None,
    *,
    clean: bool = False,
    dry_run: bool = False,
) -> CommandResult:
    command = local_cli_command(project_root, samples, outdir, clean=clean, dry_run=dry_run)
    if dry_run:
        return run_command(command, cwd=project_root)
    return run_command(command, cwd=project_root)


def start_local_pipeline(
    project_root: Path,
    samples: str,
    outdir: str,
    runtime: str | None = None,
    *,
    clean: bool = False,
    dry_run: bool = False,
) -> CommandResult:
    command = local_cli_command(project_root, samples, outdir, clean=clean, dry_run=dry_run)
    if dry_run:
        return run_command(command, cwd=project_root)
    log_dir = project_root / "gui" / "logs"
    safe_outdir = outdir.replace("/", "_").replace("\\", "_").replace(":", "_") or "results"
    return start_command(
        command,
        cwd=project_root,
        stdout_path=log_dir / f"local-run-{safe_outdir}.out.log",
        stderr_path=log_dir / f"local-run-{safe_outdir}.err.log",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run SIMPLseq locally.")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--samples", default="samples.csv")
    parser.add_argument("--outdir", default="results")
    parser.add_argument("--clean", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    result = run_local_pipeline(
        project_root,
        args.samples,
        args.outdir,
        clean=args.clean,
        dry_run=args.dry_run,
    )
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    if result.stderr:
        print(result.stderr, end="" if result.stderr.endswith("\n") else "\n")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
