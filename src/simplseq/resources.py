"""Local machine and input resource checks."""

from __future__ import annotations

import csv
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from .pathutils import user_path


@dataclass(frozen=True)
class ResourceSnapshot:
    cpu_count: int
    memory_bytes: int
    output_free_bytes: int


def memory_bytes() -> int:
    if hasattr(os, "sysconf"):
        try:
            pages = os.sysconf("SC_PHYS_PAGES")
            page_size = os.sysconf("SC_PAGE_SIZE")
            return int(pages * page_size)
        except (OSError, ValueError):
            pass
    return 0


def snapshot(outdir: Path) -> ResourceSnapshot:
    usage_path = outdir
    while not usage_path.exists() and usage_path != usage_path.parent:
        usage_path = usage_path.parent
    usage = shutil.disk_usage(usage_path)
    return ResourceSnapshot(
        cpu_count=os.cpu_count() or 1,
        memory_bytes=memory_bytes(),
        output_free_bytes=usage.free,
    )


def human_bytes(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{size} B"


def fastq_paths_from_samples(samples: Path, samples_root: Path | None = None) -> list[Path]:
    samples_root = samples_root or samples.parent
    paths: list[Path] = []
    if not samples.exists():
        return paths
    with samples.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            for field in ("fastq_1", "fastq_2"):
                value = (row.get(field) or "").strip()
                if not value:
                    continue
                path = user_path(value)
                if not path.is_absolute():
                    path = samples_root / path
                paths.append(path)
    return paths


def sample_file_checks(samples: Path) -> list[dict[str, str]]:
    paths = fastq_paths_from_samples(samples)
    found = [path for path in paths if path.exists()]
    missing = [path for path in paths if not path.exists()]
    pair_count = len(paths) // 2
    checks = [
        {
            "name": "FASTQ pairs",
            "status": "ok" if pair_count else "missing",
            "detail": str(pair_count),
        },
        {
            "name": "FASTQ files",
            "status": "ok" if not missing and paths else "missing",
            "detail": f"{len(found)}/{len(paths)} found",
        },
    ]
    if missing:
        preview = ", ".join(path.name for path in missing[:5])
        if len(missing) > 5:
            preview += f", ... plus {len(missing) - 5} more"
        checks.append(
            {
                "name": "Missing FASTQs",
                "status": "missing",
                "detail": preview,
            }
        )
    return checks


def resource_checks(samples: Path | None, outdir: Path) -> list[dict[str, str]]:
    snap = snapshot(outdir)
    checks = [
        {
            "name": "CPU cores",
            "status": "ok" if snap.cpu_count >= 2 else "warn",
            "detail": str(snap.cpu_count),
        },
        {
            "name": "Setup RAM check",
            "status": "ok" if snap.memory_bytes >= 8 * 1024**3 else "warn",
            "detail": f"{human_bytes(snap.memory_bytes)} available" if snap.memory_bytes else "unknown",
        },
        {
            "name": "Large/high-depth datasets",
            "status": "warn",
            "detail": "may require much more RAM",
        },
        {
            "name": "Output disk",
            "status": "ok" if snap.output_free_bytes >= 20 * 1024**3 else "warn",
            "detail": f"{human_bytes(snap.output_free_bytes)} free at {outdir}",
        },
    ]
    if samples:
        total = sum(path.stat().st_size for path in fastq_paths_from_samples(samples) if path.exists())
        checks.append(
            {
                "name": "Input FASTQ size",
                "status": "ok",
                "detail": human_bytes(total),
            }
        )
    return checks
