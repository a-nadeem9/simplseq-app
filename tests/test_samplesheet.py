from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from simplseq.samplesheet import parse_fastq_name, scan_fastqs, write_samples_csv


def touch_pair(root: Path, prefix: str, r1_suffix: str = "_R1_001.fastq.gz", r2_suffix: str = "_R2_001.fastq.gz") -> None:
    (root / f"{prefix}{r1_suffix}").write_bytes(b"r1")
    (root / f"{prefix}{r2_suffix}").write_bytes(b"r2")


class SampleSheetTests(unittest.TestCase):
    def test_parse_fastq_name_handles_common_metadata_orders(self) -> None:
        cases = [
            (
                "mpg_L34382_Amplicon-Pool-077-Toro113Feb2022Rep2_R1_001.fastq.gz",
                {
                    "sample_id": "Toro113Feb2022Rep2",
                    "participant_id": "Toro113",
                    "collection_date": "2022-02",
                    "replicate": "Rep2",
                },
            ),
            (
                "Toro113_Rep2_Feb2022_R1_001.fastq.gz",
                {
                    "sample_id": "Toro113_Rep2_Feb2022",
                    "participant_id": "Toro113",
                    "collection_date": "2022-02",
                    "replicate": "Rep2",
                },
            ),
            (
                "2022Feb_Toro113_Rep2_R1.fastq.gz",
                {
                    "sample_id": "2022Feb_Toro113_Rep2",
                    "participant_id": "Toro113",
                    "collection_date": "2022-02",
                    "replicate": "Rep2",
                },
            ),
            (
                "Toro113-2022-02-15-Rep2_R1.fq.gz",
                {
                    "sample_id": "Toro113-2022-02-15-Rep2",
                    "participant_id": "Toro113",
                    "collection_date": "2022-02-15",
                    "replicate": "Rep2",
                },
            ),
            (
                "SampleAlpha_Run7_R1_001.fastq.gz",
                {
                    "sample_id": "SampleAlpha_Run7",
                    "participant_id": "",
                    "collection_date": "",
                    "replicate": "",
                },
            ),
        ]
        for filename, expected in cases:
            with self.subTest(filename=filename):
                self.assertEqual(parse_fastq_name(filename), expected)

    def test_parse_fastq_name_can_keep_amplicon_pool_when_requested(self) -> None:
        parsed = parse_fastq_name(
            "mpg_L34382_Amplicon-Pool-077-Toro113Feb2022Rep2_R1_001.fastq.gz",
            include_pool_in_sample_id=True,
        )
        self.assertEqual(parsed["sample_id"], "Toro113Feb2022Rep2_Pool077")
        self.assertEqual(parsed["participant_id"], "Toro113")

    def test_scan_fastqs_pairs_suffix_variants_and_marks_controls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            touch_pair(root, "Toro113_Rep2_Feb2022")
            touch_pair(root, "NTC_Feb2022_Rep1", "_R1.fastq.gz", "_R2.fastq.gz")
            (root / "orphan_R2_001.fastq.gz").write_bytes(b"orphan")
            (root / "Toro114_Rep1_Feb2022_R1_001.fastq.gz").write_bytes(b"missing mate")
            (root / "Toro113_Rep2_Feb2022_R1_001.fastq.gz.md5").write_text("checksum\n", encoding="utf-8")

            scan = scan_fastqs(root)

        self.assertEqual([pair.sample_id for pair in scan.pairs], ["NTC_Feb2022_Rep1", "Toro113_Rep2_Feb2022"])
        self.assertEqual(scan.pairs[0].sample_type, "negative")
        self.assertEqual(scan.pairs[1].sample_type, "sample")
        self.assertEqual(scan.missing_r2, ["Toro114_Rep1_Feb2022_R1_001.fastq.gz"])
        self.assertEqual(scan.orphan_r2, ["orphan_R2_001.fastq.gz"])
        self.assertEqual(scan.md5_files, 1)
        self.assertEqual(scan.duplicate_sample_ids, [])

    def test_write_samples_csv_uses_absolute_paths_when_requested(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            touch_pair(root, "Toro113_Rep2_Feb2022")
            output = root / "samples.csv"

            written, duplicates = write_samples_csv(root, output, absolute=True)

            with output.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))

        self.assertEqual(written, 1)
        self.assertEqual(duplicates, [])
        self.assertEqual(rows[0]["sample_id"], "Toro113_Rep2_Feb2022")
        self.assertTrue(Path(rows[0]["fastq_1"]).is_absolute())
        self.assertTrue(Path(rows[0]["fastq_2"]).is_absolute())
        self.assertEqual(rows[0]["participant_id"], "Toro113")
        self.assertEqual(rows[0]["collection_date"], "2022-02")
        self.assertEqual(rows[0]["replicate"], "Rep2")


if __name__ == "__main__":
    unittest.main()
