#!/usr/bin/env python3
"""Assess biological equivalence between frozen and Nextflow SIMPLseq outputs."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import pandas as pd


PASS = "PASS"
WARN = "WARN"
FAIL = "FAIL"
MISSING = "MISSING"


@dataclass
class Check:
    check: str
    status: str
    details: str
    frozen_path: str = ""
    nextflow_path: str = ""


def read_table(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, sep="\t", dtype=str, keep_default_na=False)


def read_matrix(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, sep="\t")
    df = df.rename(columns={df.columns[0]: "sample"}).set_index("sample")
    return df.apply(pd.to_numeric, errors="coerce").fillna(0).astype(int)


def normalize_table(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df = df.loc[:, sorted(df.columns)]
    return df.sort_values(list(df.columns)).reset_index(drop=True)


def fasta_records(path: Path) -> dict[str, str]:
    records: dict[str, str] = {}
    name: str | None = None
    chunks: list[str] = []
    with path.open() as handle:
        for raw in handle:
            line = raw.strip()
            if not line:
                continue
            if line.startswith(">"):
                if name is not None:
                    records[name] = "".join(chunks)
                name = line[1:].split()[0]
                chunks = []
            else:
                chunks.append(line)
    if name is not None:
        records[name] = "".join(chunks)
    return records


def missing_check(name: str, frozen: Path, nextflow: Path) -> Check | None:
    if frozen.exists() and nextflow.exists():
        return None
    return Check(
        name,
        MISSING,
        f"frozen_exists={frozen.exists()} nextflow_exists={nextflow.exists()}",
        str(frozen),
        str(nextflow),
    )


def compare_fasta(name: str, frozen: Path, nextflow: Path) -> Check:
    missing = missing_check(name, frozen, nextflow)
    if missing:
        return missing
    left = fasta_records(frozen)
    right = fasta_records(nextflow)
    common_ids = set(left) & set(right)
    changed_ids = sum(1 for asv_id in common_ids if left[asv_id] != right[asv_id])
    same_ids = set(left) == set(right)
    same_multiset = sorted(left.values()) == sorted(right.values())
    status = PASS if same_ids and changed_ids == 0 else FAIL
    details = (
        f"records frozen={len(left)} nextflow={len(right)}; "
        f"same_ids={same_ids}; common_ids={len(common_ids)}; "
        f"changed_ids={changed_ids}; same_sequence_multiset={same_multiset}"
    )
    return Check(name, status, details, str(frozen), str(nextflow))


def compare_exact_table(name: str, frozen: Path, nextflow: Path) -> Check:
    missing = missing_check(name, frozen, nextflow)
    if missing:
        return missing
    left = normalize_table(read_table(frozen))
    right = normalize_table(read_table(nextflow))
    same = left.equals(right)
    status = PASS if same else FAIL
    details = f"shape frozen={left.shape} nextflow={right.shape}; normalized_equal={same}"
    return Check(name, status, details, str(frozen), str(nextflow))


def compare_mapped_asv_table(name: str, frozen: Path, nextflow: Path, count_delta_warn: int) -> Check:
    missing = missing_check(name, frozen, nextflow)
    if missing:
        return missing

    left = read_table(frozen)
    right = read_table(nextflow)
    key = "hapid" if "hapid" in left.columns and "hapid" in right.columns else left.columns[0]
    left_ids = set(left[key])
    right_ids = set(right[key])
    if left_ids != right_ids:
        return Check(
            name,
            FAIL,
            f"ASV IDs differ frozen_only={len(left_ids - right_ids)} nextflow_only={len(right_ids - left_ids)}",
            str(frozen),
            str(nextflow),
        )

    stable_cols = [
        col
        for col in left.columns
        if col in right.columns and col not in {key, "total_reads", "total_samples"}
    ]
    count_cols = [col for col in ["total_reads", "total_samples"] if col in left.columns and col in right.columns]

    lidx = left.set_index(key).sort_index()
    ridx = right.set_index(key).sort_index()

    differing_stable_cols = []
    for col in stable_cols:
        if not lidx[col].astype(str).equals(ridx[col].astype(str)):
            differing_stable_cols.append(col)

    count_notes: list[str] = []
    count_status = PASS
    for col in count_cols:
        lnum = pd.to_numeric(lidx[col], errors="coerce").fillna(0).astype(int)
        rnum = pd.to_numeric(ridx[col], errors="coerce").fillna(0).astype(int)
        delta = (lnum - rnum).abs()
        changed = int((delta != 0).sum())
        max_delta = int(delta.max()) if len(delta) else 0
        count_notes.append(f"{col}: changed_rows={changed} max_abs_delta={max_delta}")
        if max_delta > count_delta_warn:
            count_status = WARN
        elif changed:
            count_status = WARN

    if differing_stable_cols:
        status = FAIL
    else:
        status = count_status
    details = (
        f"shape frozen={left.shape} nextflow={right.shape}; stable_columns_equal={not differing_stable_cols}; "
        f"differing_stable_columns={','.join(differing_stable_cols) if differing_stable_cols else 'none'}; "
        + "; ".join(count_notes)
    )
    return Check(name, status, details, str(frozen), str(nextflow))


def threshold_crossings(left: pd.DataFrame, right: pd.DataFrame, thresholds: list[int]) -> dict[int, int]:
    crossings: dict[int, int] = {}
    for threshold in thresholds:
        crossings[threshold] = int(((left >= threshold) != (right >= threshold)).to_numpy().sum())
    return crossings


def compare_matrix(
    name: str,
    frozen: Path,
    nextflow: Path,
    *,
    role: str,
    max_delta_warn: int,
    total_delta_warn: int,
    thresholds: list[int],
) -> Check:
    missing = missing_check(name, frozen, nextflow)
    if missing:
        return missing

    left = read_matrix(frozen)
    right = read_matrix(nextflow)
    if left.index.duplicated().any() or right.index.duplicated().any():
        return Check(name, FAIL, "duplicate sample IDs detected", str(frozen), str(nextflow))

    same_rows = list(left.index) == list(right.index)
    same_cols = list(left.columns) == list(right.columns)
    if set(left.index) != set(right.index) or set(left.columns) != set(right.columns):
        return Check(
            name,
            FAIL,
            (
                f"rows/columns differ same_row_order={same_rows} same_col_order={same_cols}; "
                f"frozen_only_rows={len(set(left.index) - set(right.index))}; "
                f"nextflow_only_rows={len(set(right.index) - set(left.index))}; "
                f"frozen_only_cols={len(set(left.columns) - set(right.columns))}; "
                f"nextflow_only_cols={len(set(right.columns) - set(left.columns))}"
            ),
            str(frozen),
            str(nextflow),
        )

    common_rows = sorted(set(left.index) & set(right.index))
    common_cols = sorted(set(left.columns) & set(right.columns))
    lmat = left.loc[common_rows, common_cols]
    rmat = right.loc[common_rows, common_cols]
    delta = (lmat - rmat).abs()
    changed = int((delta != 0).to_numpy().sum())
    max_delta = int(delta.to_numpy().max()) if delta.size else 0
    total_left = int(lmat.to_numpy().sum())
    total_right = int(rmat.to_numpy().sum())
    total_delta = abs(total_left - total_right)
    crossings = threshold_crossings(lmat, rmat, thresholds)
    crossing_total = sum(crossings.values())

    if changed == 0:
        status = PASS
    elif role == "raw":
        status = FAIL if max_delta > max_delta_warn or total_delta > total_delta_warn else WARN
    else:
        status = (
            FAIL
            if max_delta > max_delta_warn or total_delta > total_delta_warn or crossing_total > 0
            else WARN
        )

    crossing_text = ",".join(f"{k}:{v}" for k, v in crossings.items())
    details = (
        f"shape frozen={left.shape} nextflow={right.shape}; "
        f"same_rows={same_rows}; same_cols={same_cols}; "
        f"changed_cells={changed}; max_abs_delta={max_delta}; "
        f"total_reads frozen={total_left} nextflow={total_right}; total_delta={total_delta}; "
        f"threshold_crossings={crossing_text}"
    )
    return Check(name, status, details, str(frozen), str(nextflow))


def parse_thresholds(value: str) -> list[int]:
    thresholds = [int(part.strip()) for part in value.split(",") if part.strip()]
    return sorted(set(thresholds))


def write_reports(checks: list[Check], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    rows = [check.__dict__ for check in checks]
    pd.DataFrame(rows).to_csv(out.with_suffix(".tsv"), sep="\t", index=False)

    failures = [check for check in checks if check.status in {FAIL, MISSING}]
    warnings = [check for check in checks if check.status == WARN]
    if failures:
        result = "FAIL"
    elif warnings:
        result = "PASS_WITH_WARNINGS"
    else:
        result = "PASS"

    with out.open("w", encoding="utf-8") as handle:
        handle.write("# SIMPLseq Biological Equivalence Report\n\n")
        handle.write(f"Overall result: **{result}**\n\n")
        handle.write("| Check | Status | Details |\n")
        handle.write("| --- | --- | --- |\n")
        for check in checks:
            details = check.details.replace("|", "\\|")
            handle.write(f"| {check.check} | {check.status} | {details} |\n")
        handle.write("\n## Interpretation\n\n")
        if failures:
            handle.write(
                "At least one biologically critical check failed or was missing. "
                "Review failures before treating the Nextflow run as equivalent.\n"
            )
        elif warnings:
            handle.write(
                "No biologically critical identity check failed. Warnings indicate bounded count drift "
                "or count-only ASV-map differences that should be reviewed, especially if reporting thresholds are used.\n"
            )
        else:
            handle.write("All compared biological-equivalence checks passed without warnings.\n")


def build_checks(args: argparse.Namespace) -> list[Check]:
    frozen = args.frozen
    nextflow = args.nextflow
    thresholds = parse_thresholds(args.report_thresholds)
    return [
        compare_matrix(
            "Raw merged iSeq DADA2 seqtab",
            frozen / "run_dada2/seqtab_iseq.tsv",
            nextflow / "run_dada2/seqtab_iseq.tsv",
            role="raw",
            max_delta_warn=args.raw_max_delta,
            total_delta_warn=args.raw_total_delta,
            thresholds=[],
        ),
        compare_fasta(
            "ASV FASTA sequence identity",
            frozen / "run_dada2/ASVSeqs.fasta",
            nextflow / "run_dada2/ASVSeqs.fasta",
        ),
        compare_mapped_asv_table(
            "Mapped ASV biological identity",
            frozen / "run_dada2/ASV_mapped_table.tsv",
            nextflow / "run_dada2/ASV_mapped_table.tsv",
            args.asv_count_delta,
        ),
        compare_mapped_asv_table(
            "Filtered mapped ASV biological identity",
            frozen / "run_dada2/ASV_mapped_table.filtered.tsv",
            nextflow / "run_dada2/ASV_mapped_table.filtered.tsv",
            args.asv_count_delta,
        ),
        compare_exact_table(
            "ASV-to-CIGAR mapping identity",
            frozen / "run_dada2/asv_to_cigar.tsv",
            nextflow / "run_dada2/asv_to_cigar.tsv",
        ),
        compare_matrix(
            "Final CIGAR/haplotype count table",
            frozen / "run_dada2/seqtab_cigar.tsv",
            nextflow / "run_dada2/seqtab_cigar.tsv",
            role="final",
            max_delta_warn=args.final_max_delta,
            total_delta_warn=args.final_total_delta,
            thresholds=thresholds,
        ),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frozen", default="results", type=Path)
    parser.add_argument("--nextflow", default="results_nextflow", type=Path)
    parser.add_argument("--out", default="results_nextflow/qc/biological_equivalence_report.md", type=Path)
    parser.add_argument("--raw-max-delta", type=int, default=10)
    parser.add_argument("--raw-total-delta", type=int, default=100)
    parser.add_argument("--asv-count-delta", type=int, default=100)
    parser.add_argument("--final-max-delta", type=int, default=10)
    parser.add_argument("--final-total-delta", type=int, default=10)
    parser.add_argument(
        "--report-thresholds",
        default="1,10,100",
        help="Comma-separated reportability thresholds checked for final CIGAR count crossings.",
    )
    args = parser.parse_args()

    checks = build_checks(args)
    write_reports(checks, args.out)
    failures = [check for check in checks if check.status in {FAIL, MISSING}]
    warnings = [check for check in checks if check.status == WARN]
    print(f"Wrote {args.out} and {args.out.with_suffix('.tsv')}")
    print(f"Biological equivalence: failures={len(failures)} warnings={len(warnings)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
