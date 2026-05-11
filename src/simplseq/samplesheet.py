"""FASTQ discovery and SIMPLseq sample sheet writing."""

from __future__ import annotations

import csv
import os
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .pathutils import user_path


MONTHS = {
    "Jan": "01",
    "Feb": "02",
    "Mar": "03",
    "Apr": "04",
    "May": "05",
    "Jun": "06",
    "Jul": "07",
    "Aug": "08",
    "Sep": "09",
    "Oct": "10",
    "Nov": "11",
    "Dec": "12",
}

SAMPLE_FIELDS = [
    "sample_id",
    "fastq_1",
    "fastq_2",
    "sample_type",
    "participant_id",
    "collection_date",
    "replicate",
    "plate_id",
    "well",
    "expected_fwd_barcode",
    "expected_rev_barcode",
    "sequencing_run",
    "amplicon_pool",
]

READ_SUFFIXES = [
    ("_R1.fastq.gz", "_R2.fastq.gz"),
    ("_R1_001.fastq.gz", "_R2_001.fastq.gz"),
    ("_R1.fq.gz", "_R2.fq.gz"),
    ("_R1_001.fq.gz", "_R2_001.fq.gz"),
]


@dataclass(frozen=True)
class FastqPair:
    sample_id: str
    fastq_1: Path
    fastq_2: Path
    sample_type: str
    participant_id: str = ""
    collection_date: str = ""
    replicate: str = ""
    sequencing_run: str = ""
    amplicon_pool: str = ""


@dataclass(frozen=True)
class FastqScan:
    fastq_dir: Path
    pairs: list[FastqPair]
    missing_r2: list[str]
    orphan_r2: list[str]
    md5_files: int
    total_fastq_bytes: int
    duplicate_sample_ids: list[str]


def split_read_suffix(name: str) -> tuple[str, str, str] | None:
    for r1_suffix, r2_suffix in READ_SUFFIXES:
        if name.endswith(r1_suffix):
            return name[: -len(r1_suffix)], "R1", r1_suffix
        if name.endswith(r2_suffix):
            return name[: -len(r2_suffix)], "R2", r2_suffix
    return None


def mate_name(prefix: str, suffix: str) -> str:
    for r1_suffix, r2_suffix in READ_SUFFIXES:
        if suffix == r1_suffix:
            return prefix + r2_suffix
        if suffix == r2_suffix:
            return prefix + r1_suffix
    return prefix + suffix


def parse_fastq_name(name: str, include_pool_in_sample_id: bool = False) -> dict[str, str]:
    base = os.path.basename(name)
    read_parts = split_read_suffix(base)
    stripped = read_parts[0] if read_parts else re.sub(r"_R[12](?:_001)?\.f(?:ast)?q\.gz$", "", base)
    parsed = {
        "sample_id": stripped,
        "participant_id": "",
        "collection_date": "",
        "replicate": "",
        "sequencing_run": "",
        "amplicon_pool": "",
    }
    mpg = re.match(
        r"^mpg_(?P<run>[^_]+)_Amplicon-Pool-(?P<pool>[0-9]+)-(?P<label>.+)$",
        stripped,
    )
    if mpg:
        label = mpg.group("label")
        parsed["sequencing_run"] = mpg.group("run")
        parsed["amplicon_pool"] = mpg.group("pool")
        parsed["sample_id"] = f"{label}_Pool{mpg.group('pool')}" if include_pool_in_sample_id else label
    else:
        label = stripped

    longitudinal = re.match(
        r"^(?P<participant>[A-Za-z]+[0-9]+)(?P<month>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)(?P<year>[0-9]{4})(?P<replicate>Rep[0-9]+)$",
        label,
    )
    if longitudinal:
        parsed["participant_id"] = longitudinal.group("participant")
        parsed["collection_date"] = f"{longitudinal.group('year')}-{MONTHS[longitudinal.group('month')]}"
        parsed["replicate"] = longitudinal.group("replicate")
    return parsed


def scan_fastqs(fastq_dir: Path | str, *, include_pool_in_sample_id: bool = False) -> FastqScan:
    root = user_path(fastq_dir).resolve()
    if not root.exists():
        return FastqScan(root, [], [], [], 0, 0, [])
    files = [p for p in root.iterdir() if p.is_file()]
    r1: dict[str, tuple[Path, str]] = {}
    r2: dict[str, tuple[Path, str]] = {}
    for path in files:
        read_parts = split_read_suffix(path.name)
        if not read_parts:
            continue
        prefix, read, suffix = read_parts
        if read == "R1":
            r1[prefix] = (path, suffix)
        else:
            r2[prefix] = (path, suffix)
    pairs: list[FastqPair] = []
    missing_r2: list[str] = []
    for prefix, (f1, suffix) in sorted(r1.items()):
        if prefix not in r2:
            missing_r2.append(f1.name)
            continue
        f2 = r2[prefix][0]
        parsed = parse_fastq_name(f1.name, include_pool_in_sample_id=include_pool_in_sample_id)
        sample_id = parsed["sample_id"]
        pairs.append(
            FastqPair(
                sample_id=sample_id,
                fastq_1=f1,
                fastq_2=f2,
                sample_type="negative" if "ctrl" in sample_id.lower() else "sample",
                participant_id=parsed["participant_id"],
                collection_date=parsed["collection_date"],
                replicate=parsed["replicate"],
                sequencing_run=parsed["sequencing_run"],
                amplicon_pool=parsed["amplicon_pool"],
            )
        )
    orphan_r2 = sorted(path.name for prefix, (path, _suffix) in r2.items() if prefix not in r1)
    duplicate_ids = sorted(
        sample_id for sample_id, count in Counter(pair.sample_id for pair in pairs).items() if count > 1
    )
    total_bytes = sum(p.stat().st_size for p in files if split_read_suffix(p.name))
    md5_files = sum(1 for p in files if p.name.endswith(".md5"))
    return FastqScan(root, pairs, missing_r2, orphan_r2, md5_files, total_bytes, duplicate_ids)


def pair_to_row(pair: FastqPair, output_root: Path, absolute: bool) -> dict[str, str]:
    if absolute:
        fq1 = str(pair.fastq_1)
        fq2 = str(pair.fastq_2)
    else:
        fq1 = os.path.relpath(pair.fastq_1, output_root).replace(os.sep, "/")
        fq2 = os.path.relpath(pair.fastq_2, output_root).replace(os.sep, "/")
    return {
        "sample_id": pair.sample_id,
        "fastq_1": fq1,
        "fastq_2": fq2,
        "sample_type": pair.sample_type,
        "participant_id": pair.participant_id,
        "collection_date": pair.collection_date,
        "replicate": pair.replicate,
        "plate_id": "",
        "well": "",
        "expected_fwd_barcode": "",
        "expected_rev_barcode": "",
        "sequencing_run": pair.sequencing_run,
        "amplicon_pool": pair.amplicon_pool,
    }


def write_samples_csv(
    fastq_dir: Path | str,
    output_csv: Path | str,
    *,
    include_pool_in_sample_id: bool = False,
    absolute: bool = False,
) -> tuple[int, list[str]]:
    output = user_path(output_csv).resolve()
    scan = scan_fastqs(fastq_dir, include_pool_in_sample_id=include_pool_in_sample_id)
    if scan.duplicate_sample_ids:
        return 0, scan.duplicate_sample_ids
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=SAMPLE_FIELDS)
        writer.writeheader()
        for pair in scan.pairs:
            writer.writerow(pair_to_row(pair, output.parent, absolute))
    return len(scan.pairs), []
