from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from simplseq.resources import resource_checks
from simplseq.runner import run_nextflow


class RunnerTests(unittest.TestCase):
    def test_reproducible_dry_run_records_effective_parameters(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            samples = root / "samples.csv"
            outdir = root / "results"
            samples.write_text("sample_id,fastq_1,fastq_2\n", encoding="utf-8")

            result = run_nextflow(samples, outdir, root=Path.cwd(), profile="reproducible", dry_run=True)
            parameters = json.loads((outdir / "parameters.json").read_text(encoding="utf-8"))

        self.assertEqual(result.returncode, 0)
        self.assertIn("reproducible", result.command)
        self.assertEqual(parameters["nextflow_profile"], "reproducible")
        self.assertEqual(parameters["dada2_multithread"], "0")
        self.assertEqual(parameters["dada2_seed"], "1")
        self.assertEqual(parameters["analysis_parameters"]["dada2_multithread"], "0")
        self.assertEqual(parameters["analysis_parameters"]["dada2_seed"], "1")

    def test_resource_checks_do_not_create_output_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            outdir = Path(tmp) / "not-created"

            checks = resource_checks(None, outdir)

            self.assertFalse(outdir.exists())
            self.assertTrue(any(check["name"] == "Output disk" for check in checks))


if __name__ == "__main__":
    unittest.main()
