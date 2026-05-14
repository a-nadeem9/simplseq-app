#!/usr/bin/env python3
"""CLI helpers used by the first-pass SIMPLseq Nextflow port."""

from __future__ import annotations

import argparse
import csv
import html
import json
import os
from collections import Counter
from pathlib import Path
from urllib.parse import quote

import pandas as pd


def read_fasta_lengths(path: str) -> list[tuple[str, int]]:
    records = []
    name = None
    seq = []
    with open(path) as handle:
        for raw in handle:
            line = raw.strip()
            if not line:
                continue
            if line.startswith(">"):
                if name is not None:
                    records.append((name, len("".join(seq))))
                name = line[1:].split()[0]
                seq = []
            else:
                seq.append(line)
    if name is not None:
        records.append((name, len("".join(seq))))
    return records


def resolve_manifest_path(value: str, manifest_path: str, manifest_root: str | None = None) -> str:
    if not value:
        return value
    path = Path(value)
    if path.is_absolute():
        return str(path)
    base = Path(manifest_root).resolve() if manifest_root else Path(manifest_path).resolve().parent
    return str((base / path).resolve())


def cmd_preflight(args: argparse.Namespace) -> int:
    read_length = args.read_length
    required = ["sample_id", "fastq_1", "fastq_2"]
    rows = []

    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    with open(args.samples, newline="") as handle:
        reader = csv.DictReader(handle)
        missing_cols = [col for col in required if col not in (reader.fieldnames or [])]
        if missing_cols:
            rows.append(("ERROR", "samples_csv", "Missing required columns: " + ",".join(missing_cols)))
            sample_rows = []
        else:
            sample_rows = list(reader)

    if not sample_rows:
        rows.append(("ERROR", "samples_csv", "No samples found. Use `simplseq scan --fastq-dir data --out samples.csv`, or create samples.csv manually."))

    ids = [row.get("sample_id", "") for row in sample_rows]
    for sample_id, count in Counter(ids).items():
        if sample_id and count > 1:
            rows.append(("ERROR", sample_id, "Duplicate sample_id"))

    for row in sample_rows:
        sample_id = row.get("sample_id", "")
        for col in ["fastq_1", "fastq_2"]:
            value = row.get(col, "")
            resolved = resolve_manifest_path(value, args.samples, args.samples_root)
            if not value:
                rows.append(("ERROR", sample_id, f"Missing {col}"))
            elif not os.path.exists(resolved):
                rows.append(("ERROR", sample_id, f"{col} not found: {value}"))
            elif not os.path.exists(resolved + ".md5"):
                rows.append(("INFO", sample_id, f"{col} has no optional .md5 sidecar; SIMPLseq will compute input MD5: {value}.md5"))
        if row.get("sample_type", "").lower() in {"negative", "ntc", "control_negative"}:
            rows.append(("INFO", sample_id, "Negative control marked in manifest"))

    barcode_rows = [
        row for row in sample_rows
        if row.get("expected_fwd_barcode", "") or row.get("expected_rev_barcode", "")
    ]
    if args.inline_barcodes_enabled.lower() == "false":
        pass
    elif barcode_rows:
        incomplete = [
            row.get("sample_id", "") for row in sample_rows
            if bool(row.get("expected_fwd_barcode", "")) != bool(row.get("expected_rev_barcode", ""))
        ]
        if incomplete:
            rows.append(("ERROR", "inline_barcodes", "Incomplete barcode pairs: " + ",".join(incomplete[:20])))
        else:
            rows.append(("INFO", "inline_barcodes", f"Barcode columns populated for {len(barcode_rows)} samples"))
    else:
        rows.append(("WARN", "inline_barcodes", "No expected barcode pairs found; contamination module cannot run yet"))

    with open(args.geometry, "w", newline="") as out:
        writer = csv.writer(out, delimiter="\t")
        writer.writerow(["amplicon", "length_bp", "pe150_raw_overlap_bp", "recommended_handling"])
        for name, length in read_fasta_lengths(args.amplicons):
            overlap = (2 * read_length) - length
            if overlap >= 20:
                handling = "merge"
            elif overlap >= 12:
                handling = "borderline_validate"
            else:
                handling = "concatenate"
            writer.writerow([name, length, overlap, handling])

    with open(args.barcode, "w", newline="") as out:
        writer = csv.writer(out, delimiter="\t")
        writer.writerow(["status", "metric", "value"])
        writer.writerow(["INFO", "samples_with_expected_barcode_pairs", len(barcode_rows)])
        writer.writerow(["INFO", "sentinel_locus", args.sentinel_locus])

    if not any(status == "ERROR" for status, _, _ in rows):
        rows.insert(0, ("OK", "preflight", f"{len(sample_rows)} samples validated"))

    with open(args.report, "w", newline="") as out:
        writer = csv.writer(out, delimiter="\t")
        writer.writerow(["status", "scope", "message"])
        writer.writerows(rows)

    if any(status == "ERROR" for status, _, _ in rows):
        raise SystemExit("Preflight failed. See " + args.report)
    return 0


def cmd_write_meta(args: argparse.Namespace) -> int:
    with open(args.samples, newline="") as handle, open(args.out, "w", newline="") as out:
        reader = csv.DictReader(handle)
        writer = csv.writer(out, delimiter="\t", lineterminator="\n")
        for row in reader:
            writer.writerow([
                row["sample_id"],
                resolve_manifest_path(row["fastq_1"], args.samples, args.samples_root),
                resolve_manifest_path(row["fastq_2"], args.samples, args.samples_root),
            ])
    return 0


def cmd_write_pipeline_json(args: argparse.Namespace) -> int:
    out = {
        "path_to_meta": args.meta,
        "Class": args.pipeline_class,
        "maxEE": args.max_ee,
        "trimRight": args.trim_right,
        "minLen": args.min_len,
        "truncQ": args.trunc_q,
        "max_consist": args.max_consist,
        "omegaA": args.omega_a,
        "justConcatenate": args.just_concatenate,
        "saveRdata": args.save_rdata,
        "dada2_randomize": args.dada2_randomize,
        "dada2_multithread": args.dada2_multithread,
        "dada2_seed": args.dada2_seed,
        "pr1": args.primers_fwd,
        "pr2": args.primers_rev,
        "overlap_pr1": args.overlap_primers_fwd,
        "overlap_pr2": args.overlap_primers_rev,
    }
    with open(args.out, "w") as handle:
        json.dump(out, handle, indent=2)
        handle.write("\n")
    return 0


def read_seqtab(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, sep="\t")
    if df.empty:
        raise SystemExit(f"Empty seqtab: {path}")
    df = df.rename(columns={df.columns[0]: "sample"}).set_index("sample")
    return df.apply(pd.to_numeric, errors="coerce").fillna(0).astype(int)


def read_bimera(path: str) -> pd.DataFrame:
    if not os.path.exists(path):
        return pd.DataFrame(columns=["sequence", "bimera"])
    return pd.read_csv(path, sep="\t").astype({"sequence": str})


def cmd_prepare_stage2(args: argparse.Namespace) -> int:
    seqtab = read_seqtab(args.seqtab)
    valid_cols = [
        col for col in seqtab.columns
        if set(str(col)).issubset(set("ACGTN")) and len(str(col)) >= args.strict_min_asv_length
    ]
    strict = seqtab.loc[:, valid_cols]
    strict.to_csv(args.strict_seqtab, sep="\t", index_label="sample")

    op_bimera = read_bimera(args.op_bimera)
    nop_bimera = read_bimera(args.nop_bimera)
    corrected = pd.read_csv(args.corrected_asv, sep="\t")

    mapped_rows = []
    if not corrected.empty and not nop_bimera.empty:
        bmap = dict(zip(nop_bimera["sequence"].astype(str), nop_bimera["bimera"]))
        for _, row in corrected.iterrows():
            corrected_asv = row.get("correctedASV")
            original_asv = str(row.get("ASV", ""))
            if pd.notna(corrected_asv) and str(corrected_asv) in strict.columns and original_asv in bmap:
                mapped_rows.append({"sequence": str(corrected_asv), "bimera": bmap[original_asv]})

    op_rows = op_bimera[op_bimera["sequence"].astype(str).isin(strict.columns)].to_dict("records")
    bimera = pd.DataFrame(mapped_rows + op_rows, columns=["sequence", "bimera"])
    if not bimera.empty:
        bimera = bimera.drop_duplicates(subset=["sequence"], keep="first")
        bimera = bimera[bimera["sequence"].isin(strict.columns)]

    with open(args.strict_bimera, "w", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(["sequence", "bimera"])
        for _, row in bimera.iterrows():
            writer.writerow([row["sequence"], row["bimera"]])
    return 0


def cmd_prepare_stage3(args: argparse.Namespace) -> int:
    mapped = pd.read_csv(args.mapped, sep="\t")
    if "refid_3D7" in mapped.columns:
        filtered = mapped[mapped["refid_3D7"].astype(str) != "NA"]
    else:
        filtered = mapped
    filtered.to_csv(args.filtered_mapped, sep="\t", index=False)

    seqtab = pd.read_csv(args.seqtab, sep="\t")
    seqtab = seqtab.rename(columns={seqtab.columns[0]: "sample"})
    count_cols = [col for col in seqtab.columns if col != "sample"]
    seqtab[count_cols] = seqtab[count_cols].fillna(0).astype(int)
    seqtab.to_csv(args.fixed_seqtab, sep="\t", index=False)
    return 0


def row_value(row: list[str], header: list[str], name: str, fallback: int) -> str:
    if name in header:
        return row[header.index(name)]
    return row[fallback]


def passes_filters(row: list[str], header: list[str], min_reads: int, min_samples: int, include_failed: bool, exclude_bimeras: bool) -> bool:
    total_reads = int(row_value(row, header, "total_reads", 2))
    total_samples = int(row_value(row, header, "total_samples", 3))
    if total_reads < min_reads or total_samples < min_samples:
        return False
    if not include_failed:
        snv_filter = row_value(row, header, "snv_filter", -3)
        indel_filter = row_value(row, header, "indel_filter", -2)
        if snv_filter == "FAIL" or indel_filter == "FAIL":
            return False
    if exclude_bimeras:
        bimera = row_value(row, header, "bimera", -1).upper()
        if bimera == "TRUE":
            return False
    return True


def cmd_check_cigar_inputs(args: argparse.Namespace) -> int:
    counts: dict[str, dict[str, int]] = {}
    with open(args.table, newline="") as handle:
        reader = csv.reader(handle, delimiter="\t")
        header = next(reader)
        for row in reader:
            if not row:
                continue
            amplicon = row_value(row, header, "refid_3D7", 5)
            if amplicon == "NA":
                continue
            if amplicon not in counts:
                counts[amplicon] = {"input_asvs": 0, "passing_asvs": 0}
            counts[amplicon]["input_asvs"] += 1
            if passes_filters(row, header, args.min_reads, args.min_samples, args.include_failed, args.exclude_bimeras):
                counts[amplicon]["passing_asvs"] += 1

    with open(args.summary, "w", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(["amplicon", "input_asvs", "passing_asvs"])
        for amplicon in sorted(counts):
            writer.writerow([amplicon, counts[amplicon]["input_asvs"], counts[amplicon]["passing_asvs"]])

    passing_total = sum(item["passing_asvs"] for item in counts.values())
    if passing_total == 0:
        raise SystemExit("No ASVs pass CIGAR filters.")
    return 0


def read_tsv(path: str, limit: int = 12) -> tuple[list[str], list[list[str]]]:
    if not os.path.exists(path):
        return [], []
    with open(path, newline="") as handle:
        reader = csv.reader(handle, delimiter="\t")
        rows = list(reader)
    if not rows:
        return [], []
    return rows[0], rows[1:limit + 1]


def format_number(value: object) -> str:
    try:
        if isinstance(value, float) and not value.is_integer():
            return f"{value:,.1f}"
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return str(value)


def rel_download(path: str, label: str) -> str:
    if not path:
        return ""
    name = os.path.basename(path)
    href = quote("../run_dada2/" + name, safe="/._-")
    return f'<a class="download" href="{href}" download>{html.escape(label)}</a>'


def html_table(path: str, title: str, limit: int = 12, collapsed: bool = False) -> str:
    header, rows = read_tsv(path, limit=limit)
    if not header:
        return f"<h2>{html.escape(title)}</h2><p>Not available.</p>"
    head = "".join(f"<th>{html.escape(str(col))}</th>" for col in header)
    body = "".join(
        "<tr>" + "".join(f"<td>{html.escape(str(cell))}</td>" for cell in row) + "</tr>"
        for row in rows
    )
    table = f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"
    if collapsed:
        return f"<details><summary>{html.escape(title)}</summary>{table}</details>"
    return f"<h2>{html.escape(title)}</h2>{table}"


def variant_amplicon(name: str) -> str:
    text = str(name)
    for sep in [":", ","]:
        if sep in text:
            return text.split(sep, 1)[0]
    return text


def metric_card(label: str, value: object, note: str = "") -> str:
    note_html = f"<span>{html.escape(note)}</span>" if note else ""
    return f"<div class=\"card\"><b>{html.escape(format_number(value))}</b><em>{html.escape(label)}</em>{note_html}</div>"


def metric_value(value: object) -> str:
    return html.escape(format_number(value))


def bar_rows(rows: list[dict[str, object]], value_key: str, label_key: str, columns: list[tuple[str, str]]) -> str:
    if not rows:
        return "<p class=\"note\">Not available.</p>"
    max_value = max(float(row.get(value_key, 0) or 0) for row in rows) or 1.0
    header = "".join(f"<th>{html.escape(title)}</th>" for title, _ in columns)
    body = []
    for row in rows:
        width = 100.0 * float(row.get(value_key, 0) or 0) / max_value
        cells = []
        for title, key in columns:
            value = row.get(key, "")
            if key == label_key:
                cells.append(
                    f"<td><div class=\"bar-label\">{html.escape(str(value))}</div>"
                    f"<div class=\"bar\"><span style=\"width:{width:.1f}%\"></span></div></td>"
                )
            else:
                cells.append(f"<td>{metric_value(value)}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    return f"<table><thead><tr>{header}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def horizontal_chart(rows: list[dict[str, object]], label_key: str, value_key: str, title: str, max_items: int = 12) -> str:
    if not rows:
        return ""
    data = rows[:max_items]
    max_value = max(float(row.get(value_key, 0) or 0) for row in data) or 1.0
    chart_rows = []
    for row in data:
        label = html.escape(str(row.get(label_key, "")))
        value = float(row.get(value_key, 0) or 0)
        width = 100.0 * value / max_value
        chart_rows.append(
            f'<div class="chart-row"><span class="chart-label">{label}</span>'
            f'<span class="chart-track"><span style="width:{width:.1f}%"></span></span>'
            f'<span class="chart-value">{html.escape(format_number(value))}</span></div>'
        )
    return f'<div class="chart"><h3>{html.escape(title)}</h3>{"".join(chart_rows)}</div>'


def locus_recovery_chart(sample_rows: list[dict[str, object]]) -> str:
    if not sample_rows:
        return ""
    counts = Counter(int(row.get("loci_detected", 0) or 0) for row in sample_rows)
    rows = [{"loci": f"{i}/6", "samples": counts.get(i, 0)} for i in range(6, -1, -1)]
    return horizontal_chart(rows, "loci", "samples", "Sample locus recovery", max_items=7)


def downloads_panel(args: argparse.Namespace) -> str:
    links = [
        '<a class="download" href="../run_dada2/seqtab_iseq.tsv" download>seqtab_iseq.tsv</a>',
        rel_download(args.cigar, "seqtab_cigar.tsv"),
        rel_download(args.asv_to_cigar, "asv_to_cigar.tsv"),
        rel_download(args.mapped, "ASV_mapped_table.tsv"),
    ]
    return '<div class="downloads"><strong>Download tables</strong>' + "".join(links) + "</div>"


def summarize_cigar_matrix(path: str) -> tuple[dict[str, object], list[dict[str, object]], list[dict[str, object]]]:
    if not os.path.exists(path):
        return {}, [], []
    df = pd.read_csv(path, sep="\t")
    if df.empty or len(df.columns) < 2:
        return {}, [], []
    sample_col = df.columns[0]
    count_cols = [col for col in df.columns if col != sample_col]
    counts = df[count_cols].apply(pd.to_numeric, errors="coerce").fillna(0).astype(int)
    amp_by_col = {col: variant_amplicon(col) for col in count_cols}

    sample_rows = []
    for idx, row in counts.iterrows():
        positive = [col for col in count_cols if int(row[col]) > 0]
        sample_rows.append({
            "sample": df.loc[idx, sample_col],
            "total_reads": int(row.sum()),
            "loci_detected": len({amp_by_col[col] for col in positive}),
            "haplotypes_detected": len(positive),
        })
    sample_rows.sort(key=lambda item: int(item["total_reads"]), reverse=True)

    amp_rows = []
    for amplicon in sorted(set(amp_by_col.values())):
        cols = [col for col in count_cols if amp_by_col[col] == amplicon]
        sub = counts[cols]
        per_sample = sub.sum(axis=1)
        amp_rows.append({
            "amplicon": amplicon,
            "final_reads": int(per_sample.sum()),
            "samples_detected": int((per_sample >= 100).sum()),
            "haplotypes": int((sub.sum(axis=0) > 0).sum()),
            "median_reads_detected_samples": int(per_sample[per_sample > 0].median()) if (per_sample > 0).any() else 0,
        })
    amp_rows.sort(key=lambda item: int(item["final_reads"]), reverse=True)

    overview = {
        "samples": int(len(df)),
        "total_final_reads": int(counts.to_numpy().sum()),
        "samples_with_reads": sum(1 for row in sample_rows if int(row["total_reads"]) > 0),
        "median_loci_detected": float(pd.Series([row["loci_detected"] for row in sample_rows]).median()) if sample_rows else 0,
        "total_haplotypes": len(count_cols),
    }
    return overview, amp_rows, sample_rows


def summarize_mapped_asvs(path: str) -> tuple[dict[str, object], list[dict[str, object]]]:
    if not os.path.exists(path):
        return {}, []
    df = pd.read_csv(path, sep="\t")
    if df.empty or "refid_3D7" not in df.columns:
        return {}, []
    df = df[df["refid_3D7"].astype(str) != "NA"].copy()
    if df.empty:
        return {}, []
    df["total_reads"] = pd.to_numeric(df.get("total_reads", 0), errors="coerce").fillna(0).astype(int)
    df["total_samples"] = pd.to_numeric(df.get("total_samples", 0), errors="coerce").fillna(0).astype(int)
    rows = []
    for amplicon, group in df.groupby("refid_3D7"):
        pass_mask = pd.Series([True] * len(group), index=group.index)
        if "snv_filter" in group:
            pass_mask &= group["snv_filter"].astype(str).str.upper().eq("PASS")
        if "indel_filter" in group:
            pass_mask &= group["indel_filter"].astype(str).str.upper().eq("PASS")
        if "bimera" in group:
            pass_mask &= ~group["bimera"].astype(str).str.upper().eq("TRUE")
        rows.append({
            "amplicon": amplicon,
            "mapped_asvs": int(len(group)),
            "filter_pass_asvs": int(pass_mask.sum()),
            "mapped_reads": int(group["total_reads"].sum()),
            "max_samples_per_asv": int(group["total_samples"].max()),
        })
    rows.sort(key=lambda item: int(item["mapped_reads"]), reverse=True)
    overview = {
        "mapped_asvs": int(len(df)),
        "mapped_reads": int(df["total_reads"].sum()),
        "amplicons_with_asvs": int(df["refid_3D7"].nunique()),
    }
    return overview, rows


def summarize_asv_to_cigar(path: str) -> list[dict[str, object]]:
    if not os.path.exists(path):
        return []
    df = pd.read_csv(path, sep="\t")
    if df.empty or "Amplicon" not in df.columns:
        return []
    rows = []
    for amplicon, group in df.groupby("Amplicon"):
        rows.append({
            "amplicon": amplicon,
            "asvs_with_cigar": int(len(group)),
            "unique_cigars": int(group["CIGAR"].nunique()) if "CIGAR" in group else "",
        })
    rows.sort(key=lambda item: int(item["asvs_with_cigar"]), reverse=True)
    return rows


def read_tsv_dicts(path: str) -> list[dict[str, str]]:
    if not os.path.exists(path):
        return []
    with open(path, newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def compact_number(value: object) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if abs(number) >= 1_000_000:
        return f"{number / 1_000_000:.1f}M"
    if abs(number) >= 1_000:
        return f"{number:,.0f}"
    if number.is_integer():
        return f"{int(number):,}"
    return f"{number:,.1f}"


def compact_table_cell(value: object) -> str:
    text = str(value)
    numeric_text = text.replace(",", "")
    if numeric_text.replace(".", "", 1).lstrip("-").isdigit():
        return compact_number(numeric_text)
    return text


def is_optional_md5_notice(row: dict[str, str]) -> bool:
    return ".md5 sidecar" in row.get("message", "").lower()


def report_metric_card(label: str, value: object, note: str = "", tone: str = "") -> str:
    tone_class = f" {html.escape(tone)}" if tone else ""
    note_html = f"<span>{html.escape(note)}</span>" if note else ""
    return (
        f'<article class="metric{tone_class}">'
        "<i></i>"
        f"<span>{html.escape(label)}</span>"
        f"<b>{html.escape(str(value))}</b>"
        f"{note_html}"
        "</article>"
    )


def report_output_panel(args: argparse.Namespace) -> str:
    links = [
        '<a class="download" href="../run_dada2/seqtab_iseq.tsv" download>ASV count table</a>',
        rel_download(args.cigar, "CIGAR count table"),
        rel_download(args.asv_to_cigar, "ASV to CIGAR map"),
        rel_download(args.mapped, "Mapped ASV table"),
    ]
    return (
        '<article class="output-callout" id="output-tables">'
        "<h2>Output tables</h2>"
        "<p>Download the full output tables. Technical tables below show previews only.</p>"
        f'<div class="download-row">{"".join(link for link in links if link)}</div>'
        "</article>"
    )


def svg_bar_chart(
    rows: list[dict[str, object]],
    label_key: str,
    value_key: str,
    title: str,
    subtitle: str = "",
    color: str = "#2f8fd3",
    max_items: int = 12,
    wide: bool = False,
) -> str:
    data = rows[:max_items]
    if not data:
        return '<div class="chart"><h3>No data available</h3></div>'
    max_value = max(float(row.get(value_key, 0) or 0) for row in data) or 1.0
    chart_rows = []
    for row in data:
        label = str(row.get(label_key, ""))
        value = float(row.get(value_key, 0) or 0)
        width_pct = 100 * value / max_value
        chart_rows.append(
            '<div class="chart-row">'
            f'<span class="chart-label" title="{html.escape(label)}">{html.escape(label)}</span>'
            '<span class="chart-track">'
            f'<span style="width:{width_pct:.1f}%"></span>'
            "</span>"
            f'<span class="chart-value">{html.escape(compact_number(value))}</span>'
            "</div>"
        )
    classes = "chart chart-wide" if wide else "chart"
    subtitle_html = f'<p class="note">{html.escape(subtitle)}</p>' if subtitle else ""
    return (
        f'<div class="{classes}">'
        f"<h3>{html.escape(title)}</h3>"
        f"{subtitle_html}"
        f'{"".join(chart_rows)}'
        "</div>"
    )


def svg_funnel(items: list[tuple[str, int, str]]) -> str:
    max_value = max((value for _, value, _ in items), default=1) or 1
    steps = []
    previous_value = None
    previous_label = ""
    for label, value, _color in items:
        width = max(2, 100 * value / max_value)
        if previous_value is None:
            note = "baseline"
        elif previous_value:
            note = f"{value / previous_value:.0%} of {previous_label}"
        else:
            note = f"0% of {previous_label}"
        previous_value = value
        previous_label = label
        steps.append(
            '<div class="chart-row funnel-row">'
            f'<span class="chart-label" title="{html.escape(label)}">{html.escape(label)}</span>'
            '<span class="chart-track">'
            f'<span style="width:{width:.1f}%"></span>'
            "</span>"
            f'<span class="chart-value">{html.escape(compact_number(value))}<small>{html.escape(note)}</small></span>'
            "</div>"
        )
    return (
        "<h2>ASV processing funnel</h2>"
        '<p class="note">How many sequence features survive each major step.</p>'
        '<div class="chart funnel-card">'
        f'{"".join(steps)}'
        "</div>"
    )


def report_table(
    rows: list[dict[str, object]],
    columns: list[tuple[str, str]],
    title: str,
    subtitle: str = "",
    bar_key: str = "",
) -> str:
    if not rows:
        return f"<h2>{html.escape(title)}</h2><p class=\"note\">No data available.</p>"
    header = "".join(f"<th>{html.escape(label)}</th>" for label, _ in columns)
    max_value = max((float(row.get(bar_key, 0) or 0) for row in rows), default=0) or 1.0
    body = []
    for row in rows:
        cells = []
        for index, (_, key) in enumerate(columns):
            value = row.get(key, "")
            if index == 0 and bar_key:
                bar_value = float(row.get(bar_key, 0) or 0)
                width = 100 * bar_value / max_value
                cell = (
                    f'<div class="bar-label">{html.escape(str(value))}</div>'
                    '<div class="bar">'
                    f'<span style="width:{width:.1f}%"></span>'
                    "</div>"
                )
            else:
                if isinstance(value, (int, float)):
                    value = compact_number(value)
                cell = html.escape(str(value))
            cells.append(f"<td>{cell}</td>")
        body.append(f"<tr>{''.join(cells)}</tr>")
    subtitle_html = f'<p class="note">{html.escape(subtitle)}</p>' if subtitle else ""
    return (
        f"<h2>{html.escape(title)}</h2>"
        f"{subtitle_html}"
        f'<table><thead><tr>{header}</tr></thead><tbody>{"".join(body)}</tbody></table>'
    )


def report_details(path: str, title: str, limit: int = 12, note: str = "") -> str:
    header, rows = read_tsv(path, limit=limit)
    if not header:
        return ""
    head = "".join(f"<th>{html.escape(str(col))}</th>" for col in header)
    status_idx = header.index("status") if "status" in header else -1
    message_idx = header.index("message") if "message" in header else -1
    body_rows = []
    for row in rows:
        cells = list(row)
        if status_idx >= 0 and message_idx >= 0 and ".md5 sidecar" in str(cells[message_idx]).lower():
            cells[status_idx] = "INFO"
        body_rows.append(
            "<tr>" + "".join(f"<td>{html.escape(compact_table_cell(cell))}</td>" for cell in cells) + "</tr>"
        )
    body = "".join(body_rows)
    note_html = f'<p class="detail-note">{note}</p>' if note else ""
    return (
        f"<details><summary>{html.escape(title)}</summary>"
        f"{note_html}"
        f'<div class="technical"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'
        "</details>"
    )


def cmd_make_report(args: argparse.Namespace) -> int:
    cigar_overview, cigar_amplicons, sample_depth = summarize_cigar_matrix(args.cigar)
    mapped_overview, mapped_amplicons = summarize_mapped_asvs(args.mapped)
    asv_cigar_rows = summarize_asv_to_cigar(args.asv_to_cigar)
    preflight_rows = read_tsv_dicts(args.preflight)
    status_counts = Counter(row.get("status", "") for row in preflight_rows)
    optional_md5_notices = sum(1 for row in preflight_rows if is_optional_md5_notice(row))
    filter_pass_total = sum(int(row.get("filter_pass_asvs", 0) or 0) for row in mapped_amplicons)
    locus_counts = Counter(int(row.get("loci_detected", 0) or 0) for row in sample_depth)
    locus_recovery_rows = [
        {"bucket": f"{count}/6", "samples": locus_counts.get(count, 0)}
        for count in range(6, -1, -1)
    ]
    samples = cigar_overview.get("samples", "NA")
    median_loci = cigar_overview.get("median_loci_detected", "NA")
    total_final_reads = cigar_overview.get("total_final_reads", "NA")
    samples_with_reads = cigar_overview.get("samples_with_reads", "NA")
    mapped_asvs = mapped_overview.get("mapped_asvs", "NA")
    amplicons_with_asvs = mapped_overview.get("amplicons_with_asvs", "NA")
    total_haplotypes = cigar_overview.get("total_haplotypes", "NA")
    unique_cigars = sum(int(row.get("unique_cigars", 0) or 0) for row in asv_cigar_rows)
    error_count = status_counts.get("ERROR", 0)
    warning_count = sum(
        1
        for row in preflight_rows
        if row.get("status", "") == "WARN" and not is_optional_md5_notice(row)
    )
    if error_count:
        run_status = "Needs review"
    elif warning_count:
        run_status = "Passed with warnings"
    else:
        run_status = "Passed"

    def safe_int(value: object) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    cards = [
        report_metric_card("Samples", compact_number(samples), "final CIGAR table", "blue"),
        report_metric_card("Final reads", compact_number(total_final_reads), "post-CIGAR reads", "green"),
        report_metric_card("Median loci detected", f"{format_number(median_loci)}/6", "per sample", "gold"),
        report_metric_card("ASVs mapped to loci", compact_number(mapped_asvs), "amplicon-mapped variants", "blue"),
        report_metric_card("CIGAR haplotypes", compact_number(total_haplotypes), f"{compact_number(unique_cigars)} unique CIGAR strings", "pink"),
    ]
    html_text = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Run Summary</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 32px; color: #20211f; background: #f6f4ed; max-width: 1280px; line-height: 1.45; }}
    h1 {{ margin: 0; font-size: 34px; letter-spacing: -0.02em; }}
    h2 {{ margin-top: 34px; border-top: 1px solid #dcd8ce; padding-top: 22px; font-size: 24px; letter-spacing: -0.01em; }}
    h3 {{ margin: 0 0 12px 0; font-size: 16px; }}
    .report-header {{ display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 24px; align-items: end; border-bottom: 1px solid #dcd8ce; padding: 22px 0 24px; }}
    .lede {{ max-width: 760px; margin: 12px 0 0; color: #626761; }}
    .status-card {{ min-width: 300px; border: 1px solid #dcd8ce; background: #fffdf8; border-radius: 10px; padding: 16px 18px; }}
    .status-card span, .metric span {{ display: block; color: #626761; font-size: 12px; font-weight: 800; text-transform: uppercase; }}
    .status-card strong {{ display: block; margin-top: 8px; font-size: 19px; }}
    .status-card small {{ display: block; margin-top: 6px; }}
    .metrics {{ display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 14px; margin-top: 22px; }}
    .metric {{ min-height: 132px; border: 1px solid #dcd8ce; background: #fffdf8; border-radius: 8px; padding: 16px; }}
    .metric i {{ display: block; width: 24px; height: 2px; border-radius: 999px; background: #d8d6cf; margin-bottom: 18px; }}
    .metric.blue i {{ background: #d8e1e8; }} .metric.green i {{ background: #d8e7dd; }} .metric.gold i {{ background: #e6dcc8; }} .metric.pink i {{ background: #ead9e2; }}
    .metric b {{ display: block; font-size: 28px; line-height: 1.05; margin-top: 6px; }}
    .metric span + b {{ margin-top: 6px; }}
    .metric b + span {{ color: #626761; font-size: 13px; font-weight: 400; text-transform: none; margin-top: 8px; }}
    .output-callout {{ border: 1px solid #dcd8ce; background: #fffdf8; border-radius: 10px; padding: 16px; margin: 22px 0 0; }}
    .output-callout h2 {{ border: 0; padding: 0; margin: 0 0 6px; font-size: 18px; }}
    .output-callout p {{ margin: 0; color: #626761; }}
    .download-row {{ display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-top: 14px; }}
    table {{ border-collapse: collapse; width: 100%; margin-top: 10px; font-size: 14px; background: #fffdf8; }}
    th, td {{ border: 1px solid #dcd8ce; padding: 7px 9px; text-align: left; vertical-align: top; }}
    th {{ background: #eeece4; color: #51564f; font-size: 12px; text-transform: uppercase; }}
    td:not(:first-child), th:not(:first-child) {{ text-align: right; font-variant-numeric: tabular-nums; }}
    .note {{ color: #626761; margin-top: 6px; }}
    .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin-top: 20px; }}
    .card {{ border: 1px solid #dcd8ce; background: #fffdf8; border-radius: 6px; padding: 12px; }}
    .card b {{ display: block; font-size: 24px; color: #20211f; }}
    .card em {{ display: block; font-style: normal; font-weight: 700; margin-top: 2px; }}
    .card span {{ display: block; color: #626761; font-size: 12px; margin-top: 4px; }}
    .bar {{ height: 8px; background: #ebe8df; border-radius: 999px; margin-top: 5px; overflow: hidden; }}
    .bar span {{ display: block; height: 100%; background: #343832; }}
    .bar-label {{ font-weight: 700; color: #20211f; }}
    .download {{ display: inline-block; border: 1px solid #d2cec3; color: #20211f; background: #fffdf8; border-radius: 999px; padding: 6px 10px; text-decoration: none; font-size: 13px; font-weight: 700; }}
    .viz-grid {{ display: grid; grid-template-columns: repeat(2, minmax(320px, 1fr)); gap: 16px; margin-top: 22px; }}
    .chart {{ border: 1px solid #dcd8ce; border-radius: 6px; padding: 14px; background: #fffdf8; }}
    .chart-wide {{ grid-column: 1 / -1; }}
    .chart-row {{ display: grid; grid-template-columns: 112px 1fr 82px; gap: 10px; align-items: center; margin: 8px 0; }}
    .chart-label {{ font-weight: 700; color: #20211f; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    .chart-track {{ display: block; height: 11px; background: #ebe8df; border-radius: 999px; overflow: hidden; }}
    .chart-track span {{ display: block; height: 100%; background: #343832; }}
    .chart-value {{ text-align: right; font-variant-numeric: tabular-nums; color: #3b403a; }}
    .chart-value small {{ display: block; color: #777b72; font-size: 10px; }}
    .funnel-row {{ grid-template-columns: 136px 1fr 82px; }}
    .funnel-row .chart-label {{ white-space: normal; line-height: 1.15; }}
    .funnel-row .chart-track span {{ background: #222522; }}
    .funnel-card {{ margin-top: 0; }}
    .funnel-card .chart-row {{ grid-template-columns: 190px 1fr 150px; max-width: 980px; }}
    details {{ border-top: 1px solid #dcd8ce; margin-top: 18px; padding-top: 12px; }}
    summary {{ cursor: pointer; font-weight: 700; color: #20211f; font-size: 18px; }}
    .technical {{ overflow: auto; max-height: 360px; }}
    .detail-note {{ color: #626761; margin-top: 12px; }}
    .details-note {{ color: #626761; margin-top: 30px; }}
    .footer-note {{ color: #626761; margin-top: 28px; font-size: 12px; }}
    @media (max-width: 900px) {{ .report-header {{ grid-template-columns: 1fr; }} .status-card {{ min-width: 0; }} .metrics {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }} .viz-grid {{ grid-template-columns: 1fr; }} }}
    @media (max-width: 720px) {{ body {{ margin: 18px; }} .chart-row {{ grid-template-columns: 96px 1fr 74px; }} }}
    @media print {{
      body {{ background: #fff; color: #111; margin: 0.35in; }}
      .download {{ color: #111; }}
      .chart, .card, table, details {{ break-inside: avoid; page-break-inside: avoid; }}
    }}
  </style>
</head>
<body>
  <header class="report-header">
    <div>
      <h1>Run summary</h1>
      <p class="lede">A compact overview of SIMPLseq read depth, locus recovery, ASV filtering, and CIGAR conversion for this run.</p>
    </div>
    <aside class="status-card"><span>Run status</span><strong>{html.escape(run_status)}</strong><small>{html.escape(compact_number(samples))} samples processed &middot; {error_count} errors &middot; {warning_count} warnings</small></aside>
  </header>
  <section class="metrics">{''.join(cards)}</section>
  {report_output_panel(args)}
  <h2>Visual Summary</h2>
  <div class="viz-grid">
    {svg_bar_chart(cigar_amplicons, "amplicon", "final_reads", "Final reads by amplicon")}
    {svg_bar_chart(mapped_amplicons, "amplicon", "filter_pass_asvs", "Filter-pass ASVs by amplicon")}
    {svg_bar_chart(locus_recovery_rows, "bucket", "samples", "Sample locus recovery")}
    {svg_bar_chart(asv_cigar_rows, "amplicon", "unique_cigars", "Unique CIGAR strings")}
  </div>
  {svg_funnel([("Mapped ASVs", safe_int(mapped_asvs), "#343832"), ("Filter-pass ASVs", filter_pass_total, "#343832"), ("CIGAR haplotypes", safe_int(total_haplotypes), "#343832")])}
  {report_table(cigar_amplicons, [("Amplicon", "amplicon"), ("Final reads", "final_reads"), ("Samples >=100 reads", "samples_detected"), ("Haplotypes", "haplotypes"), ("Median reads in detected samples", "median_reads_detected_samples")], "Final Read Depth by Amplicon", "Final CIGAR/haplotype reads grouped by SIMPLseq target. Samples detected uses a 100-read threshold, matching the paper's locus-detection summaries.", "final_reads")}
  {report_table(mapped_amplicons, [("Amplicon", "amplicon"), ("Mapped reads", "mapped_reads"), ("Mapped ASVs", "mapped_asvs"), ("Filter-pass ASVs", "filter_pass_asvs"), ("Max samples per ASV", "max_samples_per_asv")], "Mapped ASVs by Amplicon", "", "mapped_reads")}
  {report_table(sample_depth, [("Sample", "sample"), ("Final reads", "total_reads"), ("Loci detected", "loci_detected"), ("Haplotypes detected", "haplotypes_detected")], "Sample Read Depth and Locus Recovery", "", "total_reads")}
  {report_table(asv_cigar_rows, [("Amplicon", "amplicon"), ("ASVs with CIGAR", "asvs_with_cigar"), ("Unique CIGAR strings", "unique_cigars")], "ASV to CIGAR Conversion", "", "asvs_with_cigar")}
  <p class="details-note">Detailed checks and table previews are collapsed by default. Download full tables above.</p>
  {report_details(args.preflight, "Preflight", limit=40)}
  {report_details(args.geometry, "Amplicon Reference Check")}
  {report_details(args.cigar_summary, "CIGAR Input Check")}
  {report_details(args.mapped, "Mapped ASVs", limit=20, note='Preview only. Use the Download tables buttons above for the full table.')}
  {report_details(args.cigar, "CIGAR Count Matrix", limit=6, note='Preview only. Use the Download tables buttons above for the full table.')}
  <p class="footer-note">Generated by the Nextflow SIMPLseq workflow. {error_count} errors, {warning_count} warnings, {optional_md5_notices} optional checksum notices.</p>
</body>
</html>
"""
    with open(args.out, "w") as handle:
        handle.write(html_text)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("preflight")
    p.add_argument("--samples", required=True)
    p.add_argument("--amplicons", required=True)
    p.add_argument("--report", required=True)
    p.add_argument("--geometry", required=True)
    p.add_argument("--barcode", required=True)
    p.add_argument("--read-length", type=int, default=150)
    p.add_argument("--inline-barcodes-enabled", default="false")
    p.add_argument("--sentinel-locus", default="KELT")
    p.add_argument("--samples-root", default="")
    p.set_defaults(func=cmd_preflight)

    p = sub.add_parser("write-meta")
    p.add_argument("--samples", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--samples-root", default="")
    p.set_defaults(func=cmd_write_meta)

    p = sub.add_parser("write-pipeline-json")
    p.add_argument("--meta", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--pipeline-class", default="parasite")
    p.add_argument("--max-ee", required=True)
    p.add_argument("--trim-right", required=True)
    p.add_argument("--min-len", required=True)
    p.add_argument("--trunc-q", required=True)
    p.add_argument("--max-consist", required=True)
    p.add_argument("--omega-a", required=True)
    p.add_argument("--just-concatenate", required=True)
    p.add_argument("--save-rdata", default="")
    p.add_argument("--dada2-randomize", default="")
    p.add_argument("--dada2-multithread", default="")
    p.add_argument("--dada2-seed", default="")
    p.add_argument("--primers-fwd", required=True)
    p.add_argument("--primers-rev", required=True)
    p.add_argument("--overlap-primers-fwd", required=True)
    p.add_argument("--overlap-primers-rev", required=True)
    p.set_defaults(func=cmd_write_pipeline_json)

    p = sub.add_parser("prepare-stage2")
    p.add_argument("--seqtab", required=True)
    p.add_argument("--op-bimera", required=True)
    p.add_argument("--nop-bimera", required=True)
    p.add_argument("--corrected-asv", required=True)
    p.add_argument("--strict-seqtab", required=True)
    p.add_argument("--strict-bimera", required=True)
    p.add_argument("--strict-min-asv-length", type=int, default=100)
    p.set_defaults(func=cmd_prepare_stage2)

    p = sub.add_parser("prepare-stage3")
    p.add_argument("--mapped", required=True)
    p.add_argument("--seqtab", required=True)
    p.add_argument("--filtered-mapped", required=True)
    p.add_argument("--fixed-seqtab", required=True)
    p.set_defaults(func=cmd_prepare_stage3)

    p = sub.add_parser("check-cigar-inputs")
    p.add_argument("--table", required=True)
    p.add_argument("--summary", required=True)
    p.add_argument("--min-reads", type=int, default=100)
    p.add_argument("--min-samples", type=int, default=2)
    p.add_argument("--include-failed", action="store_true")
    p.add_argument("--exclude-bimeras", action="store_true")
    p.set_defaults(func=cmd_check_cigar_inputs)

    p = sub.add_parser("make-report")
    p.add_argument("--project-name", default="SIMPLseq")
    p.add_argument("--preflight", required=True)
    p.add_argument("--geometry", required=True)
    p.add_argument("--cigar-summary", required=True)
    p.add_argument("--mapped", required=True)
    p.add_argument("--asv-to-cigar", required=True)
    p.add_argument("--cigar", required=True)
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd_make_report)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
