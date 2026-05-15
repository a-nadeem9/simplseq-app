const STAGES = [
  "prepare_inputs",
  "dada2",
  "prepare_stage2",
  "asv_mapping",
  "prepare_stage3",
  "cigar_check",
  "asv_to_cigar",
  "report"
];

const STAGE_LABELS = {
  prepare_inputs: "Checking sample sheet",
  dada2: "Running DADA2",
  prepare_stage2: "Cleaning ASV table",
  asv_mapping: "Mapping ASVs",
  prepare_stage3: "Preparing CIGAR inputs",
  cigar_check: "Checking CIGAR inputs",
  asv_to_cigar: "Converting ASVs to CIGAR",
  report: "Writing report"
};

const STORE_KEY = "simplseq.flask.settings";
const EMPTY_LOG_TEXT = "> Waiting for run.\n> Live progress appears here while SIMPLseq is active.";
let pollTimer = null;
let browseParent = "";
let scanInFlight = false;
let logInFlight = false;
let latestStatusPayload = null;
let lastRunStatus = "";
let completedRedirectKey = "";

function $(selector) {
  return document.querySelector(selector);
}

function text(node, value) {
  if (!node) return;
  node.textContent = value == null ? "" : String(value);
}

function terminalLineClass(line) {
  const trimmed = String(line || "").trim();
  if (trimmed.startsWith("[OK]")) return "log-ok";
  if (trimmed.startsWith("[WARN]") || trimmed.startsWith("WARN:")) return "log-warn";
  if (trimmed.startsWith("[ERROR]") || trimmed.startsWith("ERROR") || trimmed.includes("failed")) return "log-error";
  if (trimmed.startsWith(">")) return "log-muted";
  return "";
}

function renderTerminalLog(node, value) {
  if (!node) return;
  node.replaceChildren();
  const lines = String(value == null ? "" : value).split("\n");
  lines.forEach((line, index) => {
    const span = document.createElement("span");
    const lineClass = terminalLineClass(line);
    if (lineClass) span.className = lineClass;
    span.textContent = line;
    node.appendChild(span);
    if (index < lines.length - 1) node.appendChild(document.createTextNode("\n"));
  });
}

function getSettings() {
  try {
    return JSON.parse(localStorage.getItem(STORE_KEY) || "{}");
  } catch (_error) {
    return {};
  }
}

function normalizeDrivePath(value) {
  const raw = String(value || "").trim();
  const match = raw.match(/^([A-Za-z]):[\\/]?(.*)$/);
  if (!match) return raw;
  const drive = match[1].toLowerCase();
  const rest = match[2].replaceAll("\\", "/");
  return `/mnt/${drive}/${rest}`;
}

function normalizePathInput(selector) {
  const node = $(selector);
  if (node && node.value) node.value = normalizeDrivePath(node.value);
}

function normalizePathInputs() {
  ["#fastq-dir", "#samples-out", "#run-samples", "#outdir", "#results-outdir", "#browse-path"].forEach(normalizePathInput);
  syncPathTitles();
}

function syncPathTitles() {
  ["#fastq-dir", "#samples-out", "#run-samples", "#outdir", "#results-outdir"].forEach((selector) => {
    const node = $(selector);
    if (node) node.title = node.value || "";
  });
}

function saveSettings() {
  normalizePathInputs();
  const settings = {
    fastqDir: $("#fastq-dir").value,
    samplesOut: $("#samples-out").value,
    runSamples: $("#run-samples").value,
    outdir: $("#outdir").value,
    resultsOutdir: $("#results-outdir").value,
    cleanRun: $("#clean-run").checked,
    dryRun: $("#dry-run").checked,
    cpus: $("#cpus").value,
    memory: $("#memory").value
  };
  localStorage.setItem(STORE_KEY, JSON.stringify(settings));
}

function restoreSettings() {
  const settings = getSettings();
  if (settings.fastqDir) $("#fastq-dir").value = settings.fastqDir;
  if (settings.samplesOut) $("#samples-out").value = settings.samplesOut;
  if (settings.runSamples) $("#run-samples").value = settings.runSamples;
  if (settings.outdir) $("#outdir").value = settings.outdir;
  if (settings.resultsOutdir) $("#results-outdir").value = settings.resultsOutdir;
  if (typeof settings.cleanRun === "boolean") $("#clean-run").checked = settings.cleanRun;
  if (typeof settings.dryRun === "boolean") $("#dry-run").checked = settings.dryRun;
  if (settings.cpus != null) $("#cpus").value = settings.cpus;
  if (settings.memory != null) $("#memory").value = settings.memory;
  normalizePathInputs();
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, {
    headers: {"Content-Type": "application/json"},
    ...options
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || payload.ok === false) {
    throw new Error(payload.error || `Request failed: ${response.status}`);
  }
  return payload;
}

function postJson(url, body) {
  return fetchJson(url, {
    method: "POST",
    body: JSON.stringify(body)
  });
}

function setPill(node, label, status) {
  if (!node) return;
  node.classList.remove("ok", "warn", "bad");
  if (status) node.classList.add(status);
  text(node, label);
}

function payloadStatus(payload) {
  const state = payload?.state || {};
  const summary = payload?.summary || {};
  return state.status || summary.status || "pending";
}

function isActiveStatus(status) {
  return status === "starting" || status === "running";
}

function checkStatusReady() {
  return ($("#check-status")?.textContent || "").trim().toLowerCase() === "ready";
}

function stageClass(status) {
  if (status === "complete") return "complete";
  if (status === "started" || status === "running") return "running";
  if (status === "failed" || status === "error") return "failed";
  return "pending";
}

function stageStatusLabel(status) {
  const klass = stageClass(status);
  if (klass === "running") return "running";
  if (klass === "complete") return "complete";
  if (klass === "failed") return "failed";
  return "pending";
}

function compactTerminalLog(raw, statusPayload) {
  const value = String(raw || "").replace(/\r\n/g, "\n").trimEnd();
  const status = payloadStatus(statusPayload);
  if (!value) {
    return isActiveStatus(status)
      ? "> Starting SIMPLseq.\n> Live Nextflow progress will appear here."
      : EMPTY_LOG_TEXT;
  }

  const lines = value.split("\n");
  const nextflowStart = lines.findIndex((line) => {
    const trimmed = line.trim();
    return (
      trimmed.includes("N E X T F L O W") ||
      trimmed.startsWith("WARN:") ||
      trimmed.startsWith("Launching `") ||
      trimmed.startsWith("executor >") ||
      /^\[[0-9a-f]{2}\//i.test(trimmed)
    );
  });
  if (nextflowStart >= 0) {
    return lines.slice(nextflowStart).slice(-220).join("\n").trimEnd();
  }

  const filtered = lines.filter((line) => {
    const trimmed = line.trim();
    if (!trimmed) return false;
    if (trimmed.startsWith("[SIMPLseq/App]")) return false;
    if (trimmed.startsWith("[OK]")) return false;
    if (trimmed.startsWith("[WARN] Large/high-depth datasets")) return false;
    if (trimmed.startsWith("[SIMPLseq] preparing")) return false;
    if (trimmed.startsWith("[SIMPLseq] wrote runtime versions")) return false;
    if (trimmed.startsWith("[SIMPLseq] wrote input FASTQ MD5 table")) return false;
    return true;
  });
  const cleaned = filtered.length ? filtered : lines.slice(-40);
  return cleaned.slice(-180).join("\n").trimEnd() || EMPTY_LOG_TEXT;
}

function setStep(name, active) {
  const node = document.querySelector(`.step[data-step="${name}"]`);
  if (node) node.classList.toggle("is-active", active);
}

function selectTab(name) {
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.classList.toggle("is-active", tab.dataset.tab === name);
  });
  document.querySelectorAll(".tab-panel").forEach((panel) => {
    panel.classList.toggle("is-active", panel.id === `tab-${name}`);
  });
}

function setFolderMessage(message, className = "") {
  const node = $("#folder-message");
  if (!node) return;
  node.className = `field-help ${className}`.trim();
  text(node, message);
}

function row(cells) {
  const tr = document.createElement("tr");
  cells.forEach((value) => {
    const td = document.createElement("td");
    text(td, value);
    tr.appendChild(td);
  });
  return tr;
}

function emptyRow(colspan, message) {
  const tr = document.createElement("tr");
  const td = document.createElement("td");
  td.colSpan = colspan;
  td.className = "empty";
  text(td, message);
  tr.appendChild(td);
  return tr;
}

function renderScanPreview(items) {
  const tbody = $("#scan-preview");
  tbody.replaceChildren();
  if (!items.length) {
    tbody.appendChild(emptyRow(4, "No paired FASTQs found."));
    return;
  }
  items.forEach((item) => {
    tbody.appendChild(row([
      item.sample_id,
      item.participant_id,
      item.collection_date,
      item.replicate
    ]));
  });
}

function renderSamplePreview(items) {
  const tbody = $("#sample-preview");
  tbody.replaceChildren();
  if (!items.length) {
    tbody.appendChild(emptyRow(5, "No sample rows available."));
    return;
  }
  items.forEach((item) => {
    tbody.appendChild(row([
      item.sample_id,
      item.fastq_1,
      item.fastq_2,
      item.participant_id,
      item.collection_date
    ]));
  });
}

function renderWarnings(scan) {
  const box = $("#scan-warnings");
  box.replaceChildren();
  const notices = [];
  const pairCount = Number(scan.pair_count || 0);
  const totalBytes = Number(scan.total_fastq_bytes || 0);
  if (pairCount >= 50 || totalBytes >= 5 * 1024 * 1024 * 1024) {
    notices.push({
      className: "notice",
      text: "Large dataset detected. Full runs can require much more memory than a typical laptop. Run a small test first if this is a new setup."
    });
  }
  if (scan.duplicate_sample_ids && scan.duplicate_sample_ids.length) {
    notices.push({
      className: "notice bad",
      text: `Duplicate sample IDs: ${scan.duplicate_sample_ids.slice(0, 8).join(", ")}`
    });
  }
  if (scan.missing_r2 && scan.missing_r2.length) {
    notices.push({className: "notice", text: `Missing R2 files for ${scan.missing_r2.length} R1 files.`});
  }
  if (scan.orphan_r2 && scan.orphan_r2.length) {
    notices.push({className: "notice", text: `Found ${scan.orphan_r2.length} R2 files without R1.`});
  }
  notices.forEach((notice) => {
    const div = document.createElement("div");
    div.className = notice.className;
    text(div, notice.text);
    box.appendChild(div);
  });
}

async function scanFastqs() {
  if (scanInFlight) return;
  scanInFlight = true;
  saveSettings();
  setPill($("#scan-status"), "Scanning", "warn");
  $("#scan-button").disabled = true;
  try {
    const payload = await postJson("/api/scan", {
      fastq_dir: $("#fastq-dir").value,
      samples_out: $("#samples-out").value,
      include_pool_in_sample_id: false,
      absolute_paths: true,
      write_samples: true
    });
    text($("#metric-pairs"), payload.pair_count);
    text($("#metric-size"), payload.total_fastq_size);
    text($("#metric-md5"), payload.md5_files);
    text($("#metric-missing"), payload.missing_pairs);
    text($("#sample-sheet-title"), payload.samples_relative || payload.samples_out);
    renderScanPreview(payload.preview || []);
    renderSamplePreview(payload.sample_preview || []);
    renderWarnings(payload);
    $("#run-samples").value = $("#samples-out").value;
    if (payload.samples_written) {
      setPill($("#scan-status"), `${payload.pair_count} pairs`, payload.pair_count ? "ok" : "warn");
      setPill($("#sample-sheet-status"), `Wrote ${payload.sample_rows_written} rows`, payload.pair_count ? "ok" : "warn");
      setStep("review", true);
    } else if (payload.duplicate_sample_ids && payload.duplicate_sample_ids.length) {
      setPill($("#scan-status"), "Duplicates", "bad");
      setPill($("#sample-sheet-status"), "Not written", "bad");
    } else {
      setPill($("#scan-status"), "No pairs", "warn");
      setPill($("#sample-sheet-status"), "Empty", "warn");
    }
    saveSettings();
  } catch (error) {
    setPill($("#scan-status"), "Scan failed", "bad");
    renderWarnings({duplicate_sample_ids: [error.message]});
  } finally {
    scanInFlight = false;
    $("#scan-button").disabled = false;
  }
}

function renderChecks(checks) {
  const tbody = $("#check-table");
  tbody.replaceChildren();
  if (!checks.length) {
    tbody.appendChild(emptyRow(3, "No checks returned."));
    return;
  }
  checks.forEach((item) => {
    const tr = document.createElement("tr");
    const name = document.createElement("td");
    const status = document.createElement("td");
    const detail = document.createElement("td");
    const badge = document.createElement("span");
    badge.className = `check-badge ${item.status === "ok" ? "ok" : item.status === "warn" ? "warn" : "bad"}`;
    text(name, item.name);
    text(badge, item.status);
    text(detail, item.detail);
    status.appendChild(badge);
    tr.append(name, status, detail);
    tbody.appendChild(tr);
  });
}

async function runCheck() {
  saveSettings();
  setPill($("#check-status"), "Checking", "warn");
  $("#check-button").disabled = true;
  try {
    const payload = await postJson("/api/check", {samples: $("#run-samples").value, outdir: $("#outdir").value});
    renderChecks(payload.checks || []);
    await loadLog({silent: true});
    if (payload.failed) {
      setPill($("#check-status"), `${payload.failed} need attention`, "bad");
    } else {
      setPill($("#check-status"), "Ready", "ok");
      setStep("runtime", true);
      latestStatusPayload = await refreshStatus();
      await refreshProgress(latestStatusPayload);
    }
  } catch (error) {
    setPill($("#check-status"), "Check failed", "bad");
    renderChecks([{name: "Runtime check", status: "missing", detail: error.message}]);
  } finally {
    $("#check-button").disabled = false;
  }
}

function runPayload() {
  return {
    samples: $("#run-samples").value,
    outdir: $("#outdir").value,
    clean: $("#clean-run").checked,
    dry_run: $("#dry-run").checked,
    cpus: Number($("#cpus").value || 0),
    memory: $("#memory").value
  };
}

async function startRun() {
  saveSettings();
  $("#run-button").disabled = true;
  $("#run-message").className = "inline-message";
  text($("#run-message"), $("#dry-run").checked ? "Starting preview..." : "Starting run...");
  try {
    const payload = await postJson("/api/run", runPayload());
    $("#results-outdir").value = $("#outdir").value;
    saveSettings();
    text($("#run-message"), payload.dry_run ? "Preview started. Loading command from disk state." : "Run started. Progress will update from disk.");
    $("#run-message").classList.add("ok");
    setPill($("#run-state-pill"), payload.dry_run ? "Preview" : "Running", payload.dry_run ? "warn" : "ok");
    lastRunStatus = "starting";
    renderStages([], {status: "starting"}, {status: "starting"});
    setStep("collect", true);
    startPolling();
    setTimeout(refreshAllRunState, 1200);
  } catch (error) {
    text($("#run-message"), error.message);
    $("#run-message").classList.add("bad");
  } finally {
    $("#run-button").disabled = false;
  }
}

function openFolderModal() {
  const modal = $("#folder-modal");
  if (!modal) return;
  modal.classList.add("is-open");
  modal.setAttribute("aria-hidden", "false");
}

function closeFolderModal() {
  const modal = $("#folder-modal");
  if (!modal) return;
  modal.classList.remove("is-open");
  modal.setAttribute("aria-hidden", "true");
}

async function openFallbackFolderBrowser() {
  $("#browse-path").value = $("#fastq-dir").value || $("#browse-path").value || ".";
  openFolderModal();
  await loadBrowse($("#browse-path").value);
}

async function chooseFastqFolder() {
  const button = $("#browse-button");
  const oldLabel = button ? button.textContent : "";
  if (button) {
    button.disabled = true;
    text(button, "Opening...");
  }
  setFolderMessage("Opening folder picker...");
  const pickerHint = setTimeout(() => {
    setFolderMessage("Native folder picker is open. If you do not see it, check behind this browser or on the taskbar/Dock.", "ok");
  }, 1500);
  try {
    const payload = await postJson("/api/select-folder", {initial: $("#fastq-dir").value});
    if (payload.selected && payload.path) {
      $("#fastq-dir").value = payload.path;
      $("#browse-path").value = payload.path;
      saveSettings();
      setFolderMessage("Folder selected. Click Scan folder when ready.", "ok");
      return;
    }
    setFolderMessage("Folder selection was cancelled.");
  } catch (error) {
    setFolderMessage("Native folder picker was not available. Opening the manual browser instead.", "warn");
    await openFallbackFolderBrowser();
  } finally {
    clearTimeout(pickerHint);
    if (button) {
      button.disabled = false;
      text(button, oldLabel || "Choose folder");
    }
  }
}

function renderStages(events, summary, state) {
  const statusByStage = {};
  const messageByStage = {};
  const staleState = state?.status === "stale";
  STAGES.forEach((stage) => {
    statusByStage[stage] = "pending";
  });
  events.forEach((event) => {
    if (!STAGES.includes(event.stage)) return;
    if (staleState && ["started", "running"].includes(event.status)) return;
    statusByStage[event.stage] = event.status;
    if (event.message) messageByStage[event.stage] = event.message;
  });
  if (state && state.status === "failed") {
    const current = summary.current_stage;
    if (STAGES.includes(current) && statusByStage[current] !== "complete") {
      statusByStage[current] = "failed";
    }
  }

  const list = $("#stage-list");
  list.replaceChildren();
  STAGES.forEach((stage) => {
    const li = document.createElement("li");
    const status = statusByStage[stage];
    li.className = stageClass(status);
    const dot = document.createElement("span");
    dot.className = "stage-dot";
    const label = document.createElement("span");
    label.className = "stage-label";
    text(label, messageByStage[stage] || STAGE_LABELS[stage] || stage);
    const stateNode = document.createElement("span");
    stateNode.className = "stage-status";
    text(stateNode, stageStatusLabel(status));
    li.append(dot, label, stateNode);
    list.appendChild(li);
  });

  const completed = summary.completed_stages || 0;
  const total = summary.total_stages || STAGES.length;
  const runStatus = state?.status || summary.status || "pending";
  const percent = runStatus === "dry_run" || runStatus === "complete" ? 100 : Math.round((completed / Math.max(total, 1)) * 100);
  const progressFill = $("#progress-fill");
  const progressBar = progressFill?.parentElement;
  const globalFill = $("#global-progress-fill");
  const globalBar = globalFill?.parentElement;
  [progressBar, globalBar].forEach((bar) => {
    if (!bar) return;
    bar.classList.remove("is-running", "is-complete", "is-failed");
    if (isActiveStatus(runStatus)) bar.classList.add("is-running");
    if (runStatus === "complete" || runStatus === "dry_run") bar.classList.add("is-complete");
    if (runStatus === "failed") bar.classList.add("is-failed");
  });
  if (progressFill) progressFill.style.width = `${percent}%`;
  if (globalFill) globalFill.style.width = `${percent}%`;
  text($("#progress-percent"), `${percent}%`);
  text($("#pipeline-percent"), `${percent}%`);
  let pipelineLabel = checkStatusReady() ? "Ready" : "Idle";
  let pipelineClass = checkStatusReady() ? "is-ready" : "is-idle";
  let showPipelinePercent = false;
  if (isActiveStatus(runStatus)) {
    pipelineLabel = "Running";
    pipelineClass = "is-running";
    showPipelinePercent = true;
  }
  if (runStatus === "complete") pipelineLabel = "Complete";
  if (runStatus === "complete") {
    pipelineClass = "is-complete";
    showPipelinePercent = true;
  }
  if (runStatus === "dry_run") {
    pipelineLabel = "Preview ready";
    pipelineClass = "is-preview";
  }
  if (runStatus === "failed") {
    pipelineLabel = "Failed";
    pipelineClass = "is-failed";
    showPipelinePercent = true;
  }
  if (!["pending", "starting", "running", "complete", "dry_run", "failed"].includes(runStatus)) {
    pipelineLabel = "Check status";
    pipelineClass = "is-unknown";
  }
  text($("#pipeline-label"), pipelineLabel);

  const pipelineStatus = $(".pipeline-status");
  if (pipelineStatus) {
    pipelineStatus.classList.remove("is-idle", "is-ready", "is-running", "is-complete", "is-preview", "is-failed", "is-unknown", "has-percent");
    pipelineStatus.classList.add(pipelineClass);
    if (showPipelinePercent) pipelineStatus.classList.add("has-percent");
  }
  const current = summary.current_stage && summary.current_stage !== "pending" ? summary.current_stage : "";
  let currentLabel = current ? (STAGE_LABELS[current] || current) : "No active run";
  if (runStatus === "dry_run") currentLabel = "Preview ready";
  if (runStatus === "complete") currentLabel = "Run complete";
  if (runStatus === "failed") currentLabel = "Run failed";
  if (runStatus === "stale") currentLabel = "Check run status";
  text($("#current-stage"), currentLabel);
}

function renderStatus(payload) {
  const state = payload.state || {};
  const summary = payload.summary || {};
  const status = state.status || summary.status || "pending";
  let pillStatus = "";
  if (status === "complete" || status === "dry_run") pillStatus = "ok";
  if (status === "failed") pillStatus = "bad";
  if (status === "running" || status === "starting") pillStatus = "ok";
  setPill($("#run-state-pill"), status, pillStatus);
  $("#run-button").disabled = Boolean(payload.active && !$("#dry-run").checked);
}

async function refreshStatus() {
  const out = encodeURIComponent($("#outdir").value || "results");
  const payload = await fetchJson(`/api/status?out=${out}`);
  renderStatus(payload);
  return payload;
}

async function refreshProgress(statusPayload = null) {
  const out = encodeURIComponent($("#outdir").value || "results");
  const payload = await fetchJson(`/api/progress?out=${out}`);
  const state = statusPayload ? statusPayload.state : {};
  renderStages(payload.events || [], payload.summary || {}, state || {});
  return payload;
}

async function refreshResults() {
  const out = $("#results-outdir").value || $("#outdir").value || "results";
  const payload = await fetchJson(`/api/results?out=${encodeURIComponent(out)}`);
  updateBundleButton(payload);
  const list = $("#results-list");
  list.replaceChildren();
  if (!payload.files || !payload.files.length) {
    const div = document.createElement("div");
    div.className = "notice";
    text(div, "No result manifest entries found.");
    list.appendChild(div);
    return;
  }
  renderResultsDashboard(payload, list);
}

function updateBundleButton(payload) {
  const button = $("#download-bundle");
  if (!button) return;
  button.disabled = !payload.bundle_ready || !payload.bundle_url;
  button.dataset.url = payload.bundle_url || "";
  button.title = button.disabled ? "Output bundle is available after result files are ready." : "Download report and core result tables as a zip.";
}

function resultAction(url, label, primary = false) {
  const link = document.createElement("a");
  link.href = url;
  if (label.startsWith("Open")) link.target = "_blank";
  const button = document.createElement("button");
  if (primary) button.className = "primary";
  text(button, label);
  link.appendChild(button);
  return link;
}

function resultPill(item) {
  const pill = document.createElement("span");
  const ready = item && item.status === "ready";
  pill.className = `status-pill ${ready ? "ok" : "warn"}`;
  text(pill, ready ? "ready" : "pending");
  return pill;
}

function disabledResultAction(label) {
  const button = document.createElement("button");
  button.disabled = true;
  text(button, label);
  return button;
}

function resultSummaryCard(label, value, detail, item = null) {
  const card = document.createElement("div");
  card.className = "results-summary-card";
  const badge = document.createElement("div");
  badge.className = "results-summary-badge";
  text(badge, value);
  const meta = document.createElement("div");
  const title = document.createElement("strong");
  text(title, label);
  const description = document.createElement("span");
  text(description, detail);
  meta.append(title, description);
  card.append(badge, meta);
  if (item) card.appendChild(resultPill(item));
  return card;
}

function resultTableRow(item) {
  const row = document.createElement("tr");
  if (item.status !== "ready") row.className = "is-pending";
  const fileCell = document.createElement("td");
  fileCell.className = "result-file-cell";
  const title = document.createElement("strong");
  text(title, item.label);
  const detail = document.createElement("span");
  text(detail, item.relative_path);
  fileCell.append(title, detail);

  const sizeCell = document.createElement("td");
  text(sizeCell, item.status === "ready" ? item.size : "--");

  const actionsCell = document.createElement("td");
  const actions = document.createElement("div");
  actions.className = "result-actions";
  if (item.view_url) actions.appendChild(resultAction(item.view_url, "Open"));
  if (item.download_url) actions.appendChild(resultAction(item.download_url, "Download"));
  if (!item.view_url && !item.download_url) actions.appendChild(resultPill(item));
  actionsCell.appendChild(actions);

  row.append(fileCell, sizeCell, actionsCell);
  return row;
}

function resultTable(files, emptyText) {
  const section = document.createElement("section");
  section.className = "results-table-section";
  const wrap = document.createElement("div");
  wrap.className = "results-table-wrap";
  const table = document.createElement("table");
  table.className = "results-table";
  const thead = document.createElement("thead");
  thead.innerHTML = "<tr><th>Table</th><th>Size</th><th></th></tr>";
  const tbody = document.createElement("tbody");
  if (!files.length) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 3;
    cell.className = "empty";
    text(cell, emptyText);
    row.appendChild(cell);
    tbody.appendChild(row);
  } else {
    files.forEach((item) => tbody.appendChild(resultTableRow(item)));
  }
  table.append(thead, tbody);
  wrap.appendChild(table);
  section.appendChild(wrap);
  return section;
}

function renderResultsDashboard(payload, list) {
  const report = payload.report;
  const coreFiles = payload.core_files || [];

  const dashboard = document.createElement("div");
  dashboard.className = "results-dashboard";

  const overview = document.createElement("section");
  overview.className = "results-overview";
  const reportBlock = document.createElement("div");
  reportBlock.className = "results-report";
  const reportText = document.createElement("div");
  const reportTitle = document.createElement("h3");
  text(reportTitle, "Run report");
  const reportDetail = document.createElement("span");
  text(reportDetail, report ? report.relative_path : "reports/run_summary.html");
  reportText.append(reportTitle, reportDetail);
  const reportActions = document.createElement("div");
  reportActions.className = "result-actions";
  if (report && report.view_url) reportActions.appendChild(resultAction(report.view_url, "Open report"));
  if (report && report.download_url) reportActions.appendChild(resultAction(report.download_url, "Download"));
  if (!report || report.status !== "ready") reportActions.appendChild(resultPill(report));
  reportBlock.append(reportText, reportActions);

  const count = document.createElement("div");
  count.className = "results-count";
  const countValue = document.createElement("strong");
  text(countValue, `${payload.ready_counts?.core || 0}/${coreFiles.length}`);
  const countLabel = document.createElement("span");
  text(countLabel, "tables ready");
  count.append(countValue, countLabel);
  overview.append(reportBlock, count);

  const tableHeader = document.createElement("div");
  tableHeader.className = "results-section-heading";
  const heading = document.createElement("h3");
  text(heading, "Download tables");
  const subheading = document.createElement("span");
  text(subheading, "Primary SIMPLseq output tables");
  tableHeader.append(heading, subheading);

  dashboard.append(overview, tableHeader, resultTable(coreFiles, "Core result tables are not listed yet."));

  list.appendChild(dashboard);
}

async function refreshAllRunState() {
  try {
    const previousStatus = lastRunStatus;
    const status = await refreshStatus();
    latestStatusPayload = status;
    await refreshProgress(status);
    await refreshResults();
    await loadLog({silent: true, statusPayload: status});
    const currentStatus = payloadStatus(status);
    const wasRunning = isActiveStatus(previousStatus);
    if ((currentStatus === "complete" || currentStatus === "dry_run") && wasRunning) {
      const state = status.state || {};
      const key = `${$("#outdir").value || "results"}:${state.completed_at || currentStatus}`;
      if (completedRedirectKey !== key) {
        completedRedirectKey = key;
        $("#results-outdir").value = $("#outdir").value || $("#results-outdir").value;
        saveSettings();
        await refreshResults();
        selectTab("results");
        saveSettings();
      }
    }
    lastRunStatus = currentStatus;
    const active = Boolean(status.active);
    if (!active && pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
    return status;
  } catch (_error) {
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
    return null;
  }
}

function startPolling() {
  if (pollTimer) return;
  pollTimer = setInterval(refreshAllRunState, 3000);
}

async function loadLog() {
  const options = arguments[0] || {};
  if (logInFlight) return;
  logInFlight = true;
  const out = encodeURIComponent($("#outdir").value || "results");
  const logNode = $("#technical-log");
  const statusPayload = options.statusPayload || latestStatusPayload;
  const shouldStick = logNode
    ? logNode.scrollTop + logNode.clientHeight >= logNode.scrollHeight - 36
    : false;
  try {
    const status = payloadStatus(statusPayload);
    const hasRunState = Boolean(statusPayload?.state?.status);
    if (!hasRunState && !isActiveStatus(status) && status !== "complete" && status !== "failed" && status !== "dry_run") {
      renderTerminalLog(logNode, EMPTY_LOG_TEXT);
      return;
    }
    const payload = await fetchJson(`/api/logs?out=${out}&max_bytes=120000`);
    renderTerminalLog(logNode, compactTerminalLog(payload.text, statusPayload));
    if (shouldStick && logNode) {
      logNode.scrollTop = logNode.scrollHeight;
    }
  } catch (error) {
    if (!options.silent) {
      renderTerminalLog(logNode, error.message);
    }
  } finally {
    logInFlight = false;
  }
}

function renderCommonPaths(paths) {
  const box = $("#common-paths");
  if (!box) return;
  box.replaceChildren();
  paths.forEach((item) => {
    const button = document.createElement("button");
    text(button, item.label);
    button.title = item.path;
    button.addEventListener("click", () => {
      $("#fastq-dir").value = item.path;
      $("#browse-path").value = item.path;
      saveSettings();
      loadBrowse(item.path);
    });
    box.appendChild(button);
  });
}

function resetInstalledPath(selector, appRoot, fallback) {
  const node = $(selector);
  if (!node || !appRoot || !node.value) return;
  const normalizedValue = node.value.replaceAll("\\", "/").toLowerCase();
  const normalizedRoot = appRoot.replaceAll("\\", "/").toLowerCase();
  if (normalizedValue.startsWith(normalizedRoot)) {
    node.value = fallback;
  }
}

async function loadHealth() {
  const payload = await fetchJson("/api/health");
  renderCommonPaths(payload.common_paths || []);
  if (payload.workspace_root && $("#workspace-root")) {
    text($("#workspace-root"), payload.workspace_root);
  }
  resetInstalledPath("#fastq-dir", payload.app_root, "data");
  resetInstalledPath("#samples-out", payload.app_root, "samples.csv");
  resetInstalledPath("#run-samples", payload.app_root, "samples.csv");
  resetInstalledPath("#outdir", payload.app_root, "results");
  resetInstalledPath("#results-outdir", payload.app_root, "results");
  if (!$("#browse-path").value) {
    $("#browse-path").value = $("#fastq-dir").value || payload.workspace_root || ".";
  }
  saveSettings();
}

async function loadBrowse(path) {
  const payload = await fetchJson(`/api/browse?path=${encodeURIComponent(path || $("#browse-path").value || ".")}`);
  $("#browse-path").value = payload.path;
  browseParent = payload.parent || "";
  const list = $("#browse-list");
  list.replaceChildren();
  const current = document.createElement("div");
  current.className = "browse-row";
  const meta = document.createElement("div");
  const title = document.createElement("strong");
  text(title, "Use this folder");
  const detail = document.createElement("span");
  text(detail, `${payload.path} | ${payload.pair_count || 0} pairs`);
  meta.append(title, detail);
  const action = document.createElement("button");
  text(action, "Select");
  action.addEventListener("click", () => {
    $("#fastq-dir").value = payload.path;
    saveSettings();
    setFolderMessage("Folder selected. Click Scan folder when ready.", "ok");
    closeFolderModal();
  });
  current.append(meta, action);
  list.appendChild(current);

  if (!payload.exists || payload.is_dir === false) {
    const div = document.createElement("div");
    div.className = "notice bad";
    text(div, "Folder is not available.");
    list.appendChild(div);
    return;
  }

  (payload.directories || []).forEach((item) => {
    const div = document.createElement("div");
    div.className = "browse-row";
    const info = document.createElement("div");
    const name = document.createElement("strong");
    text(name, item.name);
    const details = document.createElement("span");
    text(details, `${item.path} | ${item.fastq_files} FASTQ files`);
    info.append(name, details);
    const button = document.createElement("button");
    text(button, "Open");
  button.addEventListener("click", () => {
      $("#browse-path").value = item.path;
      loadBrowse(item.path);
    });
    div.append(info, button);
    list.appendChild(div);
  });
}

function bindEvents() {
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      selectTab(tab.dataset.tab);
      saveSettings();
    });
  });
  document.querySelectorAll("input").forEach((input) => {
    input.addEventListener("change", saveSettings);
  });
  $("#scan-button").addEventListener("click", scanFastqs);
  $("#check-button").addEventListener("click", runCheck);
  $("#run-button").addEventListener("click", startRun);
  $("#refresh-status").addEventListener("click", refreshAllRunState);
  $("#refresh-results").addEventListener("click", () => {
    $("#results-outdir").value = $("#outdir").value || $("#results-outdir").value;
    saveSettings();
    refreshResults();
  });
  $("#download-bundle").addEventListener("click", () => {
    const url = $("#download-bundle").dataset.url;
    if (url) window.location.href = url;
  });
  $("#load-log").addEventListener("click", loadLog);
  $("#browse-button").addEventListener("click", chooseFastqFolder);
  $("#browse-parent").addEventListener("click", () => {
    if (browseParent) loadBrowse(browseParent);
  });
  $("#browse-path").addEventListener("change", () => loadBrowse($("#browse-path").value));
  const folderClose = $(".folder-modal__close");
  if (folderClose) folderClose.addEventListener("click", closeFolderModal);
  const folderScrim = $(".folder-modal__scrim");
  if (folderScrim) folderScrim.addEventListener("click", closeFolderModal);
  $("#dry-run").addEventListener("change", () => {
    text($("#run-button"), $("#dry-run").checked ? "Preview command" : "Start run");
    saveSettings();
  });
  $("#outdir").addEventListener("change", () => {
    $("#results-outdir").value = $("#outdir").value;
    saveSettings();
    refreshAllRunState();
  });
  $("#samples-out").addEventListener("change", () => {
    $("#run-samples").value = $("#samples-out").value;
    saveSettings();
  });
}

async function init() {
  restoreSettings();
  bindEvents();
  selectTab("inputs");
  text($("#run-button"), $("#dry-run").checked ? "Preview command" : "Start run");
  try {
    await loadHealth();
  } catch (_error) {
    renderCommonPaths([]);
  }
  const status = await refreshAllRunState();
  if (status?.active) selectTab("run");
}

init();
