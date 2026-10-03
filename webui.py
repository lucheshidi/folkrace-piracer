"""
Web console page for the PiRacer Pro debug tooling.

Kept separate from streamer.py, which owns the HTTP plumbing, so the request
handling does not disappear under a few hundred lines of markup. Everything in
this file is presentation only: the server re-validates every value that arrives,
so nothing here is a security boundary.

Which controls exist at all is decided by the launch flags, not by the browser --
the page is served to everyone on the LAN, so a tab only appears when the person
at the terminal asked for it.

All user-facing text is English, by request.
"""

from typing import Optional

from webcontrol import MODE_AUTO, MODE_MANUAL, MODE_PAUSED, RemoteState

# How long the ARM button must be held. Guards against a stray click or tap.
ARM_HOLD_MS = 2000

# Drive commands are pushed at 10 Hz, leaving eight heartbeats inside the 800 ms
# deadman window.
SEND_INTERVAL_MS = 100

# Parameter changes are batched so dragging a slider does not emit a request per pixel.
TUNE_DEBOUNCE_MS = 250


def _tabs_html(allow_tuning: bool, allow_manual: bool, default_tab: str) -> str:
    if not (allow_tuning or allow_manual):
        return ""

    buttons = []
    if allow_tuning:
        buttons.append(('tuning', 'Tuning'))
    if allow_manual:
        buttons.append(('manual', 'Manual Drive'))

    parts = ['<nav class="tabs">']
    for name, label in buttons:
        active = ' active' if name == default_tab else ''
        parts.append(f'<button class="tab{active}" data-panel="{name}">{label}</button>')
    parts.append('</nav>')
    return "".join(parts)


def _panels_html(allow_tuning: bool, allow_manual: bool, default_tab: str) -> str:
    parts = []

    if allow_tuning:
        active = ' active' if default_tab == 'tuning' else ''
        parts.append(f'''
        <section class="panel{active}" data-panel="tuning">
            <div class="toolbar">
                <button class="btn" id="btn-reset-pid">Reset PID State</button>
                <button class="btn" id="btn-reset-defaults">Reset to Defaults</button>
                <button class="btn" id="btn-snippet">Copy as config.py</button>
            </div>
            <div class="statusline" id="tune-status"></div>
            <div id="tune-groups"></div>
            <pre class="snippet" id="snippet" hidden></pre>
            <p class="hint">Changes apply immediately, even while the car is driving.
            The car keeps following the line &mdash; this tab never takes over steering.</p>
        </section>''')

    if allow_manual:
        active = ' active' if default_tab == 'manual' else ''
        parts.append(f'''
        <section class="panel{active}" data-panel="manual">
            <div class="warning">
                Manual control is a <strong>test-only</strong> tool. A competition run is always
                autonomous. The car stops by itself if these commands stop arriving.
            </div>

            <div class="toolbar">
                <button class="btn go arm" id="btn-arm">
                    <span class="fill"></span>
                    <span class="txt">HOLD TO ARM (2s)</span>
                </button>
                <button class="btn go" id="btn-start">START AUTONOMOUS</button>
                <button class="btn danger" id="btn-stop">&#9632; STOP</button>
            </div>
            <div class="statusline" id="manual-status"></div>

            <div id="manual-controls">
                <div class="row">
                    <label for="ctl-steer">Steering</label>
                    <input type="range" id="ctl-steer" min="-1" max="1" step="0.02" value="0">
                    <span class="num" id="disp-steer">0.00</span>
                </div>
                <div class="row">
                    <label for="ctl-thr">Throttle</label>
                    <input type="range" id="ctl-thr" min="-0.25" max="0.4" step="0.01" value="0">
                    <span class="num" id="disp-thr">0.00</span>
                </div>
                <p class="hint">Release a slider and that axis returns to zero.
                Keys: <kbd>W</kbd>/<kbd>S</kbd> throttle, <kbd>A</kbd>/<kbd>D</kbd> steering,
                <kbd>Space</kbd> emergency stop, hold <kbd>M</kbd> to arm.</p>

                <div class="pad">
                    <button class="btn pad-btn" data-axis="steering" data-value="-1">&#9664; LEFT</button>
                    <button class="btn pad-btn" data-axis="steering" data-value="1">RIGHT &#9654;</button>
                    <button class="btn pad-btn" data-axis="throttle" data-value="max">&#9650; FORWARD</button>
                    <button class="btn pad-btn" data-axis="throttle" data-value="min">&#9660; REVERSE</button>
                </div>
            </div>
        </section>''')

    return "".join(parts)


_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>PiRacer Pro - Debug Console</title>
<style>
    :root { color-scheme: dark; }
    * { box-sizing: border-box; }
    [hidden] { display: none !important; }
    body {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
        background-color: #121212;
        color: #fff;
        margin: 0;
        padding: 16px;
    }
    .container {
        max-width: 900px;
        margin: 0 auto;
        background: #1e1e1e;
        border-radius: 12px;
        padding: 20px;
        box-shadow: 0 8px 24px rgba(0,0,0,0.5);
        text-align: center;
    }
    h1 { font-size: 1.35rem; margin: 0 0 12px; color: #00e676; letter-spacing: 1px; }

    .topbar { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; justify-content: center; }
    .badge { padding: 4px 10px; border-radius: 12px; font-size: 0.78rem; font-weight: bold; letter-spacing: 0.5px; white-space: nowrap; }
    .badge.mode-auto { background: #2e7d32; }
    .badge.mode-paused { background: #8a6100; }
    .badge.mode-manual { background: #b3261e; }
    .badge.live { background: #2e7d32; }
    .btn.live-off { background: #333; }
    .telem { font-size: 0.78rem; color: #9e9e9e; font-variant-numeric: tabular-nums; }

    .deadman { height: 6px; background: #2a2a2a; border-radius: 3px; overflow: hidden; margin: 12px 0 0; }
    .deadman > i { display: block; height: 100%; width: 0; background: #00e676; }

    .stream-box {
        position: relative; margin: 15px 0; border: 2px solid #333; border-radius: 8px;
        overflow: hidden; background: #000; min-height: 240px;
        display: flex; justify-content: center; align-items: center;
    }
    img { width: 100%; height: auto; max-height: 70vh; object-fit: contain; display: block; }

    .tabs { display: flex; gap: 6px; margin: 16px 0 14px; }
    .tab {
        flex: 1; padding: 10px; background: #262626; color: #bbb;
        border: 1px solid #333; border-radius: 8px;
        font-family: inherit; font-size: 0.9rem; font-weight: 600; cursor: pointer;
    }
    .tab.active { background: #00e676; color: #08210f; border-color: #00e676; }

    .panel { display: none; text-align: left; }
    .panel.active { display: block; }

    .toolbar { display: flex; flex-wrap: wrap; gap: 8px; margin: 12px 0; }
    .btn {
        padding: 10px 14px; border-radius: 8px; border: 1px solid #333; background: #262626;
        color: #eee; font-family: inherit; font-size: 0.85rem; font-weight: 600; cursor: pointer;
    }
    .btn:hover { background: #303030; }
    .btn.danger { background: #b3261e; border-color: #b3261e; color: #fff; }
    .btn.danger:hover { background: #c9302a; }
    .btn.go { background: #2e7d32; border-color: #2e7d32; color: #fff; }
    .btn.go:hover { background: #37913b; }
    .btn[disabled] { opacity: 0.4; cursor: not-allowed; }

    .arm { position: relative; overflow: hidden; padding: 14px 22px; font-size: 0.95rem; }
    .arm .fill { position: absolute; top: 0; bottom: 0; left: 0; width: 0; background: rgba(255,255,255,0.3); pointer-events: none; }
    .arm .txt { position: relative; z-index: 1; }

    .statusline { min-height: 1.2em; font-size: 0.8rem; color: #9e9e9e; margin-bottom: 10px; }
    .statusline.bad { color: #ff6b60; }
    .statusline.good { color: #00e676; }

    .warning {
        background: #3a1f1c; border-left: 4px solid #b3261e; border-radius: 4px;
        padding: 10px 12px; font-size: 0.8rem; color: #f0c9c5; line-height: 1.5;
    }
    .hint { font-size: 0.75rem; color: #777; line-height: 1.6; }
    kbd {
        background: #2b2b2b; border: 1px solid #444; border-radius: 4px;
        padding: 1px 5px; font-size: 0.72rem; font-family: inherit;
    }

    .group { margin-bottom: 18px; }
    .group h2 {
        font-size: 0.78rem; text-transform: uppercase; letter-spacing: 1px; color: #00e676;
        margin: 0 0 10px; padding-bottom: 6px; border-bottom: 1px solid #2c2c2c;
    }
    .row { display: grid; grid-template-columns: 140px 1fr 72px; gap: 10px; align-items: center; margin-bottom: 8px; }
    .row label { font-size: 0.85rem; color: #ddd; }
    .row .note { grid-column: 2 / -1; font-size: 0.72rem; color: #777; margin: -4px 0 6px; }
    input[type=range] { width: 100%; accent-color: #00e676; touch-action: none; }
    input[type=number], select {
        width: 100%; background: #141414; border: 1px solid #333; color: #fff;
        border-radius: 6px; padding: 5px; font-family: inherit; font-size: 0.8rem;
    }
    .num { font-size: 0.85rem; color: #00e676; font-variant-numeric: tabular-nums; text-align: right; }

    .pad { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 12px; }
    .pad-btn { min-height: 72px; font-size: 0.95rem; touch-action: none; user-select: none; -webkit-user-select: none; }
    .pad-btn.held { background: #00e676; color: #08210f; border-color: #00e676; }

    .snippet {
        background: #101010; border: 1px solid #333; border-radius: 8px; padding: 12px;
        font-size: 0.75rem; color: #b9f6ca; overflow-x: auto; white-space: pre; margin-top: 10px;
    }

    #manual-controls.off { opacity: 0.35; pointer-events: none; }

    .footer { margin-top: 16px; font-size: 0.82rem; color: #888; }

    @media (max-width: 520px) {
        .container { padding: 14px; }
        .row { grid-template-columns: 96px 1fr 58px; gap: 8px; }
        .row label { font-size: 0.78rem; }
    }
</style>
</head>
<body>
<div class="container">
    <h1>PiRacer Pro - Debug Console</h1>

    <div class="topbar">
        <span class="badge mode-__INITIAL_MODE__" id="mode-badge">__INITIAL_MODE_TEXT__</span>
        <span class="badge live" id="stream-badge">&#9679; LIVE STREAMING</span>
        <span class="telem" id="telemetry">&mdash;</span>
    </div>
    <div class="deadman" id="deadman" hidden><i id="deadman-fill"></i></div>

    <div class="stream-box">
        <img src="/stream.mjpg" alt="Live camera stream">
    </div>

    __TABS__
    __PANELS__

    <div class="footer">Waveshare PiRacer Pro AI Kit &nbsp;|&nbsp; Chalmers Folkrace</div>
</div>

<script>
"use strict";

const HAS_REMOTE = __HAS_REMOTE__;
const ARM_HOLD_MS = __ARM_HOLD_MS__;
const SEND_INTERVAL_MS = __SEND_INTERVAL_MS__;
const TUNE_DEBOUNCE_MS = __TUNE_DEBOUNCE_MS__;

const STATE = { mode: "__INITIAL_MODE__", params: {}, schema: [], limits: {}, telemetry: {}, deadman: null };
const TARGET = { steering: 0, throttle: 0 };

const $ = (id) => document.getElementById(id);

/* ------------------------------------------------------------------ *
 * Networking
 * ------------------------------------------------------------------ */

async function postJSON(url, body) {
    const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        cache: "no-store"
    });
    let data = null;
    try { data = await res.json(); } catch (e) { data = null; }
    // A rejected request carries the true state so a stale page resynchronises
    // instead of retrying against a mode the car is not actually in.
    if (data && data.state) applyState(data.state);
    return { ok: res.ok, data: data };
}

async function pollState() {
    try {
        const res = await fetch("/api/state", { cache: "no-store" });
        if (res.ok) applyState(await res.json());
    } catch (e) { /* keep the last known state */ }
}

/* ------------------------------------------------------------------ *
 * State rendering
 * ------------------------------------------------------------------ */

function applyState(s) {
    const previous = STATE.mode;
    STATE.mode = s.mode;
    STATE.params = s.params || {};
    STATE.schema = s.schema || [];
    STATE.limits = s.limits || {};
    STATE.telemetry = s.telemetry || {};
    STATE.deadman = s.deadman_remaining_ms;

    if (previous !== s.mode) {
        // Never let a stale axis value survive a mode change -- that is exactly
        // how a car lurches the moment it re-arms.
        TARGET.steering = 0;
        TARGET.throttle = 0;
        if (s.mode === "manual") startSending(); else stopSending();
        // An in-progress ARM hold belongs to the mode we just left. This must stay
        // inside the "mode actually changed" branch: cancelling on every render
        // would abort the hold on the next 500 ms poll, and ARM would never fire.
        if (holdTimer !== null) cancelHold();
    }

    renderModeBadge();
    renderTelemetry();
    renderDeadman();
    renderManualLimits();
    if (!groupsBuilt && STATE.schema.length) buildGroups(STATE.schema);
    syncInputs();
}

function renderModeBadge() {
    const badge = $("mode-badge");
    if (!badge) return;
    const text = { auto: "AUTO - AUTONOMOUS", paused: "PAUSED - HOLDING", manual: "MANUAL - NOT AUTONOMOUS" };
    badge.textContent = text[STATE.mode] || STATE.mode.toUpperCase();
    badge.className = "badge mode-" + STATE.mode;

    const manual = STATE.mode === "manual";
    const paused = STATE.mode === "paused";

    if ($("btn-arm")) $("btn-arm").hidden = !paused;
    if ($("btn-start")) $("btn-start").hidden = !paused;
    if ($("manual-controls")) $("manual-controls").classList.toggle("off", !manual);
}

function renderTelemetry() {
    const el = $("telemetry");
    if (!el) return;
    const t = STATE.telemetry;
    const parts = [];
    if (t.fps !== undefined) parts.push("FPS " + Number(t.fps).toFixed(1));
    if (t.steering !== undefined) parts.push("Steer " + signed(t.steering));
    if (t.throttle !== undefined) parts.push("Thr " + signed(t.throttle));
    if (t.detected !== undefined) parts.push(t.detected ? "LINE OK" : "LINE LOST");
    el.textContent = parts.length ? parts.join("  |  ") : "—";
}

function renderDeadman() {
    const wrap = $("deadman");
    if (!wrap) return;
    if (STATE.mode !== "manual" || STATE.deadman === null || !STATE.limits.deadman_timeout_ms) {
        wrap.hidden = true;
        return;
    }
    wrap.hidden = false;
    const ratio = Math.max(0, Math.min(1, STATE.deadman / STATE.limits.deadman_timeout_ms));
    const fill = $("deadman-fill");
    fill.style.width = (ratio * 100) + "%";
    fill.style.background = ratio > 0.5 ? "#00e676" : (ratio > 0.2 ? "#ffb300" : "#ff5252");
}

function renderManualLimits() {
    const steer = $("ctl-steer");
    const thr = $("ctl-thr");
    if (!steer || !thr || !STATE.limits.max_steering) return;
    steer.min = -STATE.limits.max_steering;
    steer.max = STATE.limits.max_steering;
    thr.min = STATE.limits.max_reverse;
    thr.max = STATE.limits.max_throttle;
}

function signed(v) { return (v >= 0 ? "+" : "") + Number(v).toFixed(2); }

function statusLine(id, message, kind) {
    const el = $(id);
    if (!el) return;
    el.textContent = message || "";
    el.className = "statusline" + (kind ? " " + kind : "");
}

/* ------------------------------------------------------------------ *
 * Tuning tab
 * ------------------------------------------------------------------ */

let groupsBuilt = false;
const pendingTune = new Map();
let tuneTimer = null;

function buildGroups(schema) {
    const host = $("tune-groups");
    if (!host) return;
    host.textContent = "";

    const groups = new Map();
    for (const p of schema) {
        if (!groups.has(p.group)) groups.set(p.group, []);
        groups.get(p.group).push(p);
    }

    for (const [name, params] of groups) {
        const section = document.createElement("div");
        section.className = "group";
        const heading = document.createElement("h2");
        heading.textContent = name;
        section.appendChild(heading);
        for (const p of params) section.appendChild(buildRow(p));
        host.appendChild(section);
    }
    groupsBuilt = true;
}

function buildRow(p) {
    const row = document.createElement("div");
    row.className = "row";

    const label = document.createElement("label");
    label.textContent = p.label;
    label.htmlFor = "ctl-" + p.key;
    row.appendChild(label);

    if (p.kind === "enum") {
        const select = document.createElement("select");
        for (const choice of p.choices) {
            const option = document.createElement("option");
            option.value = choice;
            option.textContent = choice;
            select.appendChild(option);
        }
        select.dataset.key = p.key;
        select.addEventListener("change", () => onParamInput(select));
        row.appendChild(select);
    } else {
        const range = document.createElement("input");
        range.type = "range";
        range.min = p.min;
        range.max = p.max;
        range.step = p.step;
        range.dataset.key = p.key;
        range.addEventListener("input", () => onParamInput(range));
        markDragging(range);
        row.appendChild(range);

        const number = document.createElement("input");
        number.type = "number";
        number.min = p.min;
        number.max = p.max;
        number.step = p.step;
        number.dataset.key = p.key;
        number.addEventListener("input", () => onParamInput(number));
        row.appendChild(number);
    }

    if (p.note) {
        const note = document.createElement("div");
        note.className = "note";
        note.textContent = p.note;
        row.appendChild(note);
    }
    return row;
}

/* Range inputs do not always take focus on touch, so track the drag explicitly. */
function markDragging(el) {
    el.addEventListener("pointerdown", () => { el.dataset.dragging = "1"; });
    const end = () => { delete el.dataset.dragging; };
    el.addEventListener("pointerup", end);
    el.addEventListener("pointercancel", end);
}

function onParamInput(el) {
    const key = el.dataset.key;
    for (const peer of document.querySelectorAll('[data-key="' + key + '"]')) {
        if (peer !== el) peer.value = el.value;
    }
    pendingTune.set(key, el.value);
    if (tuneTimer !== null) clearTimeout(tuneTimer);
    tuneTimer = setTimeout(flushTune, TUNE_DEBOUNCE_MS);
}

async function flushTune() {
    tuneTimer = null;
    if (pendingTune.size === 0) return;
    const body = {};
    for (const [key, value] of pendingTune) body[key] = value;
    pendingTune.clear();

    const { data } = await postJSON("/api/tune", body);
    if (!data) { statusLine("tune-status", "No response from the car.", "bad"); return; }
    const rejected = data.rejected || {};
    const keys = Object.keys(rejected);
    if (keys.length) {
        statusLine("tune-status", "Rejected: " + keys.map((k) => k + " (" + rejected[k] + ")").join(", "), "bad");
    } else {
        statusLine("tune-status", "Applied " + Object.keys(data.applied || {}).length + " change(s).", "good");
    }
}

function bindTuningButtons() {
    const resetPid = $("btn-reset-pid");
    if (resetPid) resetPid.addEventListener("click", async () => {
        await postJSON("/api/tune", { action: "reset_pid" });
        statusLine("tune-status", "PID integrator and derivative history cleared.", "good");
    });

    const resetDefaults = $("btn-reset-defaults");
    if (resetDefaults) resetDefaults.addEventListener("click", async () => {
        await postJSON("/api/tune", { action: "reset_defaults" });
        await pollState();
        statusLine("tune-status", "Restored the built-in defaults.", "good");
    });

    const snippet = $("btn-snippet");
    if (snippet) snippet.addEventListener("click", async () => {
        const text = configSnippet();
        const pre = $("snippet");
        pre.textContent = text;
        pre.hidden = false;
        statusLine("tune-status", (await copyText(text))
            ? "Copied. Paste the values into config.py before the next run."
            : "Select the text below and copy it manually.", "good");
    });
}

function configSnippet() {
    const bySection = new Map();
    for (const p of STATE.schema) {
        const parts = p.key.split(".");
        const value = STATE.params[p.key];
        const literal = (typeof value === "string") ? JSON.stringify(value) : value;
        if (!bySection.has(parts[0])) bySection.set(parts[0], []);
        bySection.get(parts[0]).push("    " + parts[1] + " = " + literal);
    }
    const out = [];
    for (const [section, lines] of bySection) out.push("# " + section + "\n" + lines.join("\n"));
    return out.join("\n\n");
}

async function copyText(text) {
    // navigator.clipboard is unavailable on plain http, which is exactly how this
    // page is reached on the LAN, so the textarea fallback is the common path.
    try {
        if (window.isSecureContext && navigator.clipboard) {
            await navigator.clipboard.writeText(text);
            return true;
        }
    } catch (e) { /* fall through */ }
    const area = document.createElement("textarea");
    area.value = text;
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    let ok = false;
    try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
    document.body.removeChild(area);
    return ok;
}

/* ------------------------------------------------------------------ *
 * Manual tab
 * ------------------------------------------------------------------ */

let inFlight = false;
let sendTimer = null;
let holdTimer = null;
let holdFrame = null;
let holdStart = 0;

function startSending() {
    if (sendTimer !== null || !HAS_REMOTE) return;
    sendTimer = setInterval(pushDrive, SEND_INTERVAL_MS);
}

function stopSending() {
    if (sendTimer !== null) { clearInterval(sendTimer); sendTimer = null; }
}

async function pushDrive() {
    // Single-flight: a slow response must never let drive commands stack up, or
    // the car would keep executing a queue of stale inputs after the operator stops.
    if (inFlight || STATE.mode !== "manual") return;
    inFlight = true;
    try {
        await postJSON("/api/manual", { steering: TARGET.steering, throttle: TARGET.throttle });
    } catch (e) { /* transient network hiccup; the deadman covers a real outage */ }
    finally { inFlight = false; }
}

function setAxis(axis, value) {
    TARGET[axis] = value;
    syncInputs();
}

function releaseAll() {
    TARGET.steering = 0;
    TARGET.throttle = 0;
    syncInputs();
}

function syncInputs() {
    const steer = $("ctl-steer");
    const thr = $("ctl-thr");
    if (steer && !isBusy(steer)) steer.value = TARGET.steering;
    if (thr && !isBusy(thr)) thr.value = TARGET.throttle;
    if ($("disp-steer")) $("disp-steer").textContent = signed(TARGET.steering);
    if ($("disp-thr")) $("disp-thr").textContent = signed(TARGET.throttle);

    for (const el of document.querySelectorAll("#tune-groups [data-key]")) {
        const value = STATE.params[el.dataset.key];
        if (value === undefined || isBusy(el)) continue;
        const next = String(value);
        if (el.value !== next) el.value = next;
    }
}

/* Skipping the focused control is what keeps the 500 ms poll from yanking a
   slider back out of the operator's hand mid-drag. */
function isBusy(el) {
    return el === document.activeElement || el.dataset.dragging === "1";
}

function bindManualInputs() {
    const steer = $("ctl-steer");
    const thr = $("ctl-thr");

    if (steer) {
        steer.addEventListener("input", () => setAxis("steering", parseFloat(steer.value) || 0));
        // Releasing returns the axis to centre: this is a deadman stick, not a trim.
        // The handle is moved by hand because the control still holds focus, and
        // syncInputs() deliberately leaves a focused control alone.
        steer.addEventListener("change", () => { steer.value = 0; setAxis("steering", 0); });
        markDragging(steer);
    }
    if (thr) {
        thr.addEventListener("input", () => setAxis("throttle", parseFloat(thr.value) || 0));
        thr.addEventListener("change", () => { thr.value = 0; setAxis("throttle", 0); });
        markDragging(thr);
    }

    for (const button of document.querySelectorAll(".pad-btn")) {
        const axis = button.dataset.axis;
        const raw = button.dataset.value;
        const valueFor = () => {
            if (raw === "max") return STATE.limits.max_throttle;
            if (raw === "min") return STATE.limits.max_reverse;
            return parseFloat(raw) * STATE.limits.max_steering;
        };
        button.addEventListener("pointerdown", (event) => {
            event.preventDefault();
            button.setPointerCapture(event.pointerId);
            button.classList.add("held");
            setAxis(axis, valueFor());
        });
        const release = () => {
            button.classList.remove("held");
            setAxis(axis, 0);
        };
        button.addEventListener("pointerup", release);
        button.addEventListener("pointercancel", release);
        button.addEventListener("lostpointercapture", release);
    }
}

function bindArmButton() {
    const arm = $("btn-arm");
    if (!arm) return;
    const fill = arm.querySelector(".fill");

    const tick = () => {
        const elapsed = performance.now() - holdStart;
        if (fill) fill.style.width = Math.min(100, (elapsed / ARM_HOLD_MS) * 100) + "%";
        holdFrame = requestAnimationFrame(tick);
    };

    const start = (event) => {
        if (event) event.preventDefault();
        if (STATE.mode !== "paused") return;
        holdStart = performance.now();
        arm.classList.add("held");
        holdFrame = requestAnimationFrame(tick);
        holdTimer = setTimeout(async () => {
            cancelHold();
            const { data } = await postJSON("/api/manual", { action: "arm" });
            statusLine("manual-status", (data && data.ok)
                ? "Armed. Hold a control to drive; it stops on its own if commands stop."
                : ("Could not arm: " + ((data && data.error) || "no response")),
                (data && data.ok) ? "good" : "bad");
        }, ARM_HOLD_MS);
    };

    arm.addEventListener("pointerdown", start);
    arm.addEventListener("pointerup", cancelHold);
    arm.addEventListener("pointercancel", cancelHold);
    arm.addEventListener("pointerleave", cancelHold);
}

function cancelHold() {
    if (holdTimer !== null) { clearTimeout(holdTimer); holdTimer = null; }
    if (holdFrame !== null) { cancelAnimationFrame(holdFrame); holdFrame = null; }
    const arm = $("btn-arm");
    if (arm) {
        arm.classList.remove("held");
        const fill = arm.querySelector(".fill");
        if (fill) fill.style.width = "0%";
    }
}

function bindManualButtons() {
    if ($("btn-stop")) $("btn-stop").addEventListener("click", doStop);
    if ($("btn-start")) $("btn-start").addEventListener("click", async () => {
        const { data } = await postJSON("/api/manual", { action: "start" });
        statusLine("manual-status", (data && data.ok) ? "Autonomous line following resumed."
            : ("Could not start: " + ((data && data.error) || "no response")),
            (data && data.ok) ? "good" : "bad");
    });
}

function doStop() {
    releaseAll();
    cancelHold();
    postJSON("/api/manual", { action: "stop" });
    statusLine("manual-status", "Stop requested.", "good");
}

/* ------------------------------------------------------------------ *
 * Input, lifecycle
 * ------------------------------------------------------------------ */

function bindKeyboard() {
    const axes = {
        w: ["throttle", () => STATE.limits.max_throttle],
        s: ["throttle", () => STATE.limits.max_reverse],
        a: ["steering", () => -STATE.limits.max_steering],
        d: ["steering", () => STATE.limits.max_steering]
    };
    let armKeyTimer = null;

    window.addEventListener("keydown", (event) => {
        if (event.repeat) return;   // the OS repeat rate is not a drive command
        const key = event.key.toLowerCase();

        if (event.key === " " || event.code === "Space") {
            event.preventDefault();
            if (STATE.mode !== "auto") doStop();
            return;
        }
        if (key === "m") {
            if (STATE.mode !== "paused") return;
            armKeyTimer = setTimeout(async () => {
                armKeyTimer = null;
                const { data } = await postJSON("/api/manual", { action: "arm" });
                statusLine("manual-status", (data && data.ok) ? "Armed via keyboard."
                    : ("Could not arm: " + ((data && data.error) || "no response")),
                    (data && data.ok) ? "good" : "bad");
            }, ARM_HOLD_MS);
            return;
        }
        if (axes[key]) {
            event.preventDefault();
            if (STATE.mode !== "manual") return;
            const [axis, valueFor] = axes[key];
            setAxis(axis, valueFor());
        }
    });

    window.addEventListener("keyup", (event) => {
        const key = event.key.toLowerCase();
        if (key === "m" && armKeyTimer !== null) { clearTimeout(armKeyTimer); armKeyTimer = null; return; }
        if (axes[key]) setAxis(axes[key][0], 0);
    });

    window.addEventListener("blur", releaseAll);
}

function bindLifecycle() {
    // A backgrounded tab stops being a reliable operator: drop to zero at once
    // rather than let the deadman be the only thing between us and a runaway.
    document.addEventListener("visibilitychange", () => {
        if (!document.hidden) return;
        releaseAll();
        if (STATE.mode === "manual") {
            postJSON("/api/manual", { steering: 0, throttle: 0 });
        }
    });

    window.addEventListener("pagehide", () => {
        if (STATE.mode !== "manual" || !navigator.sendBeacon) return;
        // stop, never start: closing the page must not hand the car back to
        // autonomous control while it is sitting somewhere unexpected.
        navigator.sendBeacon("/api/manual",
            new Blob([JSON.stringify({ action: "stop" })], { type: "application/json" }));
    });
}

function bindTabs() {
    const tabs = document.querySelectorAll(".tab");
    for (const tab of tabs) {
        tab.addEventListener("click", () => {
            for (const other of tabs) other.classList.toggle("active", other === tab);
            for (const panel of document.querySelectorAll(".panel")) {
                panel.classList.toggle("active", panel.dataset.panel === tab.dataset.panel);
            }
            // The <img> lives outside the panels on purpose: rebuilding it would
            // drop the MJPEG connection and black the picture out on every switch.
        });
    }
}

function init() {
    bindTabs();
    bindTuningButtons();
    bindManualInputs();
    bindArmButton();
    bindManualButtons();
    bindKeyboard();
    bindLifecycle();

    if (!HAS_REMOTE) return;
    pollState();
    setInterval(pollState, 500);
}

document.addEventListener("DOMContentLoaded", init);
</script>
</body>
</html>
"""


def render_page(remote: Optional[RemoteState]) -> str:
    """Build the console page for the current launch flags."""
    if remote is None:
        allow_tuning = allow_manual = False
        mode = MODE_AUTO
    else:
        state = remote.snapshot()
        permissions = state["permissions"]
        allow_tuning = permissions["tuning"]
        allow_manual = permissions["manual"]
        mode = state["mode"]

    # Somebody who launched with --allow-manual came here to drive, so land them
    # on that tab. Tuning-only runs have nothing else to show.
    default_tab = "manual" if allow_manual else ("tuning" if allow_tuning else "")

    mode_text = {
        MODE_AUTO: "AUTO - AUTONOMOUS",
        MODE_PAUSED: "PAUSED - HOLDING",
        MODE_MANUAL: "MANUAL - NOT AUTONOMOUS",
    }.get(mode, mode.upper())

    return (_TEMPLATE
            .replace("__TABS__", _tabs_html(allow_tuning, allow_manual, default_tab))
            .replace("__PANELS__", _panels_html(allow_tuning, allow_manual, default_tab))
            .replace("__INITIAL_MODE_TEXT__", mode_text)
            .replace("__INITIAL_MODE__", mode)
            .replace("__HAS_REMOTE__", "true" if remote is not None else "false")
            .replace("__ARM_HOLD_MS__", str(ARM_HOLD_MS))
            .replace("__SEND_INTERVAL_MS__", str(SEND_INTERVAL_MS))
            .replace("__TUNE_DEBOUNCE_MS__", str(TUNE_DEBOUNCE_MS)))
