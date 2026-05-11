"""Local Streamlit app for SIMPLseq-nf."""

from __future__ import annotations

import os
import csv
import json
import subprocess
import sys
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

APP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = Path(os.environ.get("SIMPLSEQ_PROJECT_ROOT", APP_DIR.parents[0])).resolve()
SRC_DIR = PROJECT_ROOT / "src"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from backend.simplseq_gui.operator import (
    SAMPLE_FIELDS,
    discover_outputs,
    format_bytes,
    local_backend_ready,
    read_samples_csv,
    runtime_checks,
    scan_fastqs,
    write_samples_csv,
)
from backend.simplseq_gui.local_runner import start_local_pipeline


LOGO = PROJECT_ROOT / "assets" / "simplseq-logo-dark-smooth.png"
DEFAULT_RUNTIME = "conda-local"
DEFAULT_RESULTS_DIR = "run_test_small" if (PROJECT_ROOT / "run_test_small").exists() else "results"

FRIENDLY_STAGE_FILES = [
    ("Preparing inputs", ("_local_work/preflight.tsv", "_local_work/meta.tsv", "_local_work/pipeline_inputs.json")),
    ("Trimming reads", ("_local_work/preprocess_meta.txt",)),
    ("Removing primers", ("_local_work/iseq_nop_prim_meta.txt",)),
    ("Running DADA2", ("_local_work/run_dada2/seqtab_iseq.tsv",)),
    ("Mapping ASVs", ("_local_work/ASV_mapped_table.filtered.tsv",)),
    ("Converting ASVs to CIGAR", ("_local_work/asv_to_cigar.tsv",)),
    ("Writing report", ("_local_work/run_summary.html",)),
]


st.set_page_config(
    page_title="SIMPLseq",
    page_icon="S",
    layout="wide",
    initial_sidebar_state="collapsed",
)


def inject_css() -> None:
    st.markdown(
        """
        <style>
        :root {
            --app-bg: #030404;
            --shell: #242424;
            --shell-2: #202020;
            --panel: #2b2b2b;
            --panel-2: #303030;
            --line: #3c3c3c;
            --line-soft: #343434;
            --ink: #f3f4f6;
            --muted: #a7adb6;
            --faint: #747b86;
            --cyan: #18c6ff;
            --magenta: #e6007e;
            --green: #20df86;
            --yellow: #ffc928;
            --red: #ff5656;
        }
        .stApp {
            background:
                radial-gradient(circle at 72% 8%, rgba(24, 198, 255, .10), transparent 28rem),
                radial-gradient(circle at 12% 100%, rgba(230, 0, 126, .08), transparent 24rem),
                var(--app-bg);
            color: var(--ink);
        }
        [data-testid="stHeader"] {
            background: transparent;
        }
        [data-testid="stHeader"]::before {
            background: transparent;
        }
        .block-container {
            max-width: 1180px;
            margin-top: 1.8rem;
            margin-bottom: 2rem;
            padding: 1.55rem 1.75rem 2.2rem 1.75rem;
            background: linear-gradient(145deg, rgba(39, 39, 39, .98), rgba(31, 31, 31, .98));
            border: 1px solid #333;
            border-radius: 28px;
            box-shadow: 0 28px 80px rgba(0, 0, 0, .55);
            overflow: visible;
        }
        section[data-testid="stSidebar"] {
            background: #101010;
            border-right: 1px solid #252525;
        }
        section[data-testid="stSidebar"] h1,
        section[data-testid="stSidebar"] h2,
        section[data-testid="stSidebar"] h3,
        section[data-testid="stSidebar"] p,
        section[data-testid="stSidebar"] span {
            color: var(--ink);
        }
        h1, h2, h3, h4, p, span, label {
            letter-spacing: 0;
            color: var(--ink);
        }
        h3 {
            text-transform: uppercase;
            font-weight: 900;
        }
        .hero {
            border-bottom: 1px solid var(--line-soft);
            padding: .05rem 0 .9rem 0;
            margin-bottom: .85rem;
        }
        .eyebrow {
            color: var(--muted);
            font-size: .62rem;
            font-weight: 800;
            letter-spacing: .08em;
            text-transform: uppercase;
        }
        .hero-title {
            color: #ffffff;
            font-size: 1.62rem;
            line-height: 1.05;
            font-weight: 900;
            margin-top: .12rem;
            text-transform: uppercase;
        }
        .hero-copy {
            color: var(--muted);
            max-width: 60rem;
            font-size: .82rem;
            margin-top: .28rem;
        }
        .workflow-strip {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: .5rem;
            margin: .25rem 0 .9rem 0;
            padding-bottom: .75rem;
            border-bottom: 1px solid var(--line-soft);
        }
        .workflow-step {
            background: rgba(20, 20, 20, .52);
            border: 1px solid var(--line-soft);
            border-radius: 8px;
            padding: .55rem .65rem;
            min-height: 3.6rem;
        }
        .workflow-step .number {
            color: var(--cyan);
            font-size: .58rem;
            font-weight: 900;
            text-transform: uppercase;
        }
        .workflow-step .label {
            color: #fff;
            margin-top: .16rem;
            font-size: .8rem;
            font-weight: 850;
        }
        .workflow-step .detail {
            color: var(--muted);
            font-size: .68rem;
            margin-top: .08rem;
        }
        div[data-baseweb="tab-list"] {
            gap: .45rem;
            border-bottom: 1px solid var(--line-soft);
            padding-bottom: .75rem;
        }
        button[data-baseweb="tab"] {
            height: 2.1rem;
            min-width: 8.2rem;
            border-radius: 4px;
            background: #d8d8d8;
            color: #0d0f12;
            font-size: .72rem;
            font-weight: 900;
            text-transform: uppercase;
            border: 0;
        }
        button[data-baseweb="tab"] p {
            color: #0d0f12;
            font-weight: 900;
        }
        button[data-baseweb="tab"][aria-selected="true"] {
            background: #d8d8d8 !important;
            color: #0d0f12 !important;
            box-shadow: 0 3px 0 var(--cyan);
        }
        button[data-baseweb="tab"][aria-selected="true"] * {
            color: #0d0f12 !important;
        }
        .soft-panel {
            border: 1px solid var(--line);
            background: rgba(47, 47, 47, .78);
            border-radius: 7px;
            padding: .85rem .9rem;
            margin-bottom: .8rem;
        }
        .panel-title {
            color: #fff;
            font-weight: 850;
            font-size: .86rem;
            margin-bottom: .14rem;
        }
        .panel-subtitle {
            color: var(--muted);
            font-size: .72rem;
            margin-bottom: .35rem;
        }
        .status-line {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: .65rem;
            border: 1px solid var(--line);
            background: rgba(45, 45, 45, .86);
            border-radius: 8px;
            padding: .55rem .6rem;
            margin-bottom: .44rem;
        }
        .status-main {
            font-weight: 800;
            color: #fff;
        }
        .status-detail {
            color: var(--muted);
            font-size: .7rem;
            overflow-wrap: anywhere;
        }
        .status-pill {
            border-radius: 999px;
            padding: .14rem .48rem;
            font-size: .62rem;
            font-weight: 900;
            white-space: nowrap;
        }
        .pill-ready, .pill-done {
            color: #07140d;
            background: var(--green);
            border: 1px solid rgba(255,255,255,.18);
        }
        .pill-active {
            color: #1b1400;
            background: var(--yellow);
            border: 1px solid rgba(255,255,255,.18);
        }
        .pill-pending, .pill-missing, .pill-empty {
            color: #d9dde3;
            background: #3a3a3a;
            border: 1px solid #505050;
        }
        .pill-blocked, .pill-bad {
            color: #fff;
            background: var(--red);
            border: 1px solid rgba(255,255,255,.18);
        }
        .stage-list {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: .48rem;
            margin: .7rem 0 .45rem 0;
        }
        .stage-item {
            border: 1px dashed #555;
            background: rgba(38, 38, 38, .92);
            border-radius: 7px;
            padding: .56rem .6rem;
            min-height: 4rem;
        }
        .stage-label {
            color: #fff;
            font-size: .76rem;
            font-weight: 850;
            line-height: 1.22;
        }
        .stage-state {
            color: var(--muted);
            font-size: .68rem;
            margin-top: .24rem;
        }
        .mode-card {
            border: 1px solid var(--line);
            background: rgba(44, 44, 44, .9);
            border-radius: 8px;
            padding: .85rem .95rem;
            min-height: 6.1rem;
        }
        .mode-card h4 {
            color: #fff;
            margin: 0 0 .3rem 0;
            font-size: .9rem;
        }
        .mode-card p {
            color: var(--muted);
            margin: 0;
            font-size: .78rem;
        }
        .ready {
            color: var(--green);
            font-weight: 800;
        }
        .missing, .blocked {
            color: var(--yellow);
            font-weight: 800;
        }
        .file-row {
            border: 1px solid var(--line);
            background: rgba(44, 44, 44, .9);
            border-radius: 7px;
            padding: .7rem .8rem;
            margin-bottom: .45rem;
        }
        .file-path {
            color: var(--muted);
            font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
            font-size: .74rem;
            overflow-wrap: anywhere;
        }
        div[data-testid="stMetricValue"] {
            color: #ffffff;
            font-size: 1.32rem;
            font-weight: 900;
        }
        [data-testid="stMetricLabel"] p {
            color: var(--muted) !important;
            font-size: .74rem;
            font-weight: 850;
        }
        .stButton > button {
            background: #dedede;
            border: 0;
            color: #090b0d;
            border-radius: 4px;
            font-weight: 900;
            min-height: 2.05rem;
            text-transform: none;
        }
        .stButton > button p {
            color: #090b0d;
            font-weight: 900;
        }
        .stButton > button:hover {
            background: #f3f3f3;
            color: #090b0d;
        }
        .stButton > button[kind="primary"] {
            background: #080d1a;
            border: 1px solid #1e3354;
            color: #ffffff;
        }
        .stButton > button[kind="primary"] p {
            color: #ffffff;
        }
        .stButton > button[kind="primary"]:hover {
            border-color: var(--cyan);
            color: #ffffff;
        }
        .stDownloadButton > button {
            border-radius: 4px;
            font-weight: 850;
            background: #101522 !important;
            color: #ffffff !important;
            border: 1px solid #263552 !important;
        }
        .stDownloadButton > button:hover {
            border-color: var(--cyan) !important;
            color: #ffffff !important;
        }
        label, [data-testid="stWidgetLabel"] p {
            color: #ffffff !important;
            font-weight: 850;
            font-size: .78rem;
        }
        div[data-baseweb="checkbox"] label,
        div[data-baseweb="checkbox"] p {
            color: #ffffff !important;
        }
        div[data-baseweb="input"],
        div[data-baseweb="base-input"],
        div[data-baseweb="select"] > div,
        .stTextInput input,
        .stNumberInput input,
        .stTextArea textarea {
            background: #171717 !important;
            color: #ffffff !important;
            border-color: #454545 !important;
        }
        .stTextInput input,
        .stNumberInput input,
        .stTextArea textarea {
            border-radius: 5px !important;
        }
        .stTextInput input:focus,
        .stNumberInput input:focus,
        .stTextArea textarea:focus {
            border-color: var(--cyan) !important;
            box-shadow: 0 0 0 1px var(--cyan) !important;
        }
        .stCheckbox [data-testid="stWidgetLabel"] p {
            font-size: .82rem;
        }
        .help-text {
            color: var(--muted);
            font-size: .75rem;
            margin: -.35rem 0 .55rem 0;
        }
        .run-note {
            border-left: 4px solid var(--cyan);
            background: rgba(24, 198, 255, .08);
            color: #dce9f2;
            border-radius: 5px;
            padding: .65rem .8rem;
            margin: .5rem 0 1rem 0;
            font-size: .84rem;
        }
        .stale-note {
            border-left: 4px solid var(--yellow);
            background: rgba(255, 201, 40, .1);
            color: #f5ead2;
            border-radius: 5px;
            padding: .65rem .8rem;
            margin: .5rem 0 1rem 0;
            font-size: .84rem;
        }
        .live-card {
            border: 1px solid var(--line);
            background: rgba(46, 46, 46, .92);
            border-radius: 8px;
            padding: .76rem .86rem;
            margin: .5rem 0 .75rem 0;
        }
        .live-title {
            color: #fff;
            font-weight: 850;
            font-size: .88rem;
            margin-bottom: .15rem;
        }
        .live-subtitle {
            color: var(--muted);
            font-size: .74rem;
        }
        .resource-ok {
            border-left: 4px solid var(--green);
            background: rgba(32, 223, 134, .09);
            padding: .65rem .8rem;
            color: #e8fff4;
            border-radius: 5px;
        }
        .resource-warn {
            border-left: 4px solid var(--yellow);
            background: rgba(255, 201, 40, .1);
            padding: .65rem .8rem;
            color: #fff5d7;
            border-radius: 5px;
        }
        .resource-bad {
            border-left: 4px solid var(--red);
            background: rgba(255, 86, 86, .1);
            padding: .65rem .8rem;
            color: #ffe5e5;
            border-radius: 5px;
        }
        [data-testid="stExpander"] {
            background: transparent;
            border: 1px solid var(--line-soft);
            border-radius: 7px;
        }
        [data-testid="stExpander"] summary p {
            color: #ffffff !important;
        }
        .stDataFrame {
            border: 1px solid var(--line-soft);
            border-radius: 7px;
            overflow: hidden;
        }
        [data-testid="stProgress"] > div {
            background: #161a22 !important;
            border: 1px solid #273143;
            border-radius: 4px;
        }
        .technical-log textarea {
            font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
        }
        @media (max-width: 900px) {
            .block-container {
                margin-top: .6rem;
                border-radius: 18px;
                padding: 1rem;
            }
            .workflow-strip,
            .stage-list {
                grid-template-columns: repeat(2, minmax(0, 1fr));
            }
        }
        @media (max-width: 620px) {
            .workflow-strip,
            .stage-list {
                grid-template-columns: 1fr;
            }
            button[data-baseweb="tab"] {
                min-width: 0;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


@st.cache_data(ttl=300, show_spinner=False)
def cached_runtime_checks():
    return runtime_checks()


def rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def sample_dataframe(rows: list[dict[str, str]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


def resolve_project_path(path_text: str) -> Path:
    path = Path(path_text).expanduser()
    return (PROJECT_ROOT / path).resolve() if not path.is_absolute() else path.resolve()


def pill(label: str, status: str) -> str:
    safe_status = status.lower().replace(" ", "-")
    return f'<span class="status-pill pill-{safe_status}">{label}</span>'


def render_workflow_strip(fastq_pairs: int, sample_rows: int, runtime_ready: bool, result_ready: bool) -> None:
    steps = [
        ("1", "Choose FASTQs", f"{fastq_pairs} paired files found" if fastq_pairs else "Waiting for a folder"),
        ("2", "Review samples", f"{sample_rows} rows in samples.csv" if sample_rows else "Sample sheet not written yet"),
        ("3", "Runtime", "Verified" if runtime_ready else "Check if needed"),
        ("4", "Run and collect", "Report available" if result_ready else "Results will appear here"),
    ]
    html = '<div class="workflow-strip">'
    for number, label, detail in steps:
        html += (
            '<div class="workflow-step">'
            f'<div class="number">Step {number}</div>'
            f'<div class="label">{label}</div>'
            f'<div class="detail">{detail}</div>'
            "</div>"
        )
    html += "</div>"
    st.markdown(html, unsafe_allow_html=True)


def render_status_line(title: str, detail: str, status: str, label: str | None = None) -> None:
    st.markdown(
        f"""
        <div class="status-line">
          <div>
            <div class="status-main">{title}</div>
            <div class="status-detail">{detail}</div>
          </div>
          {pill(label or status.title(), status)}
        </div>
        """,
        unsafe_allow_html=True,
    )


def run_text_command(command: list[str], timeout: int = 8) -> tuple[int, str, str]:
    try:
        completed = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return completed.returncode, completed.stdout.strip(), completed.stderr.strip()
    except Exception as exc:
        return 1, "", str(exc)


def local_run_active(outdir: str) -> bool:
    outdir_path = resolve_project_path(outdir)
    state_file = outdir_path / "run_state.json"
    if state_file.exists():
        try:
            state = json.loads(state_file.read_text(encoding="utf-8", errors="replace"))
            return state.get("status") in {"starting", "running"}
        except json.JSONDecodeError:
            pass
    safe_outdir = outdir.replace("/", "_").replace("\\", "_").replace(":", "_") or "results"
    out_log = PROJECT_ROOT / "gui" / "logs" / f"local-run-{safe_outdir}.out.log"
    if not out_log.exists():
        return False
    text = out_log.read_text(encoding="utf-8", errors="replace")[-4000:]
    return "Completed at:" not in text and "ERROR ~" not in text and "Technical log:" not in text


def path_is_done(path: Path) -> bool:
    if path.is_file():
        return path.stat().st_size > 0
    if path.is_dir():
        return any(path.iterdir())
    return False


def friendly_stage_paths(outdir: str) -> list[tuple[str, tuple[Path, ...]]]:
    outdir_path = (PROJECT_ROOT / outdir).resolve() if not Path(outdir).is_absolute() else Path(outdir)
    stages = [
        (label, tuple(PROJECT_ROOT / rel_path for rel_path in rel_paths))
        for label, rel_paths in FRIENDLY_STAGE_FILES
    ]
    stages[-1] = ("Writing report", (PROJECT_ROOT / "_local_work" / "run_summary.html", outdir_path / "reports" / "run_summary.html"))
    stages.append(
        (
            "Complete",
            (
                outdir_path / "reports" / "run_summary.html",
                outdir_path / "run_dada2" / "seqtab_iseq.tsv",
                outdir_path / "run_dada2" / "ASV_mapped_table.tsv",
                outdir_path / "run_dada2" / "asv_to_cigar.tsv",
                outdir_path / "run_dada2" / "seqtab_cigar.tsv",
            ),
        )
    )
    return stages


EVENT_LABELS = {
    "prepare_inputs": "Preparing inputs",
    "dada2": "Running DADA2",
    "prepare_stage2": "Cleaning ASV table",
    "asv_mapping": "Mapping ASVs",
    "prepare_stage3": "Preparing CIGAR inputs",
    "cigar_check": "Checking CIGAR inputs",
    "asv_to_cigar": "Converting ASVs to CIGAR",
    "report": "Writing report",
}


def progress_event_snapshot(outdir: str) -> tuple[list[tuple[str, str]], int, int, str] | None:
    outdir_path = resolve_project_path(outdir)
    progress_file = outdir_path / "progress.jsonl"
    if not progress_file.exists():
        return None
    events = []
    for line in progress_file.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    if not events:
        return None
    completed = {event.get("stage") for event in events if event.get("status") == "complete"}
    failed = {event.get("stage") for event in events if event.get("status") in {"failed", "error"}}
    active = ""
    for event in reversed(events):
        if event.get("stage") in EVENT_LABELS and event.get("status") == "started":
            active = event["stage"]
            break
    states: list[tuple[str, str]] = []
    for stage, label in EVENT_LABELS.items():
        if stage in failed:
            state = "blocked"
        elif stage in completed:
            state = "done"
        elif stage == active:
            state = "active"
        else:
            state = "pending"
        states.append((label, state))
    current = "Complete" if len(completed.intersection(EVENT_LABELS)) == len(EVENT_LABELS) else EVENT_LABELS.get(active, "Ready to start")
    return states, len(completed.intersection(EVENT_LABELS)), len(EVENT_LABELS), current


def stage_snapshot(outdir: str, active: bool) -> tuple[list[tuple[str, str]], int, int, str]:
    progress = progress_event_snapshot(outdir)
    if progress is not None:
        return progress
    steps = friendly_stage_paths(outdir)
    if all(path_is_done(path) for path in steps[-1][1]):
        return [(label, "done") for label, _ in steps], len(steps), len(steps), "Complete"
    completed = 0
    first_open = None
    for index, (label, paths) in enumerate(steps):
        done = any(path_is_done(path) for path in paths) if label == "Writing report" else all(
            path_is_done(path) for path in paths
        )
        if done:
            completed += 1
        else:
            first_open = index
            break
    total = len(steps)
    states: list[tuple[str, str]] = []
    for index, (label, _) in enumerate(steps):
        if index < completed:
            state = "done"
        elif first_open == index and (active or completed > 0):
            state = "active"
        else:
            state = "pending"
        states.append((label, state))
    if completed == total:
        current = "Complete"
    elif active or completed > 0:
        current = steps[first_open or 0][0]
    else:
        current = "Ready to start"
    return states, completed, total, current


def render_stage_list(states: list[tuple[str, str]]) -> None:
    html = '<div class="stage-list">'
    for label, state in states:
        state_label = {"done": "Done", "active": "In progress", "pending": "Waiting"}.get(state, state.title())
        html += (
            '<div class="stage-item">'
            f'<div class="stage-label">{label}</div>'
            f'<div class="stage-state">{state_label}</div>'
            "</div>"
        )
    html += "</div>"
    st.markdown(html, unsafe_allow_html=True)


def newest_local_log() -> Path | None:
    candidates = [
        PROJECT_ROOT / st.session_state.get("run_outdir", "results") / "technical_log.txt",
        PROJECT_ROOT / st.session_state.get("run_outdir", "results") / "logs" / "technical_log.txt",
        PROJECT_ROOT / "_local_work" / "cigar_conversion.log",
        PROJECT_ROOT / "_local_work" / "postprocess_dada2.log",
        PROJECT_ROOT / "_local_work" / "dada2_pipeline.log",
    ]
    existing = [path for path in candidates if path.exists()]
    if not existing:
        return None
    return max(existing, key=lambda path: path.stat().st_mtime)


def file_tail(path: Path, lines: int = 80) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(text[-lines:])
    except Exception as exc:
        return f"Could not read {path}: {exc}"


def local_resources() -> dict[str, int | str] | None:
    if os.name == "nt":
        code, stdout, stderr = run_text_command(
            ["wsl", "bash", "-lc", "nproc && awk '/MemTotal/ {print $2 * 1024}' /proc/meminfo"],
            timeout=10,
        )
    else:
        code, stdout, stderr = run_text_command(
            ["bash", "-lc", "nproc && awk '/MemTotal/ {print $2 * 1024}' /proc/meminfo"],
            timeout=10,
        )
    if code != 0 or not stdout:
        return {"error": stderr or "resource check unavailable"}
    parts = stdout.splitlines()
    if len(parts) < 2:
        return {"error": stdout}
    try:
        return {"cpus": int(float(parts[0])), "memory_bytes": int(float(parts[1]))}
    except ValueError:
        return {"error": stdout}


def local_resource_message(resources: dict[str, int | str] | None, pairs: int, data_bytes: int) -> tuple[str, str]:
    if not resources or "error" in resources:
        return "resource-bad", f"Runtime check failed: {resources.get('error') if resources else 'not available'}"
    memory_bytes = int(resources["memory_bytes"])
    memory_gb = memory_bytes / 1024**3
    cpus = int(resources["cpus"])
    if pairs >= 50 and memory_gb < 64:
        return (
            "resource-bad",
            f"Runtime has {memory_gb:.1f} GB RAM and {cpus} CPUs. This full run has {pairs} samples; use a small test run first or increase available memory before running all samples.",
        )
    if data_bytes >= 5 * 1024**3 and memory_gb < 32:
        return (
            "resource-warn",
            f"Runtime has {memory_gb:.1f} GB RAM. This dataset is {format_bytes(data_bytes)}; full runs may fail unless more memory is available.",
        )
    return "resource-ok", f"Runtime has {memory_gb:.1f} GB RAM and {cpus} CPUs available."


def write_subset_sample_sheet(source_csv: Path, count: int) -> Path:
    rows = read_samples_csv(source_csv)
    if not rows:
        raise ValueError("No sample sheet rows found.")
    subset_path = PROJECT_ROOT / "_gui_samples_subset.csv"
    with subset_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=SAMPLE_FIELDS)
        writer.writeheader()
        for row in rows[:count]:
            writer.writerow({field: row.get(field, "") for field in SAMPLE_FIELDS})
    return subset_path


@st.fragment(run_every="8s")
def render_live_run_panel(outdir_text: str) -> None:
    active = local_run_active(outdir_text)
    states, done_steps, total_steps, current_stage = stage_snapshot(outdir_text, active)
    fraction = done_steps / total_steps if total_steps else 0
    active_text = "Local run in progress" if active else "No active local run detected"

    st.markdown(
        f"""
        <div class="live-card">
          <div class="live-title">{active_text}</div>
          <div class="live-subtitle">
            {"Current stage: " + current_stage if current_stage != "Complete" else "The run summary and output tables are ready."}
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.progress(fraction, text=f"{done_steps}/{total_steps} stages complete")
    render_stage_list(states)
    st.caption("Updates every 8 seconds while this page is open.")

    with st.expander("Show technical log", expanded=False):
        latest_log = newest_local_log()
        if latest_log:
            st.caption(f"Latest log: {rel(latest_log)}")
            st.code(file_tail(latest_log), language="text")
        else:
            st.info("No local run log yet.")


inject_css()

if "fastq_dir_text" not in st.session_state:
    st.session_state.fastq_dir_text = "data"
if "sample_csv_text" not in st.session_state:
    st.session_state.sample_csv_text = "samples.csv"
if "run_outdir" not in st.session_state:
    st.session_state.run_outdir = "results"
if "results_outdir" not in st.session_state:
    st.session_state.results_outdir = DEFAULT_RESULTS_DIR
if "include_pool" not in st.session_state:
    st.session_state.include_pool = False
if "runtime" not in st.session_state:
    st.session_state.runtime = DEFAULT_RUNTIME
if "runtime_checks" not in st.session_state:
    st.session_state.runtime_checks = []

checks = st.session_state.runtime_checks
runtime_checked = bool(checks)
ready = local_backend_ready(checks) if runtime_checked else True
fastq_dir = resolve_project_path(st.session_state.fastq_dir_text)
sample_csv = resolve_project_path(st.session_state.sample_csv_text)
scan = scan_fastqs(fastq_dir, include_pool_in_sample_id=st.session_state.include_pool)
current_rows = read_samples_csv(sample_csv)
result_report = resolve_project_path(st.session_state.results_outdir) / "reports" / "run_summary.html"

with st.sidebar:
    if LOGO.exists():
        st.image(str(LOGO), width="stretch")
    st.markdown("### SIMPLseq App")
    st.caption("Malaria amplicon workflow")
    st.divider()
    render_status_line(
        "Inputs",
        f"{len(scan.pairs)} paired FASTQs",
        "ready" if scan.pairs else "pending",
        "Ready" if scan.pairs else "Waiting",
    )
    render_status_line(
        "Sample sheet",
        f"{len(current_rows)} samples",
        "ready" if current_rows else "pending",
        "Ready" if current_rows else "Needed",
    )
    render_status_line(
        "Runtime",
        "Verified" if runtime_checked and ready else "Verified during install",
        "ready" if ready else "blocked",
        "Ready" if ready else "Needs setup",
    )
    render_status_line(
        "Results",
        rel(result_report) if result_report.exists() else "No report selected yet",
        "ready" if result_report.exists() else "pending",
        "Ready" if result_report.exists() else "Waiting",
    )
    st.divider()
    st.caption(str(PROJECT_ROOT))

hero_left, hero_right = st.columns([0.72, 0.28], vertical_alignment="center")
with hero_left:
    st.markdown(
        """
        <div class="hero">
          <div>
            <div class="eyebrow">SIMPLseq App</div>
            <div class="hero-title">From FASTQs to SIMPLseq results</div>
            <div class="hero-copy">
              A quiet browser interface for pairing reads, starting a run, watching progress, and reviewing the report.
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
with hero_right:
    if LOGO.exists():
        st.image(str(LOGO), width="stretch")

render_workflow_strip(len(scan.pairs), len(current_rows), ready, result_report.exists())

tab_inputs, tab_run, tab_results, tab_advanced = st.tabs(
    ["Inputs", "Run", "Results", "Advanced"]
)

with tab_inputs:
    st.subheader("Inputs")
    col_cfg, col_scan = st.columns([0.38, 0.62], gap="large")

    with col_cfg:
        st.markdown(
            """
            <div class="soft-panel">
              <div class="panel-title">Choose FASTQ folder</div>
              <div class="panel-subtitle">Select the folder that contains paired .fastq.gz files.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("Use data/", width="stretch"):
            st.session_state.fastq_dir_text = "data"

        fastq_dir_text = st.text_input(
            "FASTQ folder path",
            key="fastq_dir_text",
            help="Type a folder path. FASTQs are read from disk; they are not uploaded through the browser.",
        )
        st.caption("For large FASTQ datasets, use a folder path. Browser file upload is intentionally not used.")
        sample_csv_text = st.text_input("Sample sheet path", key="sample_csv_text")
        include_pool = st.checkbox(
            "Include amplicon pool in sample IDs",
            key="include_pool",
            help="Useful if the same biological label appears in more than one pool.",
        )
        absolute_paths = st.checkbox(
            "Write absolute FASTQ paths",
            value=False,
            help="Usually leave this off for portable project folders.",
        )

        fastq_dir = resolve_project_path(fastq_dir_text)
        sample_csv = resolve_project_path(sample_csv_text)

        if st.button("Write sample sheet", type="primary", width="stretch"):
            count, duplicates = write_samples_csv(
                fastq_dir,
                sample_csv,
                include_pool_in_sample_id=include_pool,
                absolute=absolute_paths,
            )
            if duplicates:
                st.error("Duplicate sample IDs: " + ", ".join(duplicates[:8]))
            else:
                st.success(f"Wrote {count} rows to {rel(sample_csv)}")

    with col_scan:
        scan = scan_fastqs(fastq_dir, include_pool_in_sample_id=include_pool)
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("FASTQ pairs", len(scan.pairs))
        m2.metric("MD5 files", scan.md5_files)
        m3.metric("Data size", format_bytes(scan.total_fastq_bytes))
        m4.metric("Missing pairs", len(scan.missing_r2) + len(scan.orphan_r2))

        if scan.duplicate_sample_ids:
            st.warning("Duplicate sample IDs detected. Use pool IDs or edit the sheet.")
        if scan.missing_r2:
            st.warning(f"Missing R2 for {len(scan.missing_r2)} R1 files.")
        if scan.orphan_r2:
            st.warning(f"Found {len(scan.orphan_r2)} R2 files without R1.")

        preview = [
            {
                "sample_id": pair.sample_id,
                "participant": pair.participant_id,
                "date": pair.collection_date,
                "replicate": pair.replicate,
                "pool": pair.amplicon_pool,
                "type": pair.sample_type,
            }
            for pair in scan.pairs[:100]
        ]
        if preview:
            st.dataframe(pd.DataFrame(preview), width="stretch", hide_index=True)
        else:
            st.info("No paired FASTQs found in this folder yet.")

    st.subheader("Sample sheet")
    current_rows = read_samples_csv(sample_csv)
    if current_rows:
        st.dataframe(sample_dataframe(current_rows), width="stretch", hide_index=True)
    else:
        st.info("No sample sheet found yet.")

with tab_run:
    st.subheader("Run")

    left_status, right_settings = st.columns([0.56, 0.44], gap="large")
    with left_status:
        resources = local_resources()
        resource_class, resource_text = local_resource_message(resources, len(scan.pairs), scan.total_fastq_bytes)
        st.markdown(f'<div class="{resource_class}">{resource_text}</div>', unsafe_allow_html=True)

        outdir_text = st.text_input("Output folder", key="run_outdir")
        render_live_run_panel(outdir_text)

    with right_settings:
        st.markdown(
            """
            <div class="soft-panel">
              <div class="panel-title">Run settings</div>
              <div class="panel-subtitle">Defaults are tuned for a normal local SIMPLseq run.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        clean_run = st.checkbox("Start from a clean run folder", value=True)
        test_run = st.checkbox("Small test run only", value=False)
        if test_run:
            test_count = st.number_input(
                "Number of samples",
                min_value=1,
                max_value=max(1, len(current_rows) or len(scan.pairs) or 1),
                value=min(4, max(1, len(current_rows) or len(scan.pairs) or 1)),
                step=1,
            )
            st.caption("Uses the first samples in the current sample sheet.")
        else:
            test_count = 0

        with st.expander("Advanced runtime options", expanded=False):
            dry_run = st.checkbox("Preview technical command only", value=False)
            if st.button("Run runtime check", width="stretch"):
                with st.spinner("Checking Python, R, DADA2, Nextflow, and MUSCLE..."):
                    st.session_state.runtime_checks = cached_runtime_checks()
                st.rerun()
            if checks:
                runtime_table = pd.DataFrame(
                    [{"check": c.name, "status": c.status, "detail": c.detail} for c in checks]
                )
                st.dataframe(runtime_table, width="stretch", hide_index=True)
            else:
                st.info("Runtime was verified during installation. Run this check only if something changes.")

        if dry_run:
            st.markdown(
                '<div class="run-note"><b>Preview mode is on.</b> The app will show the technical command but will not create results.</div>',
                unsafe_allow_html=True,
            )

        already_running = local_run_active(outdir_text)
        if already_running:
            st.info("A SIMPLseq run is already active. Wait for it to finish before starting another run.")

        run_button_label = "Preview command" if dry_run else "Run SIMPLseq"
        run_disabled = (not ready and not dry_run) or (already_running and not dry_run)
        if st.button(run_button_label, type="primary", disabled=run_disabled, width="stretch"):
            try:
                run_samples = st.session_state.sample_csv_text
                if test_run:
                    subset_path = write_subset_sample_sheet(sample_csv, int(test_count))
                    run_samples = rel(subset_path)
                completed = start_local_pipeline(
                    PROJECT_ROOT,
                    run_samples,
                    outdir_text,
                    st.session_state.runtime,
                    clean=clean_run,
                    dry_run=dry_run,
                )
                st.session_state["last_run_stdout"] = completed.stdout[-20000:]
                st.session_state["last_run_stderr"] = completed.stderr[-20000:]
                st.session_state["last_run_code"] = completed.returncode
                if not dry_run:
                    st.session_state["results_outdir"] = outdir_text
            except Exception as exc:
                st.session_state["last_run_stdout"] = ""
                st.session_state["last_run_stderr"] = str(exc)
                st.session_state["last_run_code"] = 1

    if "last_run_code" in st.session_state:
        status_code = st.session_state["last_run_code"]
        if status_code == 0 and dry_run:
            st.info("Preview finished. No pipeline was run and no output folder was created.")
        elif status_code == 0:
            st.success(f"SIMPLseq started. Watch the stage list above, then open Results for {outdir_text}.")
        else:
            st.error("The last action did not finish successfully. Technical details are available below.")
        with st.expander("Show technical log", expanded=status_code != 0):
            st.metric("Exit code", status_code)
            if st.session_state.get("last_run_stdout"):
                st.text_area("stdout", st.session_state["last_run_stdout"], height=180)
            if st.session_state.get("last_run_stderr"):
                st.text_area("stderr", st.session_state["last_run_stderr"], height=180)

with tab_results:
    st.subheader("Results")
    outdir = st.text_input("Results folder", key="results_outdir")
    outdir_path = (PROJECT_ROOT / outdir).resolve() if not Path(outdir).is_absolute() else Path(outdir)
    if outdir_path.exists():
        modified = outdir_path.stat().st_mtime
        sample_mtime = sample_csv.stat().st_mtime if sample_csv.exists() else 0
        if modified < sample_mtime:
            st.markdown(
                '<div class="stale-note"><b>Heads up:</b> this results folder is older than the current sample sheet, so it may be from an earlier run.</div>',
                unsafe_allow_html=True,
            )

    report_path = outdir_path / "reports" / "run_summary.html"
    if report_path.exists() and report_path.stat().st_size > 0:
        st.markdown(
            """
            <div class="soft-panel">
              <div class="panel-title">Run summary</div>
              <div class="panel-subtitle">Open the report in the app or download it for sharing.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        view_col, download_col = st.columns([0.7, 0.3], vertical_alignment="center")
        with view_col:
            preview_report = st.toggle("Show report preview", value=False)
        with download_col:
            with report_path.open("rb") as handle:
                st.download_button(
                    "Download report",
                    handle,
                    file_name=report_path.name,
                    width="stretch",
                    key="download-report-preview",
                )
        if preview_report:
            components.html(report_path.read_text(encoding="utf-8", errors="replace"), height=720, scrolling=True)
    else:
        st.info("No run summary report found for this results folder yet.")

    st.subheader("Output files")
    statuses = discover_outputs(PROJECT_ROOT, outdir)
    for item in statuses:
        cols = st.columns([0.18, 0.58, 0.12, 0.12], vertical_alignment="center")
        cols[0].markdown(f"**{item.label}**")
        cols[1].markdown(f"<div class='file-path'>{rel(item.path)}</div>", unsafe_allow_html=True)
        cols[2].markdown(f"<span class='{item.status}'>{item.status}</span>", unsafe_allow_html=True)
        cols[3].caption(format_bytes(item.size_bytes))
        if item.status == "ready":
            with item.path.open("rb") as handle:
                st.download_button(
                    f"Download {item.label}",
                    handle,
                    file_name=item.path.name,
                    key=f"download-{item.path.name}",
                    width="stretch",
                )
        st.divider()

with tab_advanced:
    st.subheader("Advanced")
    st.caption("These are not required for normal local runs.")

    with st.expander("Backend command-line mode"):
        st.write("For testing, debugging, automation, support, and developer work.")
        st.code(
            "\n".join(
                [
                    "simplseq scan --fastq-dir data --out samples.csv",
                    "simplseq check --samples samples.csv",
                    "simplseq run-headless --samples samples.csv --out results",
                    "simplseq status --out results",
                ]
            ),
            language="bash",
        )

    st.subheader("Planned downstream analysis")
    f1, f2 = st.columns(2, gap="large")
    with f1:
        st.markdown(
            """
            <div class="mode-card">
              <h4>dcifer</h4>
              <p>Planned relatedness analysis for polyclonal infections. Needs a clean SIMPLseq-to-allele table conversion first.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with f2:
        st.markdown(
            """
            <div class="mode-card">
              <h4>DINEMITES</h4>
              <p>Planned longitudinal analysis for new versus persistent infections. Needs participant/timepoint metadata.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
