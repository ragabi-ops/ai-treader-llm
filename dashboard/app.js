"use strict";

const pollEveryMs = 2000;
const historyLimit = 150;
const pipelineStages = [
  ["collecting", "Collect"],
  ["validating_context", "Context"],
  ["inference", "Infer"],
  ["validating_output", "Validate"],
  ["persisting", "Persist"],
  ["evaluating", "Evaluate"],
  ["complete", "Complete"],
];

const history = { gpu: [], vram: [], cpu: [], memory: [] };
let lastObservedAt = null;
let requestRunning = false;

const $ = (id) => document.getElementById(id);
const safe = (value, fallback = "—") => value === null || value === undefined || value === "" ? fallback : String(value);
const clamp = (value, low = 0, high = 100) => Math.min(high, Math.max(low, Number(value) || 0));

function bytes(value) {
  if (!Number.isFinite(value)) return "—";
  const units = ["B", "KiB", "MiB", "GiB", "TiB"];
  let size = value;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) { size /= 1024; unit += 1; }
  return `${size >= 10 || unit === 0 ? size.toFixed(0) : size.toFixed(1)} ${units[unit]}`;
}

function duration(seconds) {
  if (!Number.isFinite(seconds)) return "—";
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s}s`;
  const minutes = Math.floor(s / 60);
  if (minutes < 60) return `${minutes}m ${s % 60}s`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ${minutes % 60}m`;
  const days = Math.floor(hours / 24);
  return `${days}d ${hours % 24}h`;
}

function timeOnly(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function shortHash(value, length = 12) {
  if (!value) return "—";
  return value.length > length ? `${value.slice(0, length)}…` : value;
}

function titleCase(value) {
  if (!value) return "Unavailable";
  return String(value).replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function setMeter(id, value) { $(id).style.width = `${clamp(value)}%`; }

function setBadge(element, label, kind) {
  element.textContent = label;
  element.className = `badge badge-${kind}`;
}

function statusKind(status) {
  if (["healthy", "ready", "running", "succeeded", "complete"].includes(status)) return "success";
  if (["degraded", "queued", "idle"].includes(status)) return "warning";
  if (["offline", "failed", "cancelled"].includes(status)) return "error";
  return "muted";
}

function renderSummary(data) {
  const status = data.summary?.status || "offline";
  const pill = $("overall-pill");
  pill.className = `status-pill status-${status}`;
  $("overall-label").textContent = titleCase(status);
  $("connection-label").textContent = "Live telemetry";
  $("observed-at").textContent = timeOnly(data.observed_at);
  $("host-name").textContent = safe(data.host?.hostname);
  lastObservedAt = data.observed_at ? new Date(data.observed_at) : null;
  const reasons = data.summary?.reasons || [];
  $("attention-copy").textContent = reasons.length ? reasons.join(" · ") : "No operational warnings";
  $("attention-copy").className = reasons.length ? "" : "attention-copy-healthy";
  $("attention").style.borderLeftColor = status === "healthy" ? "var(--green)" : status === "offline" ? "var(--red)" : "var(--amber)";
}

function renderMetrics(data) {
  const gpu = data.gpu?.devices?.[0];
  if (gpu) {
    $("gpu-state").textContent = "available";
    $("gpu-util").textContent = safe(gpu.utilization_gpu_percent);
    $("gpu-temp").textContent = `${safe(gpu.temperature_c)} °C`;
    $("gpu-power").textContent = `${safe(gpu.power_draw_w)} W`;
    $("gpu-name").textContent = safe(gpu.name);
    $("vram-used").textContent = (gpu.memory_used_mib / 1024).toFixed(1);
    $("vram-total").textContent = `of ${(gpu.memory_total_mib / 1024).toFixed(1)} GiB`;
    $("vram-percent").textContent = `${safe(gpu.memory_percent)}%`;
    setMeter("gpu-util-meter", gpu.utilization_gpu_percent);
    setMeter("vram-meter", gpu.memory_percent);
  } else {
    $("gpu-state").textContent = "unavailable";
    ["gpu-util", "vram-used"].forEach((id) => $(id).textContent = "—");
    setMeter("gpu-util-meter", 0);
    setMeter("vram-meter", 0);
  }
  const inference = data.inference || {};
  $("inference-state").textContent = safe(inference.health);
  $("active-requests").textContent = safe(inference.active_requests, "0");
  $("inference-latency").textContent = `${safe(inference.latency_ms)} ms health`;
  const generationRate = inference.metrics?.["llamacpp:predicted_tokens_seconds"];
  $("inference-rate").textContent = Number.isFinite(generationRate) ? `${generationRate.toFixed(1)} tok/s gen` : "— tok/s gen";

  const host = data.host || {};
  $("cpu-util").textContent = safe(host.cpu_percent);
  $("cpu-count").textContent = host.cpu_count ? `${host.cpu_count} threads` : "—";
  $("memory-percent").textContent = `${safe(host.memory?.percent)}% RAM`;
  $("load-average").textContent = `load ${safe(host.load_average?.[0])}`;
  setMeter("cpu-meter", host.cpu_percent);
}

function renderStageRail(currentStage) {
  const rail = $("stage-rail");
  rail.replaceChildren();
  const currentIndex = pipelineStages.findIndex(([stage]) => stage === currentStage);
  pipelineStages.forEach(([stage, label], index) => {
    const node = document.createElement("div");
    node.className = `stage ${index < currentIndex ? "stage-complete" : ""} ${index === currentIndex ? "stage-current" : ""}`;
    const bar = document.createElement("span");
    bar.className = "stage-bar";
    const text = document.createElement("span");
    text.textContent = label;
    node.append(bar, text);
    rail.append(node);
  });
}

function renderPipeline(data) {
  const pipeline = data.pipeline || {};
  const empty = $("pipeline-empty");
  const content = $("pipeline-content");
  if (!pipeline.connected) {
    empty.hidden = false;
    content.hidden = true;
    setBadge($("pipeline-badge"), "Unavailable", "muted");
  } else {
    empty.hidden = true;
    content.hidden = false;
    setBadge($("pipeline-badge"), titleCase(pipeline.status), pipeline.stale ? "warning" : statusKind(pipeline.status));
    const work = pipeline.work || {};
    $("work-title").textContent = [work.symbol, work.horizon].filter(Boolean).join(" · ") || "Pipeline work item";
    $("pipeline-age").textContent = pipeline.stale ? `${duration(pipeline.age_seconds)} · stale` : duration(pipeline.age_seconds);
    $("run-id").textContent = safe(pipeline.run_id);
    $("listing-id").textContent = safe(work.listing_id);
    $("as-of").textContent = safe(work.as_of_timestamp);
    $("replay-mode").textContent = titleCase(work.replay_mode);
    $("attempt").textContent = safe(pipeline.attempt);
    $("pipeline-progress").textContent = pipeline.progress ? `${pipeline.progress.completed}/${pipeline.progress.total} · ${pipeline.progress.percent}%` : "—";
    $("pipeline-message").textContent = safe(pipeline.message, "No operator-safe message supplied.");
    renderStageRail(pipeline.stage);
  }

  const active = (data.inference?.slots || []).find((slot) => slot.processing);
  if (active) {
    $("runtime-work-label").textContent = pipeline.connected ? "Attributed generation" : "Unattributed inference request";
    $("runtime-work-detail").textContent = `Slot ${safe(active.id)} · task ${safe(active.task_id)} · ${safe(active.prompt_tokens_processed, "0")}/${safe(active.prompt_tokens, "—")} prompt tokens · ${safe(active.decoded_tokens, "0")} decoded`;
  } else {
    $("runtime-work-label").textContent = "Idle";
    $("runtime-work-detail").textContent = "No generation is running.";
  }
}

function pushHistory(key, value) {
  history[key].push(Number.isFinite(value) ? value : null);
  if (history[key].length > historyLimit) history[key].shift();
}

function pathFor(values, width = 420, height = 72) {
  if (!values.length) return "";
  const denominator = Math.max(1, values.length - 1);
  let last = 0;
  return values.map((raw, index) => {
    const value = raw === null ? last : clamp(raw);
    last = value;
    const x = index * width / denominator;
    const y = height - value * height / 100;
    return `${index ? "L" : "M"}${x.toFixed(2)},${y.toFixed(2)}`;
  }).join(" ");
}

function renderSparkline(id, values, color) {
  const svg = $(id);
  svg.replaceChildren();
  for (const y of [18, 36, 54]) {
    const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
    line.setAttribute("x1", "0"); line.setAttribute("x2", "420"); line.setAttribute("y1", String(y)); line.setAttribute("y2", String(y));
    line.setAttribute("class", "grid-line");
    svg.append(line);
  }
  const path = pathFor(values);
  if (!path) return;
  const area = document.createElementNS("http://www.w3.org/2000/svg", "path");
  area.setAttribute("d", `${path} L420,72 L0,72 Z`);
  area.setAttribute("fill", color);
  area.setAttribute("class", "area");
  const line = document.createElementNS("http://www.w3.org/2000/svg", "path");
  line.setAttribute("d", path);
  line.setAttribute("stroke", color);
  line.setAttribute("class", "line");
  svg.append(area, line);
}

function renderCharts(data) {
  const gpu = data.gpu?.devices?.[0];
  pushHistory("gpu", gpu?.utilization_gpu_percent);
  pushHistory("vram", gpu?.memory_percent);
  pushHistory("cpu", data.host?.cpu_percent);
  pushHistory("memory", data.host?.memory?.percent);
  const specs = [
    ["gpu", "chart-gpu", "chart-gpu-value", "#34d4f4"],
    ["vram", "chart-vram", "chart-vram-value", "#a78bfa"],
    ["cpu", "chart-cpu", "chart-cpu-value", "#f4b860"],
    ["memory", "chart-memory", "chart-memory-value", "#42d392"],
  ];
  specs.forEach(([key, chartId, valueId, color]) => {
    renderSparkline(chartId, history[key], color);
    const value = history[key].at(-1);
    $(valueId).textContent = value === null || value === undefined ? "—%" : `${value.toFixed(1)}%`;
  });
}

function renderDeployment(data) {
  const deployment = data.deployment || {};
  const artifact = deployment.model_artifact || {};
  const model = data.inference?.model || {};
  $("model-name").textContent = safe(model.id || artifact.repository);
  const params = model.parameters ? `${(model.parameters / 1e9).toFixed(2)}B` : "—";
  $("model-shape").textContent = `${params} · ${safe(model.quantization)} · ${safe(model.context_size)} ctx`;
  $("model-hash").textContent = shortHash(artifact.sha256, 18);
  $("model-hash").title = safe(artifact.sha256, "");
  $("model-revision").textContent = shortHash(artifact.revision, 18);
  $("model-revision").title = safe(artifact.revision, "");
  const digest = deployment.runtime_image?.split("@sha256:")[1];
  $("runtime-digest").textContent = digest ? `sha256:${shortHash(digest, 16)}` : "—";
  $("runtime-digest").title = safe(deployment.runtime_image, "");
  $("repo-commit").textContent = safe(deployment.repository_commit);
  setBadge($("repo-state"), deployment.repository_dirty ? "Dirty checkout" : "Pinned checkout", deployment.repository_dirty ? "warning" : "success");

  const host = data.host || {};
  $("host-os").textContent = safe(deployment.os);
  $("host-kernel").textContent = safe(host.kernel);
  $("host-uptime").textContent = `${duration(host.uptime_seconds)} uptime`;
  $("host-memory").textContent = `${bytes(host.memory?.used_bytes)} / ${bytes(host.memory?.total_bytes)} · ${safe(host.memory?.percent)}%`;
  const disk = (data.storage || []).find((item) => item.path === "/data");
  $("data-disk").textContent = disk ? `${bytes(disk.used_bytes)} / ${bytes(disk.total_bytes)} · ${safe(disk.percent)}%` : "—";
  $("docker-version").textContent = `${safe(deployment.docker_version)} · Compose ${safe(deployment.compose_version)}`;
  const container = data.container || {};
  $("container-state").textContent = `${titleCase(container.status)} · ${titleCase(container.health)} · ${safe(container.restart_count, "0")} restarts`;
}

function renderTraining(data) {
  const training = data.training || {};
  if (!training.connected) {
    $("training-empty").hidden = false;
    $("training-content").hidden = true;
    setBadge($("training-badge"), "Unavailable", "muted");
    return;
  }
  $("training-empty").hidden = true;
  $("training-content").hidden = false;
  setBadge($("training-badge"), titleCase(training.status), training.stale ? "warning" : statusKind(training.status));
  $("training-meter").style.width = `${clamp(training.progress?.percent)}%`;
  $("training-run").textContent = safe(training.run_id);
  $("training-stage").textContent = titleCase(training.stage);
  $("training-dataset").textContent = safe(training.dataset_id);
  $("training-step").textContent = training.step !== null && training.total_steps !== null ? `${training.step}/${training.total_steps}` : "—";
  $("training-loss").textContent = training.loss === null ? "—" : Number(training.loss).toFixed(4);
  $("training-eta").textContent = duration(training.eta_seconds);
}

function renderEvents(data) {
  const list = $("events");
  list.replaceChildren();
  const events = (data.events || []).slice(0, 12);
  if (!events.length) {
    const item = document.createElement("li");
    item.className = "event";
    item.textContent = "No state transitions recorded.";
    list.append(item);
    return;
  }
  events.forEach((event) => {
    const item = document.createElement("li");
    item.className = `event event-${safe(event.level, "info")}`;
    const marker = document.createElement("span"); marker.className = "event-marker";
    const category = document.createElement("span"); category.className = "event-category"; category.textContent = safe(event.category);
    const message = document.createElement("span"); message.className = "event-message"; message.textContent = safe(event.message);
    const timestamp = document.createElement("time"); timestamp.dateTime = safe(event.timestamp, ""); timestamp.textContent = timeOnly(event.timestamp);
    item.append(marker, category, message, timestamp);
    list.append(item);
  });
}

function render(data) {
  renderSummary(data);
  renderMetrics(data);
  renderPipeline(data);
  renderCharts(data);
  renderDeployment(data);
  renderTraining(data);
  renderEvents(data);
}

function renderOffline(error) {
  $("overall-pill").className = "status-pill status-offline";
  $("overall-label").textContent = "Dashboard offline";
  $("connection-label").textContent = "Telemetry request failed";
  $("attention-copy").textContent = error instanceof Error ? error.message : "Unable to load telemetry";
  $("attention").style.borderLeftColor = "var(--red)";
}

async function refresh() {
  if (requestRunning) return;
  requestRunning = true;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 4000);
  try {
    const response = await fetch("/api/v1/status", { cache: "no-store", signal: controller.signal });
    if (!response.ok) throw new Error(`Telemetry returned HTTP ${response.status}`);
    render(await response.json());
  } catch (error) {
    renderOffline(error);
  } finally {
    clearTimeout(timeout);
    requestRunning = false;
  }
}

setInterval(() => {
  if (!lastObservedAt) return;
  const age = Math.max(0, (Date.now() - lastObservedAt.getTime()) / 1000);
  $("connection-label").textContent = age > 8 ? `Telemetry stale · ${duration(age)}` : "Live telemetry";
}, 1000);

refresh();
setInterval(refresh, pollEveryMs);
