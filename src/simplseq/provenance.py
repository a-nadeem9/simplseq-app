"""Provenance and version recording for SIMPLseq runs."""

from __future__ import annotations

import csv
import hashlib
import subprocess
from pathlib import Path
from typing import Any

from .job_state import write_json
from .resources import fastq_paths_from_samples


PINNED_PARAMETER_KEYS = [
    "amplicons_noprimers",
    "snv_filters",
    "primers_fwd",
    "primers_rev",
    "overlap_primers_fwd",
    "overlap_primers_rev",
    "pipeline_class",
    "max_ee",
    "trim_right",
    "min_len",
    "trunc_q",
    "max_consist",
    "omega_a",
    "just_concatenate",
    "dada2_randomize",
    "dada2_multithread",
    "dada2_seed",
    "strict_min_asv_length",
    "indel_filter",
    "cigar_homopolymer_mask_length",
    "cigar_min_total_reads",
    "cigar_min_samples",
    "cigar_exclude_bimeras",
    "inline_barcodes_enabled",
    "sentinel_locus",
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def md5_file(path: Path) -> str:
    digest = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_version(command: list[str], *, cwd: Path, env: dict[str, str]) -> str:
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
    except Exception as exc:
        return f"unavailable: {exc}"
    text = (completed.stdout or completed.stderr or "").strip()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in lines:
        if "version" in line.lower():
            return line
    return lines[0] if lines else f"exit {completed.returncode}"


def write_versions(path: Path, *, root: Path, env: dict[str, str]) -> None:
    versions = {
        "python": run_version(["python", "--version"], cwd=root, env=env),
        "Rscript": run_version(["Rscript", "--version"], cwd=root, env=env),
        "dada2": run_version(
            ["Rscript", "-e", 'library(dada2); cat(as.character(packageVersion("dada2")), "\\n")'],
            cwd=root,
            env=env,
        ),
        "muscle": run_version(["muscle", "-version"], cwd=root, env=env),
        "nextflow": run_version(["nextflow", "-version"], cwd=root, env=env),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(f"{key}\t{value}" for key, value in versions.items()) + "\n", encoding="utf-8")


def write_input_md5s(path: Path, samples: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["file", "size_bytes", "md5"])
        writer.writeheader()
        for fastq in fastq_paths_from_samples(samples):
            if fastq.exists():
                writer.writerow({"file": str(fastq), "size_bytes": fastq.stat().st_size, "md5": md5_file(fastq)})
            else:
                writer.writerow({"file": str(fastq), "size_bytes": "", "md5": "missing"})


def reference_checksums(root: Path) -> dict[str, str]:
    refs = [
        "reference/amplicons_noprimers.fasta",
        "reference/snv_filters.txt",
        "workflow/primers/primers_fwd.fa",
        "workflow/primers/primers_rev.fa",
        "workflow/primers/overlap_pr1.fa",
        "workflow/primers/overlap_pr2.fa",
    ]
    checksums: dict[str, str] = {}
    for rel in refs:
        path = root / rel
        checksums[rel] = sha256_file(path) if path.exists() else "missing"
    return checksums


def write_provenance(
    path: Path,
    *,
    simplseq_version: str,
    root: Path,
    samples: Path,
    outdir: Path,
    profile: str,
    parameters_file: Path,
    versions_file: Path,
    input_md5s_file: Path,
    status: str,
    completed_at: str,
) -> None:
    write_json(
        path,
        {
            "simplseq_version": simplseq_version,
            "engine": "nextflow-local",
            "runtime": "conda" if profile == "local" else profile,
            "nextflow_profile": profile,
            "samples": str(samples),
            "outdir": str(outdir),
            "parameters_file": str(parameters_file),
            "versions_file": str(versions_file),
            "input_fastq_md5s": str(input_md5s_file),
            "reference_checksums": reference_checksums(root),
            "status": status,
            "completed_at": completed_at,
        },
    )
