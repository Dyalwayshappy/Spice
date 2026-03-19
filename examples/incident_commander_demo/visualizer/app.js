const ARTIFACT_PATH = "../demo_timeline.json";

const state = {
  artifact: null,
  cycleIndex: 1,
  view: "candidate",
  timerId: null,
};

const el = {
  title: document.getElementById("demoTitle"),
  summary: document.getElementById("demoSummary"),
  prevBtn: document.getElementById("prevBtn"),
  playBtn: document.getElementById("playBtn"),
  nextBtn: document.getElementById("nextBtn"),
  cycleRange: document.getElementById("cycleRange"),
  cycleLabel: document.getElementById("cycleLabel"),
  sceneLabel: document.getElementById("sceneLabel"),
  cycleBadges: document.getElementById("cycleBadges"),
  proofStrip: document.getElementById("proofStrip"),
  incidentState: document.getElementById("incidentStateContent"),
  currentCycle: document.getElementById("currentCycleContent"),
  decisionPanel: document.getElementById("decisionPanelContent"),
  proofPanel: document.getElementById("proofPanelContent"),
};

document.addEventListener("DOMContentLoaded", () => {
  init().catch((err) => {
    renderFatalError(err);
  });
});

async function init() {
  const artifact = await loadArtifact();
  state.artifact = artifact;

  initControls();
  render();
}

async function loadArtifact() {
  const response = await fetch(ARTIFACT_PATH, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Failed to load artifact (${response.status}) from ${ARTIFACT_PATH}`);
  }
  return response.json();
}

function initControls() {
  const total = totalCycles();
  el.cycleRange.max = String(total);
  el.cycleRange.value = "1";

  el.prevBtn.addEventListener("click", () => {
    setCycle(state.cycleIndex - 1);
  });
  el.nextBtn.addEventListener("click", () => {
    setCycle(state.cycleIndex + 1);
  });
  el.playBtn.addEventListener("click", () => {
    if (isPlaying()) {
      stopPlayer();
      return;
    }
    startPlayer();
  });
  el.cycleRange.addEventListener("input", (event) => {
    const target = /** @type {HTMLInputElement} */ (event.target);
    setCycle(Number.parseInt(target.value, 10));
  });

  const viewInputs = document.querySelectorAll("input[name='policyView']");
  viewInputs.forEach((input) => {
    input.addEventListener("change", (event) => {
      const target = /** @type {HTMLInputElement} */ (event.target);
      state.view = target.value === "baseline" ? "baseline" : "candidate";
      render();
    });
  });
}

function startPlayer() {
  stopPlayer();
  state.timerId = window.setInterval(() => {
    if (state.cycleIndex >= totalCycles()) {
      stopPlayer();
      return;
    }
    setCycle(state.cycleIndex + 1);
  }, 1200);
  syncPlayButton();
}

function stopPlayer() {
  if (state.timerId !== null) {
    window.clearInterval(state.timerId);
    state.timerId = null;
  }
  syncPlayButton();
}

function isPlaying() {
  return state.timerId !== null;
}

function syncPlayButton() {
  el.playBtn.textContent = isPlaying() ? "Pause" : "Play";
}

function setCycle(nextCycle) {
  const max = totalCycles();
  const clamped = Math.max(1, Math.min(max, Number.isFinite(nextCycle) ? nextCycle : 1));
  state.cycleIndex = clamped;
  el.cycleRange.value = String(clamped);
  render();
}

function totalCycles() {
  return state.artifact?.cycles?.length ?? 1;
}

function currentCycle() {
  const cycles = state.artifact?.cycles ?? [];
  const index = Math.max(0, Math.min(cycles.length - 1, state.cycleIndex - 1));
  return cycles[index];
}

function render() {
  const artifact = state.artifact;
  if (!artifact) {
    return;
  }
  const cycle = currentCycle();
  if (!cycle) {
    renderFatalError(new Error("Artifact has no cycles."));
    return;
  }

  el.title.textContent = artifact.title || "Incident Commander Timeline";
  el.summary.textContent = artifact.scenario_summary || "";
  el.cycleLabel.textContent = `Cycle ${cycle.cycle_index} / ${totalCycles()}`;
  el.sceneLabel.textContent = `Scene: ${cycle.scene_label || "n/a"}`;
  syncPlayButton();

  renderProofStrip(artifact);
  renderCycleBadges(cycle, artifact);
  renderIncidentState(cycle);
  renderCurrentCycle(cycle);
  renderDecisionPanel(cycle, artifact);
  renderProofPanel(artifact);
}

function renderCycleBadges(cycle, artifact) {
  const badges = [];

  if (cycle.divergence) {
    badges.push(badge("Divergence", "divergence"));
  }
  if (cycle.proactive) {
    badges.push(badge("Proactive Step", "proactive"));
  }
  if (cycle.cycle_index === artifact.divergent_cycle_after_rollback_failure) {
    badges.push(badge("Divergence Moment (rollback failure history)", "accent"));
  }
  if (cycle.cycle_index === artifact.proactive_request_hotfix_cycle) {
    badges.push(badge("Hotfix Follow-up Cycle", "accent"));
  }

  el.cycleBadges.innerHTML = badges.length
    ? badges.join("")
    : badge("No highlighted marker in this cycle", "muted");
}

function renderIncidentState(cycle) {
  const signal = cycle.observed_signal_summary || {};
  const stableForView = cycle.stable_after_cycle?.[state.view];
  const stableBaseline = cycle.stable_after_cycle?.baseline;
  const stableCandidate = cycle.stable_after_cycle?.candidate;

  el.incidentState.innerHTML = `
    <div class="status-badges">
      ${stabilityBadge("Baseline", stableBaseline, state.view === "baseline")}
      ${stabilityBadge("Candidate", stableCandidate, state.view === "candidate")}
    </div>
    <div class="kv-grid">
      ${kv("Service", signal.service)}
      ${kv("Severity", signal.severity)}
      ${kv("Error Rate", formatNumber(signal.error_rate))}
      ${kv("Latency P95 (ms)", formatNullable(signal.latency_p95_ms))}
      ${kv("Feature Flag Enabled", formatBoolean(signal.feature_flag_enabled))}
      ${kv("Recent Deploy", formatBoolean(signal.recent_deploy))}
      ${kv(`Stable After Cycle (${state.view})`, formatBoolean(stableForView))}
    </div>
  `;
}

function renderCurrentCycle(cycle) {
  const previousForView = cycle.previous_outcome_summary?.[state.view] ?? null;
  const otherView = state.view === "baseline" ? "candidate" : "baseline";
  const previousOther = cycle.previous_outcome_summary?.[otherView] ?? null;

  el.currentCycle.innerHTML = `
    <div class="kv-grid">
      ${kv("Observation ID", cycle.observation_id)}
      ${kv("Observation Type", cycle.observed_signal_summary?.observation_type)}
      ${kv(`Previous Outcome (${state.view})`, formatOutcomeSummary(previousForView))}
      ${kv(`Previous Outcome (${otherView})`, formatOutcomeSummary(previousOther))}
    </div>
  `;
}

function renderDecisionPanel(cycle, artifact) {
  const baselineAction = cycle.baseline_action;
  const candidateAction = cycle.candidate_action;
  const sequence =
    state.view === "baseline"
      ? artifact.baseline_replay_summary?.action_sequence_text
      : artifact.candidate_replay_summary?.action_sequence_text;

  const notes = [];
  if (cycle.cycle_index === artifact.divergent_cycle_after_rollback_failure) {
    notes.push("Divergence moment: candidate changes action after prior rollback failure.");
  }
  if (cycle.cycle_index === artifact.proactive_request_hotfix_cycle) {
    notes.push("Proactive step: candidate triggers one request_hotfix follow-up.");
  }
  if (!notes.length) {
    notes.push("No special narrative marker in this cycle.");
  }

  el.decisionPanel.innerHTML = `
    <div class="action-row">
      <div class="action-card ${state.view === "baseline" ? "selected" : ""}">
        <div class="action-label">Baseline</div>
        <div class="action-value">${escapeHtml(baselineAction)}</div>
      </div>
      <div class="action-card ${state.view === "candidate" ? "selected" : ""}">
        <div class="action-label">Candidate</div>
        <div class="action-value">${escapeHtml(candidateAction)}</div>
      </div>
    </div>
    <p class="note">${escapeHtml(notes.join(" "))}</p>
    <p class="sequence"><strong>${escapeHtml(state.view)} path:</strong> ${escapeHtml(
      sequence || "n/a"
    )}</p>
  `;
}

function renderProofPanel(artifact) {
  const proof = Boolean(artifact.proof_metric_candidate_lt_baseline);
  const proofClass = proof ? "proof-true" : "proof-false";

  el.proofPanel.innerHTML = `
    <div class="kv-grid">
      ${kv("Proof Target", artifact.proof_target)}
      ${kv("Baseline Cycles To Stable", formatNullable(artifact.baseline_cycles_to_stable, "not_reached"))}
      ${kv("Candidate Cycles To Stable", formatNullable(artifact.candidate_cycles_to_stable, "not_reached"))}
      ${kv("Divergent Cycle", formatNullable(artifact.divergent_cycle_after_rollback_failure, "none"))}
      ${kv("Proactive Hotfix Cycle", formatNullable(artifact.proactive_request_hotfix_cycle, "none"))}
      ${kv("Baseline Deterministic", formatBoolean(artifact.baseline_replay_summary?.deterministic))}
      ${kv("Candidate Deterministic", formatBoolean(artifact.candidate_replay_summary?.deterministic))}
    </div>
    <div class="proof-result ${proofClass}">
      proof_metric_candidate_lt_baseline = ${String(proof)}
    </div>
  `;
}

function renderProofStrip(artifact) {
  const proof = Boolean(artifact.proof_metric_candidate_lt_baseline);
  const cls = proof ? "proof-true" : "proof-false";
  const text = artifact.final_proof_summary || "Proof summary unavailable.";
  el.proofStrip.innerHTML = `
    <div class="proof-strip-inner ${cls}">
      ${escapeHtml(text)}
    </div>
  `;
}

function formatOutcomeSummary(outcome) {
  if (!outcome) {
    return "No previous outcome.";
  }
  const human = outcome.human_summary || "";
  const tech = `${outcome.status}, ${outcome.action}, err=${formatNumber(
    outcome.error_rate
  )}, p95=${formatNullable(outcome.latency_p95_ms)}`;
  return human ? `${human} (${tech})` : tech;
}

function renderFatalError(err) {
  const message = err instanceof Error ? err.message : String(err);
  el.summary.textContent =
    "Failed to load demo artifact. Run this page via a local HTTP server and regenerate demo_timeline.json if needed.";
  el.incidentState.innerHTML = `<p class="error">${escapeHtml(message)}</p>`;
  el.currentCycle.innerHTML = "";
  el.decisionPanel.innerHTML = "";
  el.proofPanel.innerHTML = "";
  el.cycleBadges.innerHTML = badge("Artifact load failed", "error");
  el.proofStrip.innerHTML = "";
}

function kv(label, value) {
  return `
    <div class="kv-row">
      <span class="kv-label">${escapeHtml(label)}</span>
      <span class="kv-value">${escapeHtml(value ?? "n/a")}</span>
    </div>
  `;
}

function badge(text, kind) {
  return `<span class="badge ${kind}">${escapeHtml(text)}</span>`;
}

function stabilityBadge(label, isStable, emphasize) {
  const stateLabel =
    isStable === null || isStable === undefined ? "Unknown" : isStable ? "Stable" : "Unstable";
  const stableClass =
    isStable === null || isStable === undefined ? "unknown" : isStable ? "stable" : "unstable";
  const selectedClass = emphasize ? "emphasize" : "";
  return `<span class="status-badge ${stableClass} ${selectedClass}">${escapeHtml(
    `${label}: ${stateLabel}`
  )}</span>`;
}

function formatNullable(value, fallback = "n/a") {
  return value === null || value === undefined ? fallback : String(value);
}

function formatNumber(value) {
  if (value === null || value === undefined) {
    return "n/a";
  }
  const num = Number(value);
  if (!Number.isFinite(num)) {
    return "n/a";
  }
  return num.toString();
}

function formatBoolean(value) {
  if (value === null || value === undefined) {
    return "n/a";
  }
  return value ? "true" : "false";
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}
