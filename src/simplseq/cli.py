"""Command line interface for SIMPLseq-nf App."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import socket
import subprocess
import sys
from pathlib import Path

from .pathutils import user_path
from .resources import human_bytes
from .runner import check_environment, progress_summary, project_root, results_manifest, run_nextflow
from .samplesheet import scan_fastqs, write_samples_csv
from . import __version__


APP_NAME = "SIMPLseq-nf App"
APP_VERSION = os.environ.get(
    "SIMPLSEQ_VERSION",
    "v1.0" if __version__ == "1.0.0" else f"v{__version__}",
)
APP_SUBTITLE = "Linux / WSL / macOS browser workflow"


def help_description() -> str:
    line = "=" * 54
    return "\n".join(
        [
            line,
            f"  >_ {APP_NAME} {APP_VERSION}",
            f"     {APP_SUBTITLE}",
            "     Nextflow + Conda/Mamba runtime",
            line,
        ]
    )


def use_color() -> bool:
    return os.environ.get("NO_COLOR") is None and (sys.stdout.isatty() or os.environ.get("FORCE_COLOR"))


def color(text: str, code: str) -> str:
    if not use_color():
        return text
    return f"\033[{code}m{text}\033[0m"


def tag(label: str, code: str) -> str:
    return color(f"[{label}]", code)


def print_banner(title: str, subtitle: str = "") -> None:
    line = "=" * 54
    print(color(line, "90"))
    print(f"  >_ {color(f'{APP_NAME} {APP_VERSION}', '1;37')}")
    print(f"     {color(APP_SUBTITLE, '36')}")
    if title != APP_NAME:
        print(f"     {color(title, '1;37')}")
    if subtitle:
        print(f"     {color(subtitle, '36')}")
    print(color(line, "90"))
    print()


def print_check_rows(rows: list[dict[str, str]]) -> int:
    failed = 0
    for row in rows:
        status = row["status"]
        if status == "ok":
            marker = tag("OK", "32") + "  "
        elif status == "warn":
            marker = tag("INFO", "34")
        else:
            marker = tag("MISS", "31")
        if status not in {"ok", "warn"}:
            failed += 1
        name = color(row["name"], "1")
        print(f"{marker} {name}: {row['detail']}")
    return failed


def cmd_scan(args: argparse.Namespace) -> int:
    print_banner("FASTQ pairing", "Sample sheet preparation")
    scan = scan_fastqs(args.fastq_dir, include_pool_in_sample_id=args.include_pool_in_sample_id)
    count, duplicates = write_samples_csv(
        args.fastq_dir,
        args.out,
        include_pool_in_sample_id=args.include_pool_in_sample_id,
        absolute=args.absolute,
    )
    if duplicates:
        print(f"{tag('ERROR', '31')} Duplicate sample IDs found:")
        for item in duplicates[:20]:
            print(f"  {item}")
        print(f"{tag('INFO', '34')} Re-run with --include-pool-in-sample-id or edit the sample names.")
        return 2
    print(f"{tag('OK', '32')} Wrote {count} sample rows to {Path(args.out).resolve()}")
    print(f"{tag('INFO', '34')} FASTQ pairs:       {len(scan.pairs)}")
    print(f"{tag('INFO', '34')} Missing R2 mates:  {len(scan.missing_r2)}")
    print(f"{tag('INFO', '34')} Orphan R2 files:   {len(scan.orphan_r2)}")
    print(f"{tag('INFO', '34')} Duplicate IDs:     {len(scan.duplicate_sample_ids)}")
    print(f"{tag('INFO', '34')} MD5 files:         {scan.md5_files}")
    print(f"{tag('INFO', '34')} Total FASTQ size:  {human_bytes(scan.total_fastq_bytes)}")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    print_banner("Runtime checks", "Python / R / DADA2 / Nextflow")
    root = project_root()
    samples = user_path(args.samples).resolve() if args.samples else None
    outdir = user_path(args.out).resolve()
    rows = check_environment(root, samples, outdir=outdir)
    failed = print_check_rows(rows)
    if failed:
        print(f"\n{tag('ERROR', '31')} {failed} checks need attention before a full run.")
        return 1
    print(f"\n{tag('OK', '32')} SIMPLseq-nf App environment looks ready.")
    return 0


def cmd_run_direct(args: argparse.Namespace) -> int:
    result = run_nextflow(
        user_path(args.samples),
        user_path(args.out),
        profile="local",
        resume=not args.no_resume,
        work_dir=user_path(args.work_dir) if args.work_dir else None,
        dry_run=args.dry_run,
        cpus=args.cpus,
        memory=args.memory,
    )
    print(f"{tag('INFO', '34')} Technical log: {result.technical_log}")
    return result.returncode


def cmd_status(args: argparse.Namespace) -> int:
    outdir = user_path(args.out).resolve()
    state_file = outdir / "run_state.json"
    if state_file.exists():
        print(state_file.read_text(encoding="utf-8", errors="replace"))
    summary = progress_summary(outdir)
    print(f"{tag('INFO', '34')} Progress: {summary['completed_stages']}/{summary['total_stages']} stages")
    print(f"{tag('INFO', '34')} Current:  {summary['current_stage']}")
    return 0


def cmd_results(args: argparse.Namespace) -> int:
    manifest = results_manifest(user_path(args.out))
    if args.json:
        print(json.dumps(manifest, indent=2))
        return 0
    print_banner("Run outputs", "Reports and final tables")
    print(f"{tag('INFO', '34')} Output folder: {manifest['outdir']}")
    state = manifest.get("state") or {}
    if state:
        print(f"{tag('INFO', '34')} Run status:    {state.get('status', 'unknown')}")
    print()
    missing = 0
    for row in manifest["files"]:
        marker = tag("OK", "32") + "  " if row["exists"] else tag("MISS", "31")
        if not row["exists"]:
            missing += 1
        print(f"{marker} {row['label']}: {row['path']}")
    return 1 if missing else 0


def cmd_app(args: argparse.Namespace) -> int:
    ui = args.ui or os.environ.get("SIMPLSEQ_UI", "flask")
    if ui == "streamlit":
        return cmd_streamlit_app(args)
    return cmd_flask_app(args)


def cmd_flask_app(args: argparse.Namespace) -> int:
    root = project_root()
    app = root / "gui" / "flask_app.py"
    if not app.exists():
        print(f"Flask app not found: {app}", file=sys.stderr)
        return 1
    port = find_free_port(args.port)
    if port is None:
        print(
            f"{tag('ERROR', '31')} No free port found from {args.port} to {args.port + 49}.",
            file=sys.stderr,
        )
        print(f"{tag('INFO', '34')} Stop another app or run: simplseq run --port 8600", file=sys.stderr)
        return 1
    if port != args.port:
        print(f"{tag('INFO', '34')} Port {args.port} is busy; using {port} instead.")
    print(f"{tag('INFO', '34')} Opening SIMPLseq-nf App at http://{args.host}:{port}")

    try:
        spec = importlib.util.spec_from_file_location("simplseq_flask_app", app)
        if spec is None or spec.loader is None:
            raise ImportError(f"could not load {app}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except ImportError as exc:
        print(f"{tag('ERROR', '31')} Flask GUI dependencies are not available: {exc}", file=sys.stderr)
        print(f"{tag('INFO', '34')} Re-run the installer or install the managed runtime.", file=sys.stderr)
        return 1
    return int(module.run_server(root=root, host=args.host, port=port, open_browser=not args.no_browser))


def cmd_streamlit_app(args: argparse.Namespace) -> int:
    root = project_root()
    app = root / "gui" / "streamlit_app.py"
    if not app.exists():
        print(f"Streamlit app not found: {app}", file=sys.stderr)
        return 1
    port = find_free_port(args.port)
    if port is None:
        print(
            f"{tag('ERROR', '31')} No free port found from {args.port} to {args.port + 49}.",
            file=sys.stderr,
        )
        print(f"{tag('INFO', '34')} Stop another app or run: simplseq run --port 8600", file=sys.stderr)
        return 1
    if port != args.port:
        print(f"{tag('INFO', '34')} Port {args.port} is busy; using {port} instead.")
    print(f"{tag('INFO', '34')} Opening SIMPLseq-nf App at http://127.0.0.1:{port}")
    command = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(app),
        "--browser.gatherUsageStats=false",
        "--server.headless=true",
        "--server.address=127.0.0.1",
        f"--server.port={port}",
    ]
    return subprocess.call(command, cwd=root)


def find_free_port(start: int, attempts: int = 50) -> int | None:
    for port in range(start, start + attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.2)
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    return None


def add_direct_run_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--samples", required=True)
    parser.add_argument("--out", "--outdir", dest="out", default="results")
    parser.add_argument("--work-dir", default="")
    parser.add_argument("--cpus", type=int, default=0, help="CPUs for heavy local stages")
    parser.add_argument("--memory", default="", help="Memory for heavy local stages, e.g. '12 GB'")
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--dry-run", action="store_true")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="simplseq",
        description=help_description(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("scan", help="Pair FASTQs and write samples.csv")
    p.add_argument("--fastq-dir", default="data")
    p.add_argument("--out", default="samples.csv")
    p.add_argument("--absolute", action="store_true")
    p.add_argument("--include-pool-in-sample-id", action="store_true")
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser("check", help="Check local runtime and optional inputs")
    p.add_argument("--samples", default=None)
    p.add_argument("--out", "--outdir", dest="out", default="results")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("run", help="Open the SIMPLseq-nf App browser interface")
    p.add_argument("--port", type=int, default=8501, help="Preferred local browser port")
    p.add_argument("--host", default="127.0.0.1", help=argparse.SUPPRESS)
    p.add_argument("--no-browser", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--ui", choices=["flask", "streamlit"], default=None, help=argparse.SUPPRESS)
    p.set_defaults(func=cmd_app)

    p = sub.add_parser("run-headless", help="Run the workflow without the browser GUI")
    add_direct_run_args(p)
    p.set_defaults(func=cmd_run_direct)

    p = sub.add_parser("status", help="Show local run status")
    p.add_argument("--out", "--outdir", dest="out", default="results")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("results", help="List expected output files")
    p.add_argument("--out", "--outdir", dest="out", default="results")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_results)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 0
    return args.func(args)
