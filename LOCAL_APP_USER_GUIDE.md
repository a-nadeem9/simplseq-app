# SIMPLseq-nf App User Guide

SIMPLseq-nf App is started with one command:

```bash
simplseq run
```

This opens the browser app. The app lets the user choose FASTQs, review
detected pairs, create the sample sheet, start the run, watch progress, and
download results.

## Runtime Model

Version 0.1-dev uses a managed Linux runtime under the user's home directory:

```text
~/.local/share/simplseq/envs/v0.1.0-dev
```

Users do not need to activate an environment manually. The `simplseq` launcher
sets `SIMPLSEQ_PROJECT_ROOT`, `PYTHONPATH`, and the managed runtime path
internally.

## First-Time Setup

From Linux or WSL:

```bash
curl -fsSL https://github.com/a-nadeem9/simplseq-nf-app/releases/download/v0.1.0-dev/install-simplseq.sh | bash
```

After setup, this should work from any new WSL/Linux shell:

```bash
simplseq run
```

If the current shell does not know `simplseq` yet, open a new shell or run:

```bash
source ~/.bashrc
```

On Windows, use WSL. Double-click launchers may be added later as convenience
wrappers, but the tested product path is the `simplseq run` command in WSL.

## Normal Use

1. Put paired FASTQ files in `data/`.
2. Start the app:

```bash
simplseq run
```

3. Choose the FASTQ folder.
4. Write the sample sheet.
5. Choose an output folder, usually `results`.
6. Start the run.
7. Watch the progress stages.
8. Download or open outputs from the Results tab.

FASTQ files are not uploaded through the browser. The app scans a folder path
on disk, which is the safer model for large sequencing runs.

## Backend Commands

These are mainly for testing, debugging, automation, support, and developer
work:

```bash
simplseq scan --fastq-dir data --out samples.csv
simplseq check --samples samples.csv
simplseq run-headless --samples samples.csv --out results
simplseq status --out results
simplseq results --out results
```

## Outputs

Main result files:

```text
results/reports/run_summary.html
results/run_dada2/seqtab_iseq.tsv
results/run_dada2/ASV_mapped_table.tsv
results/run_dada2/asv_to_cigar.tsv
results/run_dada2/seqtab_cigar.tsv
```

Run tracking files:

```text
results/progress.jsonl
results/run_state.json
results/technical_log.txt
results/provenance.json
results/parameters.json
results/versions.txt
results/input_fastq_md5s.tsv
```

## Current Limits

- Windows runs through WSL.
- Very large datasets may need more RAM than a laptop can provide.
- Scientific parameters are pinned and recorded; GUI controls should not change
  them silently.
