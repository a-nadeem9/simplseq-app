"""Flask browser app for SIMPLseq-nf App."""

from __future__ import annotations

import csv
import os
import re
import subprocess
import sys
import threading
import time
import webbrowser
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any

from flask import Flask, abort, jsonify, render_template, request, send_file, send_from_directory, url_for

from simplseq import __version__
from simplseq.job_state import read_json
from simplseq.pathutils import user_path
from simplseq.progress import read_events
from simplseq.resources import human_bytes
from simplseq.runner import (
    check_environment,
    local_runtime_env,
    progress_summary,
    project_root,
    results_manifest,
)
from simplseq.samplesheet import SAMPLE_FIELDS, FastqPair, FastqScan, scan_fastqs, write_samples_csv


RUN_PROCESSES: dict[str, subprocess.Popen[str]] = {}
RUN_LOCK = threading.Lock()
DOWNLOAD_SLUG_RE = re.compile(r"[^a-z0-9]+")
ANSI_RE = re.compile(r"\x1B\][^\x07]*(?:\x07|\x1B\\)|\x1B\[[0-?]*[ -/]*[@-~]|\x1B[@-Z\\-_]")
CORE_RESULT_LABELS = {
    "ASV count table",
    "Mapped ASV table",
    "ASV to CIGAR map",
    "CIGAR count table",
}
REPORT_LABEL = "Run summary"
BUNDLE_RESULT_LABELS = CORE_RESULT_LABELS | {REPORT_LABEL, "Input FASTQ MD5s"}


def resolve_app_path(root: Path, value: str | os.PathLike[str] | None, default: str | Path) -> Path:
    raw = str(value if value not in {None, ""} else default).strip()
    path = user_path(raw)
    if not path.is_absolute():
        path = root / path
    return path.expanduser().resolve()


def rel_or_abs(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def bool_payload(data: dict[str, Any], key: str, default: bool = False) -> bool:
    value = data.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "on"}
    return bool(value)


def int_payload(data: dict[str, Any], key: str, default: int = 0) -> int:
    try:
        return int(data.get(key, default) or default)
    except (TypeError, ValueError):
        return default


def slugify(label: str) -> str:
    slug = DOWNLOAD_SLUG_RE.sub("-", label.lower()).strip("-")
    return slug or "file"


def json_error(message: str, status: int = 400, **extra: Any):
    payload = {"ok": False, "error": message}
    payload.update(extra)
    return jsonify(payload), status


def sample_pair_json(pair: FastqPair, root: Path) -> dict[str, str]:
    return {
        "sample_id": pair.sample_id,
        "participant_id": pair.participant_id,
        "collection_date": pair.collection_date,
        "replicate": pair.replicate,
        "sample_type": pair.sample_type,
        "fastq_1": rel_or_abs(root, pair.fastq_1),
        "fastq_2": rel_or_abs(root, pair.fastq_2),
    }


def scan_json(scan: FastqScan, root: Path, *, preview_limit: int = 100) -> dict[str, Any]:
    missing_pairs = len(scan.missing_r2) + len(scan.orphan_r2)
    return {
        "fastq_dir": str(scan.fastq_dir),
        "pair_count": len(scan.pairs),
        "md5_files": scan.md5_files,
        "total_fastq_bytes": scan.total_fastq_bytes,
        "total_fastq_size": human_bytes(scan.total_fastq_bytes),
        "missing_pairs": missing_pairs,
        "missing_r2": scan.missing_r2[:100],
        "orphan_r2": scan.orphan_r2[:100],
        "duplicate_sample_ids": scan.duplicate_sample_ids,
        "preview": [sample_pair_json(pair, root) for pair in scan.pairs[:preview_limit]],
    }


def read_samples_preview(path: Path, limit: int = 100) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8", errors="replace") as handle:
        rows = []
        for index, row in enumerate(csv.DictReader(handle)):
            if index >= limit:
                break
            rows.append({field: row.get(field, "") for field in SAMPLE_FIELDS})
        return rows


def file_tail(path: Path, max_bytes: int) -> tuple[str, bool]:
    if not path.exists():
        return "", False
    size = path.stat().st_size
    with path.open("rb") as handle:
        if size > max_bytes:
            handle.seek(size - max_bytes)
            data = handle.read()
            return data.decode("utf-8", errors="replace"), True
        return handle.read().decode("utf-8", errors="replace"), False


def clean_log_text(text: str) -> str:
    cleaned = ANSI_RE.sub("", text)
    return "".join(ch for ch in cleaned if ch in {"\n", "\r", "\t"} or ord(ch) >= 32).replace("\r", "\n")


def append_runtime_check_log(outdir: Path, rows: list[dict[str, str]]) -> None:
    outdir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d %H:%M:%S %Z")
    with (outdir / "technical_log.txt").open("a", encoding="utf-8") as handle:
        handle.write(f"[SIMPLseq/App] {stamp} runtime check\n")
        for row in rows:
            status = str(row.get("status", "")).upper()
            name = row.get("name", "check")
            detail = row.get("detail", "")
            handle.write(f"[{status}] {name}: {detail}\n")
        handle.write("\n")


def safe_exists(path: Path) -> bool:
    try:
        return path.exists()
    except OSError:
        return False


def safe_is_dir(path: Path) -> bool:
    try:
        return path.is_dir()
    except OSError:
        return False


def safe_is_file(path: Path) -> bool:
    try:
        return path.is_file()
    except OSError:
        return False


def safe_resolve(path: Path) -> Path | None:
    try:
        return path.expanduser().resolve()
    except (OSError, RuntimeError):
        return None


def is_wsl() -> bool:
    try:
        proc_version = Path("/proc/version").read_text(encoding="utf-8", errors="ignore").lower()
    except OSError:
        return False
    return "microsoft" in proc_version or "wsl" in proc_version


def wsl_to_windows_path(path: Path) -> str:
    text = str(path)
    match = re.match(r"^/mnt/([a-zA-Z])(?:/(.*))?$", text)
    if match:
        drive = match.group(1).upper()
        rest = (match.group(2) or "").replace("/", "\\")
        return f"{drive}:\\{rest}" if rest else f"{drive}:\\"
    try:
        completed = subprocess.run(
            ["wslpath", "-w", text],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=3,
        )
    except (OSError, subprocess.TimeoutExpired):
        return text
    return completed.stdout.strip() or text


def windows_to_wsl_path(value: str) -> str:
    text = value.strip().replace("\\", "/")
    match = re.match(r"^([A-Za-z]):/?(.*)$", text)
    if not match:
        return value.strip()
    drive = match.group(1).lower()
    rest = match.group(2).strip("/")
    return f"/mnt/{drive}/{rest}" if rest else f"/mnt/{drive}"


def select_folder_dialog(initial: Path | None = None) -> dict[str, Any]:
    if not is_wsl():
        return {"ok": False, "error": "Native folder picker is only available in WSL for this build."}
    env = os.environ.copy()
    if initial:
        env["SIMPLSEQ_PICKER_INITIAL"] = wsl_to_windows_path(initial)
    script = r"""
Add-Type -AssemblyName System.Windows.Forms
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$dialog = New-Object System.Windows.Forms.FolderBrowserDialog
$dialog.Description = "Select the folder containing FASTQ files"
$dialog.ShowNewFolderButton = $false
if ($env:SIMPLSEQ_PICKER_INITIAL -and (Test-Path -LiteralPath $env:SIMPLSEQ_PICKER_INITIAL)) {
  $dialog.SelectedPath = $env:SIMPLSEQ_PICKER_INITIAL
}
$result = $dialog.ShowDialog()
if ($result -eq [System.Windows.Forms.DialogResult]::OK) {
  Write-Output $dialog.SelectedPath
}
"""
    try:
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Sta", "-ExecutionPolicy", "Bypass", "-Command", script],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=600,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error": f"Folder picker could not open: {exc}"}
    selected = completed.stdout.strip().splitlines()[-1].strip() if completed.stdout.strip() else ""
    if completed.returncode != 0 and not selected:
        detail = " ".join(completed.stderr.split())[:220] if completed.stderr else "PowerShell folder picker failed"
        return {"ok": False, "error": detail}
    if not selected:
        return {"ok": True, "selected": False}
    return {"ok": True, "selected": True, "path": windows_to_wsl_path(selected), "windows_path": selected}


def common_paths(workspace_root: Path, app_root: Path) -> list[dict[str, str]]:
    paths: list[tuple[str, Path]] = [
        ("Current folder", workspace_root),
        ("Data in current folder", workspace_root / "data"),
        ("Home", Path.home()),
    ]
    if safe_exists(workspace_root / "test-data"):
        paths.append(("Test data", workspace_root / "test-data"))
    desktop = Path.home() / "Desktop"
    if safe_exists(desktop):
        paths.append(("Desktop", desktop))
    windows_home = Path("/mnt/c/Users") / Path.home().name
    for label, path in [
        ("Windows home", windows_home),
        ("Windows Desktop", windows_home / "Desktop"),
        ("Windows Downloads", windows_home / "Downloads"),
        ("Windows Documents", windows_home / "Documents"),
    ]:
        if safe_exists(path):
            paths.append((label, path))
    for mount in [Path("/mnt/c"), Path("/mnt/d")]:
        if safe_exists(mount):
            paths.append((str(mount), mount))
    windows_users = Path("/mnt/c/Users")
    if safe_exists(windows_users):
        try:
            candidates = sorted(windows_users.iterdir(), key=lambda item: item.name.lower())
        except OSError:
            candidates = []
        for candidate in candidates:
            desktop_dir = candidate / "Desktop"
            if safe_exists(desktop_dir):
                paths.append((f"{candidate.name} Desktop", desktop_dir))
    seen: set[str] = set()
    result = []
    for label, path in paths:
        resolved_path = safe_resolve(path)
        if resolved_path is None:
            continue
        resolved = str(resolved_path)
        if resolved in seen:
            continue
        seen.add(resolved)
        result.append({"label": label, "path": resolved})
    return result


def fastq_count(path: Path) -> int:
    count = 0
    try:
        for item in path.iterdir():
            if item.name.endswith((".fastq.gz", ".fq.gz")) and safe_is_file(item):
                count += 1
    except OSError:
        return 0
    return count


def browse_payload(path: Path) -> dict[str, Any]:
    if not safe_exists(path):
        return {"path": str(path), "exists": False, "directories": [], "parent": str(path.parent)}
    if not safe_is_dir(path):
        return {"path": str(path), "exists": True, "is_dir": False, "directories": [], "parent": str(path.parent)}
    directories = []
    try:
        children = sorted((item for item in path.iterdir() if safe_is_dir(item)), key=lambda item: item.name.lower())
    except OSError:
        children = []
    for child in children[:250]:
        directories.append(
            {
                "name": child.name,
                "path": str(child),
                "fastq_files": fastq_count(child),
            }
        )
    current_fastq_files = fastq_count(path)
    scan = scan_fastqs(path) if current_fastq_files else FastqScan(path, [], [], [], 0, 0, [])
    return {
        "path": str(path),
        "exists": True,
        "is_dir": True,
        "parent": str(path.parent),
        "directories": directories,
        "fastq_files": current_fastq_files,
        "pair_count": len(scan.pairs),
        "missing_pairs": len(scan.missing_r2) + len(scan.orphan_r2),
    }


def result_files_with_downloads(root: Path, outdir: Path) -> dict[str, Any]:
    manifest = results_manifest(outdir)
    files = []
    for item in manifest["files"]:
        label = str(item["label"])
        slug = slugify(label)
        exists = bool(item["exists"])
        size_bytes = int(item["size_bytes"])
        files.append(
            {
                "label": label,
                "slug": slug,
                "path": item["path"],
                "relative_path": rel_or_abs(root, Path(str(item["path"]))),
                "exists": exists,
                "size_bytes": size_bytes,
                "size": human_bytes(size_bytes),
                "status": "ready" if exists and size_bytes else "missing",
                "download_url": url_for("download_result", file_key=slug, out=str(outdir)) if exists else "",
                "view_url": url_for("download_result", file_key=slug, out=str(outdir), inline=1)
                if exists and label == REPORT_LABEL
                else "",
            }
        )
    manifest["files"] = files
    manifest["report"] = next((item for item in files if item["label"] == REPORT_LABEL), None)
    manifest["core_files"] = [item for item in files if item["label"] in CORE_RESULT_LABELS]
    manifest["support_files"] = [
        item for item in files if item["label"] != REPORT_LABEL and item["label"] not in CORE_RESULT_LABELS
    ]
    manifest["ready_counts"] = {
        "core": sum(1 for item in manifest["core_files"] if item["status"] == "ready"),
        "support": sum(1 for item in manifest["support_files"] if item["status"] == "ready"),
    }
    manifest["bundle_ready"] = any(
        item["label"] in BUNDLE_RESULT_LABELS and item["status"] == "ready" for item in files
    )
    manifest["bundle_url"] = url_for("download_bundle", out=str(outdir)) if manifest["bundle_ready"] else ""
    return manifest


def bundle_result_paths(outdir: Path) -> list[tuple[Path, str]]:
    outdir = outdir.resolve()
    bundled: list[tuple[Path, str]] = []
    for item in results_manifest(outdir)["files"]:
        label = str(item["label"])
        if label not in BUNDLE_RESULT_LABELS:
            continue
        path = Path(str(item["path"])).resolve()
        try:
            arcname = path.relative_to(outdir).as_posix()
        except ValueError:
            continue
        if path.exists() and path.is_file() and path.stat().st_size > 0:
            bundled.append((path, arcname))
    return bundled


def active_state(outdir: Path) -> bool:
    state = read_json(outdir / "run_state.json")
    return state.get("status") in {"starting", "running"}


def process_active(outdir: Path) -> bool:
    key = str(outdir)
    with RUN_LOCK:
        process = RUN_PROCESSES.get(key)
        if process is None:
            return False
        if process.poll() is None:
            return True
        RUN_PROCESSES.pop(key, None)
    return False


def start_run_process(root: Path, samples: Path, outdir: Path, data: dict[str, Any]) -> subprocess.Popen[str]:
    outdir.mkdir(parents=True, exist_ok=True)
    logs_dir = outdir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "simplseq",
        "run-headless",
        "--samples",
        str(samples),
        "--out",
        str(outdir),
    ]
    cpus = int_payload(data, "cpus", 0)
    memory = str(data.get("memory", "")).strip()
    if cpus:
        command.extend(["--cpus", str(cpus)])
    if memory:
        command.extend(["--memory", memory])
    if bool_payload(data, "clean", True):
        command.append("--no-resume")
    if bool_payload(data, "dry_run", False):
        command.append("--dry-run")

    env = local_runtime_env(root)
    env["SIMPLSEQ_PROJECT_ROOT"] = str(root)
    env["PYTHONPATH"] = str(root / "src") + os.pathsep + env.get("PYTHONPATH", "")
    stdout_handle = (logs_dir / "flask-run.stdout.log").open("w", encoding="utf-8")
    stderr_handle = (logs_dir / "flask-run.stderr.log").open("w", encoding="utf-8")
    kwargs: dict[str, Any] = {}
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    else:
        kwargs["start_new_session"] = True
    process = subprocess.Popen(
        command,
        cwd=root,
        env=env,
        text=True,
        stdout=stdout_handle,
        stderr=stderr_handle,
        **kwargs,
    )
    stdout_handle.close()
    stderr_handle.close()
    with RUN_LOCK:
        RUN_PROCESSES[str(outdir)] = process
    return process


def create_app(root: Path | None = None, workspace_root: Path | None = None) -> Flask:
    app_root = (root or project_root()).resolve()
    workspace = (workspace_root or Path.cwd()).expanduser().resolve()
    gui_root = Path(__file__).resolve().parent
    app = Flask(
        __name__,
        static_folder=str(gui_root / "static"),
        template_folder=str(gui_root / "templates"),
    )
    app.config["SIMPLSEQ_PROJECT_ROOT"] = app_root
    app.config["SIMPLSEQ_WORKSPACE_ROOT"] = workspace
    app.config["TEMPLATES_AUTO_RELOAD"] = True

    @app.get("/")
    def index():
        static_paths = [gui_root / "static" / "css" / "app.css", gui_root / "static" / "js" / "app.js"]
        asset_version = str(max((path.stat().st_mtime_ns for path in static_paths if path.exists()), default=0))
        return render_template(
            "index.html",
            workspace_root=str(workspace),
            asset_version=asset_version,
        )

    @app.get("/assets/<path:filename>")
    def assets(filename: str):
        assets_dir = (app_root / "assets").resolve()
        requested = (assets_dir / filename).resolve()
        try:
            requested.relative_to(assets_dir)
        except ValueError:
            abort(404)
        return send_from_directory(assets_dir, filename)

    @app.get("/api/health")
    def api_health():
        return jsonify(
            {
                "ok": True,
                "app": "SIMPLseq-nf App",
                "version": f"v{__version__}-dev" if __version__ == "0.1.0" else f"v{__version__}",
                "app_root": str(app_root),
                "workspace_root": str(workspace),
                "common_paths": common_paths(workspace, app_root),
            }
        )

    @app.get("/api/browse")
    def api_browse():
        path = resolve_app_path(workspace, request.args.get("path"), workspace)
        return jsonify({"ok": True, **browse_payload(path)})

    @app.post("/api/select-folder")
    def api_select_folder():
        data = request.get_json(silent=True) or {}
        initial = resolve_app_path(workspace, data.get("initial"), workspace)
        return jsonify(select_folder_dialog(initial))

    @app.post("/api/scan")
    def api_scan():
        data = request.get_json(silent=True) or {}
        fastq_dir = resolve_app_path(workspace, data.get("fastq_dir"), "data")
        samples_out = resolve_app_path(workspace, data.get("samples_out"), "samples.csv")
        include_pool = bool_payload(data, "include_pool_in_sample_id", False)
        absolute = bool_payload(data, "absolute_paths", True)
        write_samples = bool_payload(data, "write_samples", True)

        scan = scan_fastqs(fastq_dir, include_pool_in_sample_id=include_pool)
        written = False
        duplicates: list[str] = scan.duplicate_sample_ids
        count = 0
        if write_samples and not duplicates:
            count, duplicates = write_samples_csv(
                fastq_dir,
                samples_out,
                include_pool_in_sample_id=include_pool,
                absolute=absolute,
            )
            written = not duplicates
        response = scan_json(scan, workspace)
        response.update(
            {
                "ok": True,
                "samples_out": str(samples_out),
                "samples_relative": rel_or_abs(workspace, samples_out),
                "samples_written": written,
                "sample_rows_written": count,
                "sample_preview": read_samples_preview(samples_out),
            }
        )
        return jsonify(response)

    @app.post("/api/check")
    def api_check():
        data = request.get_json(silent=True) or {}
        samples = data.get("samples")
        samples_path = resolve_app_path(workspace, samples, "samples.csv") if samples else None
        outdir = resolve_app_path(workspace, data.get("outdir"), "results")
        rows = check_environment(app_root, samples_path, outdir=outdir)
        append_runtime_check_log(outdir, rows)
        failed = sum(1 for row in rows if row.get("status") not in {"ok", "warn"})
        return jsonify({"ok": failed == 0, "failed": failed, "checks": rows})

    @app.post("/api/run")
    def api_run():
        data = request.get_json(silent=True) or {}
        samples = resolve_app_path(workspace, data.get("samples"), "samples.csv")
        outdir = resolve_app_path(workspace, data.get("outdir"), "results")
        dry_run = bool_payload(data, "dry_run", False)
        if not samples.exists() and not dry_run:
            return json_error(f"Sample sheet not found: {samples}", 400)
        if active_state(outdir) or process_active(outdir):
            return json_error("A SIMPLseq run is already active for this output folder.", 409, outdir=str(outdir))
        try:
            process = start_run_process(app_root, samples, outdir, data)
        except Exception as exc:  # pragma: no cover - reported to browser
            return json_error(str(exc), 500)
        return jsonify(
            {
                "ok": True,
                "pid": process.pid,
                "outdir": str(outdir),
                "samples": str(samples),
                "dry_run": dry_run,
                "status_url": url_for("api_status", out=str(outdir)),
            }
        )

    @app.get("/api/status")
    def api_status():
        outdir = resolve_app_path(workspace, request.args.get("out"), "results")
        state = read_json(outdir / "run_state.json")
        summary = progress_summary(outdir)
        return jsonify(
            {
                "ok": True,
                "outdir": str(outdir),
                "state": state,
                "summary": summary,
                "active": active_state(outdir) or process_active(outdir),
            }
        )

    @app.get("/api/progress")
    def api_progress():
        outdir = resolve_app_path(workspace, request.args.get("out"), "results")
        events = read_events(outdir / "progress.jsonl")
        return jsonify(
            {
                "ok": True,
                "outdir": str(outdir),
                "events": events,
                "summary": progress_summary(outdir),
            }
        )

    @app.get("/api/results")
    def api_results():
        outdir = resolve_app_path(workspace, request.args.get("out"), "results")
        manifest = result_files_with_downloads(workspace, outdir)
        return jsonify({"ok": True, **manifest})

    @app.get("/api/logs")
    def api_logs():
        outdir = resolve_app_path(workspace, request.args.get("out"), "results")
        max_bytes = max(1000, min(int_payload(request.args, "max_bytes", 50000), 250000))
        log_text, truncated = file_tail(outdir / "technical_log.txt", max_bytes)
        return jsonify(
            {
                "ok": True,
                "outdir": str(outdir),
                "path": str(outdir / "technical_log.txt"),
                "text": clean_log_text(log_text),
                "truncated": truncated,
            }
        )

    @app.get("/download/<file_key>")
    def download_result(file_key: str):
        outdir = resolve_app_path(workspace, request.args.get("out"), "results")
        manifest = results_manifest(outdir)
        for item in manifest["files"]:
            label = str(item["label"])
            if slugify(label) != file_key:
                continue
            path = Path(str(item["path"])).resolve()
            try:
                path.relative_to(outdir.resolve())
            except ValueError:
                abort(404)
            if not path.exists() or not path.is_file():
                abort(404)
            inline = request.args.get("inline") == "1" and label == REPORT_LABEL
            return send_file(path, as_attachment=not inline, download_name=path.name)
        abort(404)

    @app.get("/download-bundle")
    def download_bundle():
        outdir = resolve_app_path(workspace, request.args.get("out"), "results")
        bundle_paths = bundle_result_paths(outdir)
        if not bundle_paths:
            abort(404)
        archive = BytesIO()
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zip_handle:
            for path, arcname in bundle_paths:
                zip_handle.write(path, arcname)
        archive.seek(0)
        bundle_name = f"{outdir.name or 'simplseq-results'}-output-bundle.zip"
        return send_file(archive, as_attachment=True, download_name=bundle_name, mimetype="application/zip")

    return app


def open_browser_later(url: str) -> None:
    time.sleep(1.0)
    if is_wsl():
        try:
            subprocess.Popen(["cmd.exe", "/c", "start", "", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except Exception:
            pass
    try:
        webbrowser.open(url)
    except Exception:
        pass


def run_server(root: Path | None = None, host: str = "127.0.0.1", port: int = 8501, open_browser: bool = True) -> int:
    app = create_app(root, Path.cwd())
    url = f"http://{host}:{port}"
    if open_browser:
        threading.Thread(target=open_browser_later, args=(url,), daemon=True).start()
    app.run(host=host, port=port, debug=False, use_reloader=False, threaded=True)
    return 0


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Run the SIMPLseq-nf App Flask GUI.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8501)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    return run_server(host=args.host, port=args.port, open_browser=not args.no_browser)


if __name__ == "__main__":
    raise SystemExit(main())
