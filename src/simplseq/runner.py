"""Local Nextflow runner for SIMPLseq App."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .job_state import read_json, write_json, write_state
from .pathutils import user_path
from .progress import emit_event, read_events
from .provenance import PINNED_PARAMETER_KEYS, write_input_md5s, write_provenance, write_versions
from .resources import resource_checks, sample_file_checks


STAGES = [
    "prepare_inputs",
    "dada2",
    "prepare_stage2",
    "asv_mapping",
    "prepare_stage3",
    "cigar_check",
    "asv_to_cigar",
    "report",
]


@dataclass(frozen=True)
class RunResult:
    returncode: int
    command: list[str]
    technical_log: Path


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def project_root() -> Path:
    configured = os.environ.get("SIMPLSEQ_PROJECT_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parents[2]


def command_exists(name: str) -> bool:
    return shutil.which(name) is not None


def local_conda_env(root: Path) -> Path | None:
    configured = os.environ.get("SIMPLSEQ_ENV_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return None


def local_runtime_env(root: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src") + os.pathsep + env.get("PYTHONPATH", "")
    conda_env = local_conda_env(root)
    conda_bin = conda_env / "bin" if conda_env else None
    if conda_env and conda_bin and conda_bin.exists():
        env["CONDA_PREFIX"] = str(conda_env)
        env["PATH"] = str(conda_bin) + os.pathsep + env.get("PATH", "")
    tools_dir = root / "tools"
    if tools_dir.exists():
        env["PATH"] = str(tools_dir) + os.pathsep + env.get("PATH", "")
    java_home = root / "tools" / "java"
    if (java_home / "bin" / "java").exists():
        env["JAVA_HOME"] = str(java_home)
        env["PATH"] = str(java_home / "bin") + os.pathsep + env.get("PATH", "")
    return env


def resolve_command(command: str, env: dict[str, str]) -> str:
    resolved = shutil.which(command, path=env.get("PATH", ""))
    return resolved or ""


def run_probe(
    name: str,
    command: list[str],
    env: dict[str, str],
    *,
    timeout: int = 30,
) -> dict[str, str]:
    try:
        completed = subprocess.run(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
            timeout=timeout,
            env=env,
        )
    except FileNotFoundError:
        return {"name": name, "status": "missing", "detail": f"{command[0]} not found"}
    except subprocess.TimeoutExpired:
        return {"name": name, "status": "missing", "detail": "check timed out"}
    output = " ".join(completed.stdout.split()) if completed.stdout else ""
    detail = output[:220] if output else "ok"
    return {"name": name, "status": "ok" if completed.returncode == 0 else "missing", "detail": detail}


def check_environment(root: Path, samples: Path | None = None, *, profile: str = "local") -> list[dict[str, str]]:
    if profile != "local":
        raise ValueError("SIMPLseq App currently supports the local Conda/Nextflow runtime only")
    checks: list[dict[str, str]] = []
    env = local_runtime_env(root)
    command_checks = [("Python", "python"), ("Rscript", "Rscript"), ("MUSCLE", "muscle")]
    for name, command in command_checks:
        resolved = resolve_command(command, env)
        if name == "Python" and not resolved:
            resolved = resolve_command("python3", env)
        checks.append(
            {
                "name": name,
                "status": "ok" if resolved else "missing",
                "detail": resolved or f"{command} not found",
            }
        )
    java = resolve_command("java", env)
    checks.append({"name": "Java", "status": "ok" if java else "missing", "detail": java or "java not found"})
    nextflow_candidates = [resolve_command("nextflow", env), str(root / "tools" / "nextflow")]
    nextflow = next((item for item in nextflow_candidates if item and Path(item).exists()), "")
    checks.append({"name": "Nextflow", "status": "ok" if nextflow else "missing", "detail": nextflow or "nextflow not found"})
    checks.extend(
        [
            run_probe("Python packages", ["python", "-c", "import pandas; print('pandas ok')"], env),
            run_probe("Java works", ["java", "-version"], env),
            run_probe("Nextflow works", ["nextflow", "-version"], env),
            run_probe("DADA2 loads", ["Rscript", "-e", "suppressPackageStartupMessages(library(dada2)); cat(as.character(packageVersion('dada2')))"], env, timeout=60),
            run_probe("MUSCLE works", ["muscle", "-version"], env),
        ]
    )
    for rel in [
        "main.nf",
        "nextflow.config",
        "workflow/scripts/AmpliconPipeline.py",
        "workflow/scripts/postProc_dada2.R",
        "workflow/scripts/ASV_to_CIGAR.py",
        "workflow/scripts/runDADA2.R",
        "workflow/scripts/adjustASV.R",
        "workflow/scripts/create_meta.py",
        "workflow/bin/simplseq_nf_helpers.py",
        "reference/amplicons_noprimers.fasta",
        "reference/snv_filters.txt",
        "workflow/primers/primers_fwd.fa",
        "workflow/primers/primers_rev.fa",
        "workflow/primers/overlap_pr1.fa",
        "workflow/primers/overlap_pr2.fa",
    ]:
        path = root / rel
        checks.append(
            {
                "name": rel,
                "status": "ok" if path.exists() else "missing",
                "detail": str(path),
            }
        )
    if samples is not None:
        checks.append(
            {
                "name": "samples",
                "status": "ok" if samples.exists() else "missing",
                "detail": str(samples),
            }
        )
        checks.extend(sample_file_checks(samples))
    checks.extend(resource_checks(samples, root / "results"))
    return checks


def analysis_parameters() -> dict[str, object]:
    return {
        "amplicons_noprimers": "reference/amplicons_noprimers.fasta",
        "snv_filters": "reference/snv_filters.txt",
        "primers_fwd": "workflow/primers/primers_fwd.fa",
        "primers_rev": "workflow/primers/primers_rev.fa",
        "overlap_primers_fwd": "workflow/primers/overlap_pr1.fa",
        "overlap_primers_rev": "workflow/primers/overlap_pr2.fa",
        "pipeline_class": "parasite",
        "max_ee": "5,5",
        "trim_right": "0,0",
        "min_len": "50",
        "trunc_q": "5,5",
        "max_consist": "10",
        "omega_a": "1e-120",
        "just_concatenate": "0",
        "dada2_randomize": "1",
        "dada2_multithread": "1",
        "dada2_seed": "",
        "strict_min_asv_length": 100,
        "indel_filter": "0.10",
        "cigar_homopolymer_mask_length": 5,
        "cigar_min_total_reads": 100,
        "cigar_min_samples": 2,
        "cigar_exclude_bimeras": True,
        "inline_barcodes_enabled": False,
        "sentinel_locus": "KELT",
    }


def run_nextflow(
    samples: Path,
    outdir: Path,
    *,
    profile: str = "local",
    resume: bool = True,
    work_dir: Path | None = None,
    root: Path | None = None,
    dry_run: bool = False,
    cpus: int | None = None,
    memory: str | None = None,
) -> RunResult:
    root = (root or project_root()).resolve()
    samples = user_path(samples).resolve()
    outdir = user_path(outdir).resolve()
    work_dir = user_path(work_dir or (outdir / ".nextflow_work")).resolve()
    logs_dir = outdir / "logs"
    progress_file = outdir / "progress.jsonl"
    technical_log = outdir / "technical_log.txt"
    legacy_technical_log = logs_dir / "technical_log.txt"
    state_file = outdir / "run_state.json"
    parameters_file = outdir / "parameters.json"
    provenance_file = outdir / "provenance.json"
    versions_file = outdir / "versions.txt"
    input_md5s_file = outdir / "input_fastq_md5s.tsv"
    started_at = utc_now()

    outdir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    if progress_file.exists() and not resume:
        progress_file.unlink()

    pinned_parameters = analysis_parameters()
    parameters = {
        "samples": str(samples),
        "outdir": str(outdir),
        "work_dir": str(work_dir),
        "engine": "nextflow-local",
        "nextflow_profile": profile,
        "resume": resume,
        "dada2_randomize": "1",
        "dada2_multithread": "1",
        "cigar_min_total_reads": 100,
        "cigar_min_samples": 2,
        "cigar_exclude_bimeras": True,
        "analysis_parameters": pinned_parameters,
        "pinned_parameter_keys": PINNED_PARAMETER_KEYS,
    }
    write_json(parameters_file, parameters)
    write_state(
        state_file,
        status="starting",
        started_at=started_at,
        completed_at=None,
        samples=str(samples),
        outdir=str(outdir),
        engine="nextflow-local",
        nextflow_profile=profile,
        technical_log=str(technical_log),
    )
    emit_event(progress_file, "run", "started", message="Starting SIMPLseq App run")

    command = [
        "nextflow",
        "run",
        str(root / "main.nf"),
        "-profile",
        profile,
        "-work-dir",
        str(work_dir),
        "--samples",
        str(samples),
        "--outdir",
        str(outdir),
        "--project_name",
        "SIMPLseq",
    ]
    if cpus:
        dada2_cpus = max(1, int(cpus))
        postprocess_cpus = max(1, int(cpus))
        cigar_cpus = min(4, max(1, int(cpus)))
        command.extend(
            [
                "--dada2_cpus",
                str(dada2_cpus),
                "--postprocess_cpus",
                str(postprocess_cpus),
                "--cigar_cpus",
                str(cigar_cpus),
            ]
        )
    if memory:
        command.extend(["--dada2_memory", memory, "--postprocess_memory", memory])
    if resume:
        command.append("-resume")

    if dry_run:
        technical_log.write_text(" ".join(command) + "\n", encoding="utf-8")
        legacy_technical_log.write_text(technical_log.read_text(encoding="utf-8"), encoding="utf-8")
        write_state(state_file, status="dry_run", command=command, outdir=str(outdir), technical_log=str(technical_log))
        return RunResult(0, command, technical_log)

    if profile != "local":
        raise ValueError("SIMPLseq App currently supports the local Conda/Nextflow runtime only")

    env = local_runtime_env(root)
    env["NXF_HOME"] = str(outdir / ".nextflow")
    env["TMPDIR"] = str(outdir / ".tmp")
    Path(env["NXF_HOME"]).mkdir(parents=True, exist_ok=True)
    Path(env["TMPDIR"]).mkdir(parents=True, exist_ok=True)

    write_state(
        state_file,
        status="running",
        started_at=started_at,
        completed_at=None,
        samples=str(samples),
        outdir=str(outdir),
        engine="nextflow-local",
        nextflow_profile=profile,
        technical_log=str(technical_log),
    )
    write_versions(versions_file, root=root, env=env)
    write_input_md5s(input_md5s_file, samples)

    with technical_log.open("w", encoding="utf-8", errors="replace") as log:
        log.write("[SIMPLseq] command: " + " ".join(command) + "\n")
        log.flush()
        process = subprocess.Popen(
            command,
            cwd=root,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert process.stdout is not None
        for line in process.stdout:
            log.write(line)
            log.flush()
            print(line, end="")
        returncode = process.wait()

    status = "complete" if returncode == 0 else "failed"
    emit_event(progress_file, "run", status, message="SIMPLseq App run finished")
    legacy_technical_log.write_text(technical_log.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
    completed_at = utc_now()
    write_state(
        state_file,
        status=status,
        started_at=started_at,
        completed_at=completed_at,
        returncode=returncode,
        samples=str(samples),
        outdir=str(outdir),
        engine="nextflow-local",
        nextflow_profile=profile,
        technical_log=str(technical_log),
    )
    write_provenance(
        provenance_file,
        simplseq_version=__version__,
        root=root,
        samples=samples,
        outdir=outdir,
        profile=profile,
        parameters_file=parameters_file,
        versions_file=versions_file,
        input_md5s_file=input_md5s_file,
        status=status,
        completed_at=completed_at,
    )
    return RunResult(returncode, command, technical_log)


def progress_summary(outdir: Path) -> dict[str, str | int]:
    events = read_events(outdir / "progress.jsonl")
    state = read_json(outdir / "run_state.json")
    completed = {event.get("stage") for event in events if event.get("status") == "complete"}
    failed = [event for event in events if event.get("status") in {"failed", "error"}]
    current = ""
    for event in reversed(events):
        if event.get("user_visible", True):
            current = str(event.get("stage", ""))
            break
    state_status = str(state.get("status", "")) if state else ""
    if state_status in {"complete", "failed", "dry_run"}:
        status = state_status
    elif failed:
        status = "failed"
    elif events:
        status = "running"
    else:
        status = "pending"
    return {
        "events": len(events),
        "completed_stages": len(completed.intersection(STAGES)),
        "total_stages": len(STAGES),
        "current_stage": current or "pending",
        "status": status,
    }


def results_manifest(outdir: Path) -> dict[str, object]:
    outdir = user_path(outdir).resolve()
    files = [
        ("Run summary", outdir / "reports" / "run_summary.html"),
        ("ASV count table", outdir / "run_dada2" / "seqtab_iseq.tsv"),
        ("Mapped ASV table", outdir / "run_dada2" / "ASV_mapped_table.tsv"),
        ("ASV to CIGAR map", outdir / "run_dada2" / "asv_to_cigar.tsv"),
        ("CIGAR count table", outdir / "run_dada2" / "seqtab_cigar.tsv"),
        ("Progress events", outdir / "progress.jsonl"),
        ("Run state", outdir / "run_state.json"),
        ("Provenance", outdir / "provenance.json"),
        ("Parameters", outdir / "parameters.json"),
        ("Versions", outdir / "versions.txt"),
        ("Input FASTQ MD5s", outdir / "input_fastq_md5s.tsv"),
        ("Technical log", outdir / "technical_log.txt"),
    ]
    return {
        "outdir": str(outdir),
        "state": read_json(outdir / "run_state.json"),
        "files": [
            {
                "label": label,
                "path": str(path),
                "exists": path.exists(),
                "size_bytes": path.stat().st_size if path.exists() else 0,
            }
            for label, path in files
        ],
    }
