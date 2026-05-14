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
MONTH_ALIASES = {key.lower(): value for key, value in MONTHS.items()}
MONTH_ALIASES["sept"] = "09"
MONTH_PATTERN = r"Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec"
NON_PARTICIPANT_TOKEN_RE = re.compile(r"^(run|lane|pool|amplicon|l)[0-9A-Za-z]*$", re.IGNORECASE)
NEGATIVE_SAMPLE_RE = re.compile(
    r"(^|[^a-z0-9])(ctrl|control|ntc|negative|neg|blank|no[-_ ]?template)([^a-z0-9]|$)",
    re.IGNORECASE,
)

SAMPLE_FIELDS = [
    "sample_id",
    "fastq_1",
    "fastq_2",
    "sample_type",
    "participant_id",
    "collection_date",
    "replicate",
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


def _month_number(value: str) -> str:
    return MONTH_ALIASES.get(value.lower(), "")


def _format_date(year: str, month: str, day: str = "") -> str:
    month_int = int(month)
    if day:
        return f"{int(year):04d}-{month_int:02d}-{int(day):02d}"
    return f"{int(year):04d}-{month_int:02d}"


def _looks_like_date_token(token: str) -> bool:
    return bool(
        re.fullmatch(rf"({MONTH_PATTERN})[0-9]{{4}}", token, re.IGNORECASE)
        or re.fullmatch(rf"[0-9]{{4}}({MONTH_PATTERN})", token, re.IGNORECASE)
        or re.fullmatch(r"[0-9]{6,8}", token)
    )


def infer_sample_type(sample_id: str) -> str:
    return "negative" if NEGATIVE_SAMPLE_RE.search(sample_id) else "sample"


def parse_label_metadata(label: str) -> dict[str, str]:
    parsed = {
        "participant_id": "",
        "collection_date": "",
        "replicate": "",
    }

    compact = re.match(
        rf"^(?P<participant>[A-Za-z]+[0-9]+)(?P<month>{MONTH_PATTERN})(?P<year>[0-9]{{4}})(?P<replicate>Rep[0-9A-Za-z]+)$",
        label,
        re.IGNORECASE,
    )
    if compact:
        parsed["participant_id"] = compact.group("participant")
        parsed["collection_date"] = f"{compact.group('year')}-{_month_number(compact.group('month'))}"
        parsed["replicate"] = compact.group("replicate")
        return parsed

    replicate = re.search(r"(Rep(?:licate)?[-_ .]*[0-9]+[A-Za-z]?)", label, re.IGNORECASE)
    if replicate:
        parsed["replicate"] = re.sub(
            r"^Replicate",
            "Rep",
            re.sub(r"[-_ .]+", "", replicate.group(1)),
            flags=re.IGNORECASE,
        )

    month_year = re.search(
        rf"(?P<month>{MONTH_PATTERN})[-_ .]*(?P<year>[0-9]{{4}})",
        label,
        re.IGNORECASE,
    )
    year_month = re.search(
        rf"(?P<year>[0-9]{{4}})[-_ .]*(?P<month>{MONTH_PATTERN})",
        label,
        re.IGNORECASE,
    )
    iso_date = re.search(
        r"(?P<year>20[0-9]{2}|19[0-9]{2})[-_ .](?P<month>[0-9]{1,2})(?:[-_ .](?P<day>[0-9]{1,2}))?",
        label,
    )
    compact_date = re.search(r"(?P<year>20[0-9]{2}|19[0-9]{2})(?P<month>[0-9]{2})(?P<day>[0-9]{2})", label)

    if month_year:
        parsed["collection_date"] = f"{month_year.group('year')}-{_month_number(month_year.group('month'))}"
    elif year_month:
        parsed["collection_date"] = f"{year_month.group('year')}-{_month_number(year_month.group('month'))}"
    elif iso_date:
        parsed["collection_date"] = _format_date(
            iso_date.group("year"),
            iso_date.group("month"),
            iso_date.group("day") or "",
        )
    elif compact_date:
        parsed["collection_date"] = _format_date(
            compact_date.group("year"),
            compact_date.group("month"),
            compact_date.group("day"),
        )

    tokens = [token for token in re.split(r"[^A-Za-z0-9]+", label) if token]
    for token in tokens:
        if re.fullmatch(rf"{MONTH_PATTERN}", token, re.IGNORECASE):
            continue
        if re.fullmatch(r"Rep(?:licate)?[0-9A-Za-z]*", token, re.IGNORECASE):
            continue
        if re.fullmatch(r"(20[0-9]{2}|19[0-9]{2}|[0-9]{1,2})", token):
            continue
        if _looks_like_date_token(token):
            continue
        if NON_PARTICIPANT_TOKEN_RE.fullmatch(token):
            continue
        if re.search(r"[A-Za-z]", token) and re.search(r"[0-9]", token):
            parsed["participant_id"] = token
            break

    return parsed


def parse_fastq_name(name: str, include_pool_in_sample_id: bool = False) -> dict[str, str]:
    base = os.path.basename(name)
    read_parts = split_read_suffix(base)
    stripped = read_parts[0] if read_parts else re.sub(r"_R[12](?:_001)?\.f(?:ast)?q\.gz$", "", base)
    parsed = {
        "sample_id": stripped,
        "participant_id": "",
        "collection_date": "",
        "replicate": "",
    }
    mpg = re.match(
        r"^mpg_(?P<run>[^_]+)_Amplicon-Pool-(?P<pool>[0-9]+)-(?P<label>.+)$",
        stripped,
    )
    if mpg:
        label = mpg.group("label")
        parsed["sample_id"] = f"{label}_Pool{mpg.group('pool')}" if include_pool_in_sample_id else label
    else:
        label = stripped

    parsed.update(parse_label_metadata(label))
    return parsed


def _safe_exists(path: Path) -> bool:
    try:
        return path.exists()
    except OSError:
        return False


def _safe_files(root: Path) -> list[Path]:
    files: list[Path] = []
    try:
        for entry in root.iterdir():
            try:
                if entry.is_file():
                    files.append(entry)
            except OSError:
                continue
    except OSError:
        return files
    return files


def _safe_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def scan_fastqs(fastq_dir: Path | str, *, include_pool_in_sample_id: bool = False) -> FastqScan:
    try:
        root = user_path(fastq_dir).resolve()
    except OSError:
        root = user_path(fastq_dir).expanduser()
    if not _safe_exists(root):
        return FastqScan(root, [], [], [], 0, 0, [])
    files = _safe_files(root)
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
    for prefix, (f1, _suffix) in sorted(r1.items()):
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
                sample_type=infer_sample_type(sample_id),
                participant_id=parsed["participant_id"],
                collection_date=parsed["collection_date"],
                replicate=parsed["replicate"],
            )
        )
    orphan_r2 = sorted(path.name for prefix, (path, _suffix) in r2.items() if prefix not in r1)
    duplicate_ids = sorted(
        sample_id for sample_id, count in Counter(pair.sample_id for pair in pairs).items() if count > 1
    )
    total_bytes = sum(_safe_size(p) for p in files if split_read_suffix(p.name))
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
