"""Thin GUI wrappers around the canonical SIMPLseq backend modules."""

from __future__ import annotations

import csv
import os
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

from simplseq.resources import human_bytes as format_bytes
from simplseq.runner import check_environment, project_root, results_manifest
from simplseq.samplesheet import SAMPLE_FIELDS, scan_fastqs, write_samples_csv


@dataclass(frozen=True)
class RuntimeCheck:
    name: str
    status: str
    detail: str


@dataclass(frozen=True)
class OutputStatus:
    label: str
    path: Path
    status: str
    size_bytes: int


def read_samples_csv(path: Path | str) -> list[dict[str, str]]:
    sample_path = Path(path).expanduser()
    if not sample_path.exists():
        return []
    with sample_path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def discover_outputs(project_root_path: Path | str, outdir: Path | str) -> list[OutputStatus]:
    project = Path(project_root_path).resolve()
    run_dir = Path(outdir)
    if not run_dir.is_absolute():
        run_dir = project / run_dir
    manifest = results_manifest(run_dir)
    statuses: list[OutputStatus] = []
    for item in manifest["files"]:
        if item["label"] not in {
            "Run summary",
            "ASV count table",
            "Mapped ASV table",
            "ASV to CIGAR map",
            "CIGAR count table",
        }:
            continue
        statuses.append(
            OutputStatus(
                label=str(item["label"]),
                path=Path(str(item["path"])),
                status="ready" if item["exists"] and item["size_bytes"] else "missing",
                size_bytes=int(item["size_bytes"]),
            )
        )
    return statuses


def runtime_checks() -> list[RuntimeCheck]:
    if os.name == "nt":
        return runtime_checks_wsl(project_root())
    rows = check_environment(project_root(), None)
    return [
        RuntimeCheck(
            name=row["name"],
            status="ready" if row["status"] == "ok" else row["status"],
            detail=row["detail"],
        )
        for row in rows
    ]


def runtime_checks_wsl(root: Path) -> list[RuntimeCheck]:
    resolved = str(root.resolve())
    if len(resolved) < 3 or resolved[1:3] != ":\\":
        return [RuntimeCheck("Project path", "missing", f"cannot translate Windows path: {resolved}")]
    root_wsl = f"/mnt/{resolved[0].lower()}{resolved[2:].replace(chr(92), '/')}"
    script = (
        f"cd {shlex.quote(root_wsl)} && "
        "simplseq check"
    )
    completed = subprocess.run(
        ["wsl", "bash", "-lc", script],
        text=True,
        capture_output=True,
        check=False,
        timeout=120,
    )
    checks: list[RuntimeCheck] = []
    for line in completed.stdout.splitlines():
        if not line.startswith("["):
            continue
        marker, _, rest = line.partition("]")
        name, _, detail = rest.strip().partition(":")
        status = {"[OK": "ready", "[WARN": "warn", "[MISS": "missing"}.get(marker, "missing")
        checks.append(RuntimeCheck(name.strip(), status, detail.strip()))
    if not checks:
        detail = completed.stderr.strip() or completed.stdout.strip() or "runtime check failed"
        checks.append(RuntimeCheck("SIMPLseq backend", "missing", detail[:300]))
    return checks


def local_backend_ready(checks: list[RuntimeCheck]) -> bool:
    critical = {"Python", "Rscript", "MUSCLE", "Java", "Nextflow", "DADA2 loads"}
    seen_ready = {check.name for check in checks if check.status in {"ok", "ready", "warn"}}
    return critical.issubset(seen_ready)


def shell_join(parts: list[str]) -> str:
    return " ".join(parts)
