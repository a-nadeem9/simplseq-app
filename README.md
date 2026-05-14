![SIMPLseq logo](assets/simplseq-logo.png)

# SIMPLseq-nf App

SIMPLseq-nf App is a browser-based app for running the SIMPLseq malaria
amplicon workflow.

Start it with:

```bash
simplseq run
```

This opens a Flask browser interface where the user chooses a FASTQ folder,
reviews detected pairs, creates the sample sheet, starts the run, watches
progress, and downloads results.

Behind the GUI, SIMPLseq-nf App uses a Linux Conda/Mamba runtime and a local
Nextflow pipeline.

## Direction

SIMPLseq-nf App is GUI-first and CLI-backed.

```text
simplseq run
  -> Flask browser GUI
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

The lowest-friction release path is a GitHub Release with two assets:

- `install-simplseq.sh`
- `simplseq-nf-app-v1.0.tar.gz`

Users install from the release page with one command.

On Linux, WSL, or macOS:

```bash
curl -fsSL https://github.com/a-nadeem9/simplseq-nf-app/releases/download/v1.0/install-simplseq.sh | bash
simplseq run
```

The installer downloads the app files, creates a managed Micromamba runtime
under `~/.local/share/simplseq`, and installs a `simplseq` launcher into
`~/.local/bin`. Users do not need to activate an environment manually; the
launcher sets the project root, Python path, and runtime path internally.
Reinstalling the same version recreates that managed runtime by default so old
packages cannot linger after dependency changes. Set `SIMPLSEQ_REUSE_ENV=1` to
reuse the existing runtime intentionally.

On Linux/WSL, the installer uses the pinned `locks/linux-64-explicit.txt`
runtime lock when it is present. Set `SIMPLSEQ_USE_LOCK=0` to force a fresh
solve from `environment.yml`. macOS currently resolves from `environment.yml`;
add platform locks after testing on Intel and Apple Silicon Macs.

If `simplseq` is not found immediately after installation, open a new shell or
run:

```bash
source ~/.bashrc
```

On Windows, run through WSL. Double-click launchers may be provided later as
convenience wrappers only; they are not the main install path.

## Release Testing

Build the release assets locally:

```bash
scripts/build_release.sh
```

The GitHub Actions workflow provides the end-user test path:

- `Installer smoke` builds release-shaped tarball/checksum assets, installs
  them on Linux, and can also install them on macOS runners.

The macOS workflow is the first real gate for macOS support. A passing workflow
means the installer can fetch the app, create the Micromamba runtime, run the
runtime check, and expose the `simplseq` launcher on a clean macOS runner.

## Normal Use

Start the app:

```bash
simplseq run
```

Then use the browser GUI to:

1. Choose the FASTQ folder path.
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

If that port is busy, `simplseq run` automatically chooses the next available
local port and prints the browser address.

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

The sample sheet parser always uses the FASTQ filename prefix as `sample_id`.
It also fills optional metadata when the name clearly contains common
participant/date/replicate patterns, including:

```text
Toro142Mar2023Rep1
Toro142_Rep1_Mar2023
2023Mar_Toro142_Rep1
Toro142-2023-03-15-Rep1
```

If metadata cannot be inferred safely, those optional fields are left blank;
the FASTQ paths are still written so Nextflow can run.

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
simplseq run-headless --samples samples.csv --out results --profile reproducible
simplseq results --out results
```

These are useful for testing, debugging, automation, support, and developer
mode. They are not the normal wet-lab user path.

Use `--profile reproducible` when byte-for-byte reproducibility is more
important than maximum local DADA2 throughput.

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
