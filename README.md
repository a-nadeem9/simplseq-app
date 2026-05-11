![SIMPLseq logo](assets/simplseq-logo.png)

# SIMPLseq App

SIMPLseq App is a browser-based app for running the SIMPLseq malaria
amplicon workflow.

Start it with:

```bash
simplseq run
```

This opens a browser interface where the user chooses FASTQ files,
reviews detected pairs, creates the sample sheet, starts the run, watches
progress, and downloads results.

Behind the GUI, SIMPLseq App uses a Linux Conda/Mamba runtime and a local
Nextflow pipeline.

## Direction

SIMPLseq App is GUI-first and CLI-backed.

```text
simplseq run
  -> browser GUI
      -> SIMPLseq backend runner
          -> local Nextflow pipeline
              -> Conda/Mamba environment
                  -> R / DADA2 / Python / MUSCLE / SIMPLseq scripts
                      -> output tables and report
```

The GUI owns the user experience. The backend CLI owns execution, testing,
debugging, automation, support, and developer mode. Both use the same
Nextflow + Conda runtime.

## Attribution

SIMPLseq was developed and published by Schwabl, Amaya-Romero, Kelley, and
colleagues from the Neafsey lab and collaborators:

> Schwabl P, Amaya-Romero JE, Kelley KA, et al. SIMPLseq: a high-sensitivity
> Plasmodium falciparum genotyping and PCR contamination tracking tool.
> Malaria Journal 25, 131 (2026). https://doi.org/10.1186/s12936-026-05796-1

The underlying malaria amplicon analysis scripts and ASV-to-CIGAR workflow are
derived from the Broad Institute's public malaria amplicon pipeline:

> Broad Institute. malaria-amplicon-pipeline.
> https://github.com/broadinstitute/malaria-amplicon-pipeline

This repository packages the workflow for local use with a browser GUI,
Nextflow, and a Conda/Mamba runtime. The SIMPLseq assay, original malaria
amplicon methods, and upstream pipeline components belong to their original
authors.

## Install

On Linux/WSL:

```bash
curl -fsSL https://github.com/a-nadeem9/simplseq-app/releases/download/v0.1.0-dev/install-simplseq.sh | bash
simplseq run
```

The installer downloads the app files, creates a managed Micromamba runtime
under `~/.local/share/simplseq`, and installs a `simplseq` launcher into
`~/.local/bin`. Users do not need to activate an environment manually; the
launcher sets the project root, Python path, and runtime path internally.

If `simplseq` is not found immediately after installation, open a new shell or
run:

```bash
source ~/.bashrc
```

On Windows, run through WSL. Double-click launchers may be provided later as
convenience wrappers only; they are not the main install path.

## Normal Use

Start the app:

```bash
simplseq run
```

Then use the browser GUI to:

1. Choose the FASTQ folder.
2. Review detected pairs.
3. Write the sample sheet.
4. Choose an output folder.
5. Start the SIMPLseq run.
6. Watch clean progress stages.
7. Download results.

FASTQ files are read from disk by folder path. The app intentionally does not
upload FASTQ files through the browser, because real runs can contain many GB of
compressed sequencing data.

The app opens locally, usually at:

```text
http://localhost:8501
```

## Input Layout

Put paired FASTQ files in a `data/` folder:

```text
project/
+-- data/
|   +-- mpg_L34382_Amplicon-Pool-109-Toro142Mar2023Rep1_R1.fastq.gz
|   +-- mpg_L34382_Amplicon-Pool-109-Toro142Mar2023Rep1_R2.fastq.gz
|   +-- mpg_L34382_Amplicon-Pool-110-Toro142Mar2023Rep2_R1.fastq.gz
|   +-- mpg_L34382_Amplicon-Pool-110-Toro142Mar2023Rep2_R2.fastq.gz
```

The sample sheet parser understands longitudinal sample names and technical
replicates such as `Toro142Mar2023Rep1`.

## Direct CLI Mode

For CLI users:

```bash
simplseq run-headless --samples samples.csv --out results
```

Backend/developer commands:

```bash
simplseq scan --fastq-dir data --out samples.csv
simplseq check --samples samples.csv
simplseq run-headless --samples samples.csv --out results
simplseq results --out results
```

These are useful for testing, debugging, automation, support, and developer
mode. They are not the normal wet-lab user path.

## Outputs

Key result files:

```text
results/reports/run_summary.html
results/run_dada2/seqtab_iseq.tsv
results/run_dada2/ASV_mapped_table.tsv
results/run_dada2/asv_to_cigar.tsv
results/run_dada2/seqtab_cigar.tsv
```

Run tracking and reproducibility files:

```text
results/progress.jsonl
results/run_state.json
results/technical_log.txt
results/provenance.json
results/parameters.json
results/versions.txt
results/input_fastq_md5s.tsv
```

## Scientific Parameters

The GUI should not quietly change scientific behavior. Panel/reference files,
primer definitions, DADA2 parameters, filter thresholds, masking rules, CIGAR
conversion behavior, minimum read/sample thresholds, bimera handling, and
reference choices are recorded in the run outputs.

If the GUI exposes these later, they should be labelled as analysis parameters.

## License

License information will be finalized before public release. The upstream
malaria amplicon pipeline is distributed under GPL-3.0, so public release of
this repository must preserve the relevant upstream license notices.
