"""
Web console page for the PiRacer Pro debug tooling.

Kept separate from streamer.py, which owns the HTTP plumbing, so the request
handling does not disappear under a few hundred lines of markup. Everything in
this file is presentation only: the server re-validates every value that arrives,
so nothing here is a security boundary.

Which controls exist at all is decided by the launch flags, not by the browser --
the page is served to everyone on the LAN, so a tab only appears when the person
at the terminal asked for it.

The console speaks English and Simplified Chinese. Unlike the repository's
documents there is no mirror file for the Chinese: this is a runtime view, so
both languages travel inside the one page and the browser swaps the strings in
place. Switching language therefore never reloads -- a reload would drop the
MJPEG connection and, for an operator mid-drive, the deadman with it.
"""

import json
from typing import Dict, Optional

from webcontrol import MODE_AUTO, MODE_MANUAL, MODE_PAUSED, RemoteState

# Languages the console ships. The first is what an unmatched Accept-Language
# header falls back to.
DEFAULT_LANG = "en"

# How long the ARM button must be held. Guards against a stray click or tap.
ARM_HOLD_MS = 2000

# Drive commands are pushed at 10 Hz, leaving eight heartbeats inside the 800 ms
# deadman window.
SEND_INTERVAL_MS = 100

# Parameter changes are batched so dragging a slider does not emit a request per pixel.
TUNE_DEBOUNCE_MS = 250

# Axis response rates, in full-scale units per second.
#
# A key press is an *intent*, not a position: the browser integrates it into an
# axis value over these rates, so the commanded steering and throttle ramp
# instead of stepping. Two reasons this matters beyond feel -- a step to full
# lock shock-loads the steering servo and the ESC every time a key goes down,
# and a car that jumps straight to max_manual_throttle is unpleasant to drive
# anywhere near a wall. Let go and the axis returns to centre on its own.
STEER_RATE = 2.2        # key held: full lock in ~0.45 s
STEER_RETURN = 3.5      # key released: back to centre in ~0.29 s
THROTTLE_RISE = 0.9     # W held: 0 -> 0.40 in ~0.44 s
THROTTLE_FALL = 1.8     # S held, or nothing held: brake and return to zero faster

# One frame's worth of integration is clamped to this many seconds. A backgrounded
# tab stops emitting animation frames, and without the clamp the axis would jump
# the whole elapsed gap the moment it comes back.
MAX_FRAME_DT = 0.1

# Every piece of interface copy, in both languages.
#
# Keys are stable identifiers; markup carries them as data-i18n (plain text) or
# data-i18n-html (the entry contains inline markup, and only ever our own
# literals -- no user input reaches innerHTML here).
#
# Entries use real Unicode characters rather than HTML entities, because most of
# them are written with textContent, where "&mdash;" would show up as itself.
#
# Not in this table, on purpose: the error strings webcontrol.py and streamer.py
# return ("must be within [0.0, 2.0]", "not armed (mode=auto)"). Those are
# diagnostics for whoever is debugging, not interface copy, and translating them
# would mean threading a language into the validation layer, which is deliberately
# free of any presentation concern. The console shows them verbatim after a
# translated prefix.
_STRINGS: Dict[str, Dict[str, str]] = {
    "en": {
        "badge.live": "Live",
        "stream.alt": "Live camera stream",
        "badge.mode.auto": "AUTO - AUTONOMOUS",
        "badge.mode.paused": "PAUSED - HOLDING",
        "badge.mode.manual": "MANUAL - NOT AUTONOMOUS",

        "tab.tuning": "Tuning",
        "tab.manual": "Manual Drive",

        "telem.fps": "FPS",
        "telem.steer": "Steer",
        "telem.thr": "Thr",
        "telem.line_ok": "LINE OK",
        "telem.line_lost": "LINE LOST",

        "gauge.steering": "STEERING",
        "gauge.throttle": "THR",

        "tuning.reset_pid": "Reset PID State",
        "tuning.reset_defaults": "Reset to Defaults",
        "tuning.copy": "Copy as config.py",
        "tuning.hint": "Changes apply immediately, even while the car is driving. "
                       "The car keeps following the line — this tab never takes over steering.",

        "manual.warning": "Manual control is a <strong>test-only</strong> tool. "
                          "A competition run is always autonomous. "
                          "The car stops by itself if these commands stop arriving.",
        "manual.arm": "HOLD TO ARM (2s)",
        "manual.autonomous": "AUTONOMOUS",
        "manual.stop": "■ STOP",
        "manual.hint": "Keyboard: <kbd>W</kbd> throttle, <kbd>S</kbd> brake/reverse, "
                       "<kbd>A</kbd>/<kbd>D</kbd> steer, <kbd>Space</kbd> emergency stop, "
                       "hold <kbd>M</kbd> to arm. Nothing latches: let go and every axis "
                       "returns to centre on its own.",

        "footer": "Test tooling only · a race run is always autonomous",

        "status.no_response": "No response from the car.",
        "status.rejected": "Rejected: ",
        "status.applied": "Applied {n} change(s).",
        "status.pid_reset": "PID integrator and derivative history cleared.",
        "status.defaults": "Restored the built-in defaults.",
        "status.copied": "Copied. Paste the values into config.py before the next run.",
        "status.copy_manual": "Select the text below and copy it manually.",
        "status.armed": "Armed. Hold a control to drive; it stops on its own if commands stop.",
        "status.armed_keyboard": "Armed via keyboard.",
        "status.arm_failed": "Could not arm: ",
        "status.autonomous": "Autonomous line following resumed.",
        "status.start_failed": "Could not start: ",
        "status.stopped": "Stop requested.",
        "common.no_response": "no response",
    },
    "zh": {
        "badge.live": "实时",
        "stream.alt": "实时摄像头画面",
        "badge.mode.auto": "AUTO - 自主驾驶",
        "badge.mode.paused": "PAUSED - 已停住",
        "badge.mode.manual": "MANUAL - 非自主控制",

        "tab.tuning": "调参",
        "tab.manual": "手动驾驶",

        "telem.fps": "FPS",
        "telem.steer": "转向",
        "telem.thr": "油门",
        "telem.line_ok": "循线正常",
        "telem.line_lost": "丢线",

        "gauge.steering": "转向",
        "gauge.throttle": "油门",

        "tuning.reset_pid": "重置 PID 状态",
        "tuning.reset_defaults": "恢复默认值",
        "tuning.copy": "复制为 config.py",
        "tuning.hint": "改动立即生效，车辆行驶中也一样。车始终自主循线 —— 本页签从不接管转向。",

        "manual.warning": "手动控制是<strong>仅限测试</strong>的工具。比赛全程自主驾驶。"
                          "若指令中断，车辆会自行停车。",
        "manual.arm": "长按解锁（2 秒）",
        "manual.autonomous": "自主驾驶",
        "manual.stop": "■ 急停",
        "manual.hint": "键盘：<kbd>W</kbd> 油门、<kbd>S</kbd> 刹车/倒车、"
                       "<kbd>A</kbd>/<kbd>D</kbd> 转向、<kbd>Space</kbd> 急停、"
                       "长按 <kbd>M</kbd> 解锁。没有任何轴会锁住：松手后自动回正。",

        "footer": "仅为测试工具 · 比赛全程自主驾驶",

        "status.no_response": "车辆无响应。",
        "status.rejected": "被拒绝：",
        "status.applied": "已应用 {n} 项改动。",
        "status.pid_reset": "已清空 PID 积分与微分历史。",
        "status.defaults": "已恢复内置默认值。",
        "status.copied": "已复制。下次运行前把数值粘回 config.py。",
        "status.copy_manual": "请手动选中下方文本复制。",
        "status.armed": "已解锁。按住控制键才会动；指令中断会自动停车。",
        "status.armed_keyboard": "已通过键盘解锁。",
        "status.arm_failed": "解锁失败：",
        "status.autonomous": "已恢复自主循线。",
        "status.start_failed": "启动失败：",
        "status.stopped": "已请求停车。",
        "common.no_response": "无响应",
    },
}

# The whole table, embedded in the page. "</" is escaped so that a future entry
# containing a closing tag can never terminate the script block early.
_I18N_JSON = json.dumps(_STRINGS, ensure_ascii=False).replace("</", "<\\/")


def pick_language(accept_language: str) -> str:
    """
    Choose the console's initial language from the browser's Accept-Language.

    Deliberately naive: this only sets what a first-time visitor sees, and the
    buttons on the page override it from then on. Parsing q-values properly would
    buy nothing -- the header arrives ordered by preference anyway.
    """
    for part in accept_language.split(","):
        tag = part.split(";")[0].strip().lower()
        if tag.startswith("zh"):
            return "zh"
        if tag.startswith("en"):
            return "en"
    return DEFAULT_LANG


def _tabs_html(allow_tuning: bool, allow_manual: bool, default_tab: str) -> str:
    if not (allow_tuning or allow_manual):
        return ""

    buttons = []
    if allow_tuning:
        buttons.append(('tuning', 'tab.tuning'))
    if allow_manual:
        buttons.append(('manual', 'tab.manual'))

    # The label is filled in by applyLanguage() on load, so an empty element here
    # is correct -- it is never visible without one.
    parts = ['<nav class="tabs">']
    for name, key in buttons:
        active = ' active' if name == default_tab else ''
        parts.append(f'<button class="tab{active}" data-panel="{name}" '
                     f'data-i18n="{key}"></button>')
    parts.append('</nav>')
    return "".join(parts)


def _panels_html(allow_tuning: bool, allow_manual: bool, default_tab: str) -> str:
    parts = []

    if allow_tuning:
        active = ' active' if default_tab == 'tuning' else ''
        parts.append(f'''
        <section class="panel{active}" data-panel="tuning">
            <div class="toolbar">
                <button class="btn" id="btn-reset-pid" data-i18n="tuning.reset_pid"></button>
                <button class="btn" id="btn-reset-defaults" data-i18n="tuning.reset_defaults"></button>
                <button class="btn" id="btn-snippet" data-i18n="tuning.copy"></button>
            </div>
            <div class="statusline" id="tune-status"></div>
            <div id="tune-groups"></div>
            <pre class="snippet" id="snippet" hidden></pre>
            <p class="hint" data-i18n-html="tuning.hint"></p>
        </section>''')

    if allow_manual:
        active = ' active' if default_tab == 'manual' else ''
        parts.append(f'''
        <section class="panel{active}" data-panel="manual">
            <div class="warning" data-i18n-html="manual.warning"></div>

            <div class="toolbar">
                <button class="btn go arm" id="btn-arm">
                    <span class="fill"></span>
                    <span class="txt" data-i18n="manual.arm"></span>
                </button>
                <button class="btn" id="btn-start" data-i18n="manual.autonomous"></button>
                <button class="btn danger" id="btn-stop" data-i18n="manual.stop"></button>
            </div>
            <div class="statusline" id="manual-status"></div>

            <div class="gamepad" id="manual-controls">
                <div class="pad-cluster">
                    <button class="pad-btn" data-key="a" aria-label="Steer left">&#9664;</button>
                    <button class="pad-btn" data-key="d" aria-label="Steer right">&#9654;</button>
                </div>
                <div class="pad-cluster">
                    <button class="pad-btn" data-key="s" aria-label="Reverse">&#9660;</button>
                    <button class="pad-btn" data-key="w" aria-label="Accelerate">&#9650;</button>
                </div>
            </div>

            <p class="hint" data-i18n-html="manual.hint"></p>
        </section>''')

    return "".join(parts)


def _dash_html(allow_manual: bool) -> str:
    """
    The gauge cluster drawn over the video.

    Only rendered when a human can actually drive: a readout of the commanded
    axes is noise on a page that has no way to command them. Pure display, so
    it stays out of the pointer path (`.hud` is pointer-events: none) and can
    never swallow a click meant for the video.
    """
    if not allow_manual:
        return ""

    return '''
            <div class="hud-dash" id="hud-dash">
                <div class="gauge gauge-steer">
                    <span class="gauge-label" data-i18n="gauge.steering"></span>
                    <div class="steer-track">
                        <i class="steer-center"></i>
                        <i class="steer-needle" id="needle-steer"></i>
                    </div>
                    <span class="gauge-value" id="dash-steer">+0.00</span>
                </div>
                <div class="gauge gauge-thr">
                    <span class="gauge-label" data-i18n="gauge.throttle"></span>
                    <div class="thr-track"><i class="thr-fill" id="fill-thr"></i></div>
                    <span class="gauge-value" id="dash-thr">+0.00</span>
                </div>
            </div>
        '''


_TEMPLATE = r"""<!DOCTYPE html>
<html lang="__INITIAL_LANG__">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>PiRacer Pro - Debug Console</title>
<style>
    :root {
        color-scheme: dark;
        --neon: #00e676;
        --amber: #ffb300;
        --red: #ff3b30;
        --line: #262b35;
        --ink: #0a0b0e;
        --ink-2: #14161b;
        --muted: #8892a0;
        /* CJK faces for the Chinese UI. They come after the Latin ones in every
           stack, so ASCII still renders in the system's own font and only the Han
           characters fall through -- which is what keeps the numbers in the gauges
           and in the config snippet monospaced. */
        --cjk: "PingFang SC", "Microsoft YaHei", "Noto Sans CJK SC", "Source Han Sans SC",
               "WenQuanYi Micro Hei", "Hiragino Sans GB", sans-serif;
        --mono: ui-monospace, "SF Mono", "Cascadia Mono", "Roboto Mono", Consolas, var(--cjk);
    }
    * { box-sizing: border-box; }
    [hidden] { display: none !important; }
    body {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, var(--cjk);
        background: radial-gradient(120% 90% at 50% 0%, #171b22 0%, var(--ink) 55%) fixed;
        color: #e8ecf1;
        margin: 0;
        padding: 16px;
        min-height: 100vh;
    }
    .container { max-width: 1000px; margin: 0 auto; text-align: center; }

    .masthead { position: relative; margin-bottom: 12px; }
    .masthead h1 {
        font-size: 1.05rem; margin: 0; letter-spacing: 4px; font-weight: 800;
        color: var(--neon); text-transform: uppercase;
    }
    .masthead h1 span { color: var(--muted); font-weight: 400; }
    .masthead p { margin: 3px 0 0; font-size: 0.7rem; color: var(--muted); letter-spacing: 1px; }

    /* Language switch. Both languages ship in the page, so this only swaps strings;
       it never navigates, which is what keeps the video and the deadman alive. */
    .langs { position: absolute; top: 0; right: 0; display: flex; gap: 4px; }
    .langbtn {
        background: transparent; border: 1px solid var(--line); color: var(--muted);
        border-radius: 6px; padding: 4px 9px; font-family: inherit; font-size: 0.7rem;
        font-weight: 700; letter-spacing: 0.5px; cursor: pointer;
    }
    .langbtn:hover { background: var(--ink-2); color: #dfe4ea; }
    .langbtn.active { color: var(--neon); border-color: rgba(0, 230, 118, 0.6); }

    /* ---------- cockpit: the video fills the stage, the HUD rides on top ---------- */

    .stage {
        position: relative; background: #000; border-radius: 12px; overflow: hidden;
        border: 1px solid var(--line);
        box-shadow: 0 0 0 1px rgba(0, 230, 118, 0.07), 0 16px 48px rgba(0, 0, 0, 0.7);
    }
    .stage img { display: block; width: 100%; height: auto; max-height: 76vh; object-fit: contain; }

    /* The gauge cluster is the only thing overlaid on the picture. The mode banner
       is already drawn into the video frame by main.py, so nothing else belongs up
       there; the badges and telemetry sit below the stage instead of on top of it. */
    .hud {
        position: absolute; inset: 0; pointer-events: none;
        display: flex; align-items: flex-end; padding: 12px;
    }
    .hud-dash { display: flex; gap: 18px; align-items: flex-end; justify-content: space-between; width: 100%; }

    .topbar { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; justify-content: center; margin: 12px 0 8px; }

    .badge {
        padding: 5px 11px; border-radius: 6px; font-size: 0.68rem; font-weight: 800;
        letter-spacing: 1.1px; text-transform: uppercase; white-space: nowrap;
        background: rgba(10, 12, 16, 0.78); border: 1px solid var(--line);
        backdrop-filter: blur(6px); -webkit-backdrop-filter: blur(6px);
    }
    .badge.mode-auto { color: var(--neon); border-color: rgba(0, 230, 118, 0.6); box-shadow: 0 0 14px rgba(0, 230, 118, 0.3); }
    .badge.mode-paused { color: var(--amber); border-color: rgba(255, 179, 0, 0.6); box-shadow: 0 0 14px rgba(255, 179, 0, 0.28); }
    .badge.mode-manual {
        color: #fff; background: var(--red); border-color: var(--red);
        box-shadow: 0 0 20px rgba(255, 59, 48, 0.55); animation: pulse 1.6s ease-in-out infinite;
    }
    .badge.live { color: var(--neon); }
    .badge.live::before { content: "\25CF"; color: var(--red); margin-right: 5px; animation: blink 1.6s steps(1, end) infinite; }
    @keyframes blink { 0%, 60% { opacity: 1; } 61%, 100% { opacity: 0.25; } }
    @keyframes pulse { 50% { box-shadow: 0 0 6px rgba(255, 59, 48, 0.25); } }

    .telem {
        font-family: var(--mono); font-size: 0.7rem; color: var(--muted);
        background: rgba(10, 12, 16, 0.78); border: 1px solid var(--line);
        border-radius: 6px; padding: 5px 10px; letter-spacing: 0.4px;
        backdrop-filter: blur(6px); -webkit-backdrop-filter: blur(6px);
    }

    .deadman {
        height: 5px; background: rgba(255, 255, 255, 0.13); border-radius: 3px;
        overflow: hidden; box-shadow: 0 1px 6px rgba(0, 0, 0, 0.8);
    }
    .deadman > i { display: block; height: 100%; width: 0; background: var(--neon); transition: background 0.2s; }

    /* ---------- gauge cluster ---------- */

    .gauge { display: flex; flex-direction: column; gap: 5px; align-items: center; }
    .gauge-label, .gauge-value {
        font-family: var(--mono); font-size: 0.64rem; letter-spacing: 1.4px;
        color: var(--muted); text-shadow: 0 1px 4px #000;
    }
    .gauge-value { font-size: 0.95rem; font-weight: 700; color: #fff; letter-spacing: 0.5px; }

    .gauge-steer { flex: 1; max-width: 320px; align-items: stretch; }
    .gauge-steer .gauge-label, .gauge-steer .gauge-value { text-align: left; }

    .steer-track {
        position: relative; height: 10px; border-radius: 5px;
        background: rgba(10, 12, 16, 0.78); border: 1px solid var(--line);
        backdrop-filter: blur(6px); -webkit-backdrop-filter: blur(6px);
    }
    .steer-center { position: absolute; left: 50%; top: 1px; bottom: 1px; width: 2px; margin-left: -1px; background: rgba(255, 255, 255, 0.28); }
    .steer-needle {
        position: absolute; top: 50%; left: 50%; width: 18px; height: 18px; margin: -9px 0 0 -9px;
        border-radius: 50%; background: var(--neon); box-shadow: 0 0 14px var(--neon);
        transition: background 0.1s, box-shadow 0.1s;
    }
    .steer-needle.wide { background: var(--amber); box-shadow: 0 0 14px var(--amber); }

    .gauge-thr { width: 46px; }
    .thr-track {
        position: relative; width: 100%; height: 82px; border-radius: 6px; overflow: hidden;
        background: rgba(10, 12, 16, 0.78); border: 1px solid var(--line);
        backdrop-filter: blur(6px); -webkit-backdrop-filter: blur(6px);
    }
    .thr-track::after { content: ""; position: absolute; left: 0; right: 0; top: 50%; height: 1px; background: rgba(255, 255, 255, 0.28); }
    .thr-fill {
        position: absolute; left: 0; right: 0; bottom: 50%; height: 0;
        background: var(--neon); box-shadow: 0 0 16px var(--neon);
    }
    .thr-fill.reverse { background: var(--amber); box-shadow: 0 0 16px var(--amber); }

    /* ---------- tabs ---------- */

    .tabs { display: flex; gap: 6px; margin: 14px 0 12px; }
    .tab {
        flex: 1; padding: 11px; background: var(--ink-2); color: #b6bdc9;
        border: 1px solid var(--line); border-radius: 8px;
        font-family: inherit; font-size: 0.86rem; font-weight: 700; letter-spacing: 0.8px;
        text-transform: uppercase; cursor: pointer;
    }
    .tab:hover { background: #1b1f27; }
    .tab.active { background: var(--neon); color: #06200e; border-color: var(--neon); box-shadow: 0 0 20px rgba(0, 230, 118, 0.3); }

    .panel { display: none; text-align: left; }
    .panel.active { display: block; }

    /* ---------- controls ---------- */

    .toolbar { display: flex; flex-wrap: wrap; gap: 8px; margin: 12px 0; }
    .btn {
        padding: 11px 16px; border-radius: 8px; border: 1px solid var(--line); background: var(--ink-2);
        color: #eee; font-family: inherit; font-size: 0.82rem; font-weight: 700;
        letter-spacing: 0.8px; text-transform: uppercase; cursor: pointer;
    }
    .btn:hover { background: #1b1f27; }
    .btn.danger { background: var(--red); border-color: var(--red); color: #fff; box-shadow: 0 0 16px rgba(255, 59, 48, 0.35); }
    .btn.danger:hover { background: #ff5349; }
    .btn.go { background: #1d7a3c; border-color: #1d7a3c; color: #fff; }
    .btn.go:hover { background: #238c45; }
    .btn[disabled] { opacity: 0.4; cursor: not-allowed; }

    .arm { position: relative; overflow: hidden; padding: 15px 24px; font-size: 0.88rem; }
    .arm .fill { position: absolute; top: 0; bottom: 0; left: 0; width: 0; background: rgba(255, 255, 255, 0.32); pointer-events: none; }
    .arm .txt { position: relative; z-index: 1; }

    .statusline { min-height: 1.2em; font-size: 0.78rem; color: var(--muted); margin-bottom: 10px; }
    .statusline.bad { color: #ff6b60; }
    .statusline.good { color: var(--neon); }

    .warning {
        background: rgba(255, 59, 48, 0.09); border-left: 3px solid var(--red); border-radius: 4px;
        padding: 10px 12px; font-size: 0.78rem; color: #f0c9c5; line-height: 1.55;
    }
    .hint { font-size: 0.73rem; color: #6f7987; line-height: 1.7; }
    kbd {
        background: #22262f; border: 1px solid #363c48; border-bottom-width: 2px; border-radius: 4px;
        padding: 1px 6px; font-size: 0.7rem; font-family: var(--mono); color: #dfe4ea;
    }

    /* Gamepad: steering on the left, throttle on the right, both held down. */
    .gamepad {
        display: flex; justify-content: space-between; gap: 12px;
        margin: 6px 0 14px; touch-action: none;
    }
    .pad-cluster { display: flex; gap: 10px; }
    .pad-btn {
        width: 92px; height: 92px; border-radius: 14px;
        background: var(--ink-2); border: 1px solid var(--line); color: #dfe4ea;
        font-size: 1.6rem; line-height: 1; cursor: pointer;
        touch-action: none; user-select: none; -webkit-user-select: none;
        -webkit-tap-highlight-color: transparent;
    }
    .pad-btn:hover { background: #1b1f27; }
    .pad-btn.held {
        background: var(--neon); border-color: var(--neon); color: #06200e;
        box-shadow: 0 0 24px rgba(0, 230, 118, 0.45);
    }
    [data-key="s"].held { background: var(--amber); border-color: var(--amber); box-shadow: 0 0 24px rgba(255, 179, 0, 0.45); }

    #manual-controls.off { opacity: 0.3; pointer-events: none; }

    /* ---------- tuning ---------- */

    .group { margin-bottom: 18px; }
    .group h2 {
        font-size: 0.72rem; text-transform: uppercase; letter-spacing: 1.4px; color: var(--neon);
        margin: 0 0 10px; padding-bottom: 6px; border-bottom: 1px solid var(--line);
    }
    .row { display: grid; grid-template-columns: 150px 1fr 74px; gap: 10px; align-items: center; margin-bottom: 8px; }
    .row label { font-size: 0.83rem; color: #d5dae1; }
    .row .note { grid-column: 2 / -1; font-size: 0.7rem; color: #6f7987; margin: -4px 0 6px; }
    input[type=range] { width: 100%; accent-color: var(--neon); touch-action: none; }
    input[type=number], select {
        width: 100%; background: #0e1014; border: 1px solid var(--line); color: #fff;
        border-radius: 6px; padding: 5px; font-family: var(--mono); font-size: 0.78rem;
    }
    .num { font-family: var(--mono); font-size: 0.82rem; color: var(--neon); text-align: right; }

    .snippet {
        background: #0e1014; border: 1px solid var(--line); border-radius: 8px; padding: 12px;
        font-family: var(--mono); font-size: 0.73rem; color: #b9f6ca;
        overflow-x: auto; white-space: pre; margin-top: 10px;
    }

    .footer { margin-top: 18px; font-size: 0.7rem; color: #4d5560; letter-spacing: 1px; text-transform: uppercase; }

    @media (max-width: 560px) {
        body { padding: 10px; }
        .hud { padding: 8px; }
        .badge { font-size: 0.6rem; padding: 4px 8px; letter-spacing: 0.6px; }
        .telem { font-size: 0.62rem; padding: 4px 7px; }
        .thr-track { height: 62px; }
        .gauge-value { font-size: 0.82rem; }
        .pad-btn { width: 74px; height: 74px; font-size: 1.3rem; }
        .row { grid-template-columns: 100px 1fr 60px; gap: 8px; }
        .row label { font-size: 0.76rem; }
    }
</style>
</head>
<body>
<div class="container">
    <div class="masthead">
        <h1>PiRacer <span>Pro</span></h1>
        <p>Waveshare AI Kit &middot; Chalmers Folkrace</p>
        <div class="langs">
            <button class="langbtn" data-lang="en" lang="en">EN</button>
            <button class="langbtn" data-lang="zh" lang="zh">中文</button>
        </div>
    </div>

    <div class="stage">
        <img src="/stream.mjpg" alt="Live camera stream" data-i18n-alt="stream.alt">
        <div class="hud">__DASH__</div>
    </div>

    <div class="topbar">
        <span class="badge mode-__INITIAL_MODE__" id="mode-badge">__INITIAL_MODE_TEXT__</span>
        <span class="badge live" id="stream-badge" data-i18n="badge.live"></span>
        <span class="telem" id="telemetry">&mdash;</span>
    </div>
    <div class="deadman" id="deadman" hidden><i id="deadman-fill"></i></div>

    __TABS__
    __PANELS__

    <div class="footer" data-i18n="footer"></div>
</div>

<script>
"use strict";

const HAS_REMOTE = __HAS_REMOTE__;
const ARM_HOLD_MS = __ARM_HOLD_MS__;
const SEND_INTERVAL_MS = __SEND_INTERVAL_MS__;
const TUNE_DEBOUNCE_MS = __TUNE_DEBOUNCE_MS__;
const STEER_RATE = __STEER_RATE__;
const STEER_RETURN = __STEER_RETURN__;
const THROTTLE_RISE = __THROTTLE_RISE__;
const THROTTLE_FALL = __THROTTLE_FALL__;
const MAX_FRAME_DT = __MAX_FRAME_DT__;

/* Both languages arrive in the page, so switching is a matter of rewriting text
   nodes. That is the whole reason there is no navigation here: a reload would drop
   the MJPEG connection, and for an operator mid-drive the deadman with it. */
const I18N = __I18N_JSON__;
const INITIAL_LANG = "__INITIAL_LANG__";
const LANG_KEY = "piracer.lang";
let LANG = INITIAL_LANG;

/* A missing key falls back to English and then to the key itself, so a typo shows
   up as "manual.arm" on the button rather than as an empty one. */
function t(key) {
    const table = I18N[LANG] || I18N.en;
    if (table && table[key] !== undefined) return table[key];
    return I18N.en[key] !== undefined ? I18N.en[key] : key;
}

/* Parameter labels and notes arrive from webcontrol.py as {en, zh}; this is the
   only place in the page that reads that shape rather than this file's table. */
function pick(field) {
    if (!field) return "";
    if (typeof field === "string") return field;
    return field[LANG] || field.en || "";
}

/* localStorage throws outright in some privacy configurations. An operator who
   cannot save a preference still has to be able to drive, so nothing here is
   allowed to break the page. */
function savedLang() {
    try { return localStorage.getItem(LANG_KEY); } catch (e) { return null; }
}

function saveLang(lang) {
    try { localStorage.setItem(LANG_KEY, lang); } catch (e) { /* preference lost, page fine */ }
}

function applyLanguage(lang, persist) {
    if (!I18N[lang]) lang = INITIAL_LANG;
    LANG = lang;
    document.documentElement.lang = lang;
    if (persist) saveLang(lang);

    for (const el of document.querySelectorAll("[data-i18n]")) {
        el.textContent = t(el.getAttribute("data-i18n"));
    }
    /* data-i18n-html is for the two strings carrying inline <strong>/<kbd>. Only
       this file's own literals are ever written through it -- no user input, and
       nothing from the network, reaches innerHTML. */
    for (const el of document.querySelectorAll("[data-i18n-html]")) {
        el.innerHTML = t(el.getAttribute("data-i18n-html"));
    }
    for (const el of document.querySelectorAll("[data-i18n-alt]")) {
        el.alt = t(el.getAttribute("data-i18n-alt"));
    }
    for (const button of document.querySelectorAll(".langbtn")) {
        button.classList.toggle("active", button.dataset.lang === lang);
    }

    // Script-built content has to be redrawn: the schema rows, and the two readouts
    // that carry words rather than numbers. Status lines are deliberately left as
    // they are -- each is a receipt for something that already happened, and
    // rewriting a receipt in another language is worse than leaving it.
    if (groupsBuilt) buildGroups(STATE.schema);
    renderModeBadge();
    renderTelemetry();
}

function bindLangButtons() {
    for (const button of document.querySelectorAll(".langbtn")) {
        button.addEventListener("click", () => applyLanguage(button.dataset.lang, true));
    }
}

/* limits starts at the built-in values rather than {} so the axis integrator has
   real numbers to clamp against on the very first frame; Math.min(x, undefined)
   is NaN, and a NaN throttle sticks to the axis for good. The first state poll
   replaces them with the ones the car is actually running. */
const STATE = {
    mode: "__INITIAL_MODE__",
    params: {}, schema: [],
    limits: { max_throttle: 0.4, max_reverse: -0.25, max_steering: 1.0, deadman_timeout_ms: 800 },
    telemetry: {}, deadman: null
};

/* The driving axes, and which direction keys are physically down right now.
   A key is an intent; the animation loop turns it into an axis value, so both
   the keyboard and the on-screen pad feed the same two numbers. */
const AXIS = { steering: 0, throttle: 0 };
const HELD = { w: false, a: false, s: false, d: false };

const $ = (id) => document.getElementById(id);
const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

function approach(value, target, step) {
    if (value > target) return Math.max(target, value - step);
    if (value < target) return Math.min(target, value + step);
    return target;
}

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
    // Keep the previous limits if a response arrives without them, so a partial
    // payload can never leave the axes integrating against undefined.
    STATE.limits = s.limits || STATE.limits;
    STATE.telemetry = s.telemetry || {};
    STATE.deadman = s.deadman_remaining_ms;

    if (previous !== s.mode) {
        // Never let a stale axis value survive a mode change -- that is exactly
        // how a car lurches the moment it re-arms.
        releaseAll();
        if (s.mode === "manual") startSending(); else stopSending();
        // An in-progress ARM hold belongs to the mode we just left. This must stay
        // inside the "mode actually changed" branch: cancelling on every render
        // would abort the hold on the next 500 ms poll, and ARM would never fire.
        if (holdTimer !== null) cancelHold();
    }

    renderModeBadge();
    renderTelemetry();
    renderDeadman();
    if (!groupsBuilt && STATE.schema.length) buildGroups(STATE.schema);
    syncInputs();
}

function renderModeBadge() {
    const badge = $("mode-badge");
    if (!badge) return;
    badge.textContent = t("badge.mode." + STATE.mode);
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
    // Not named "t" -- that is the translation function.
    const data = STATE.telemetry;
    const parts = [];
    if (data.fps !== undefined) parts.push(t("telem.fps") + " " + Number(data.fps).toFixed(1));
    if (data.steering !== undefined) parts.push(t("telem.steer") + " " + signed(data.steering));
    if (data.throttle !== undefined) parts.push(t("telem.thr") + " " + signed(data.throttle));
    if (data.detected !== undefined) parts.push(data.detected ? t("telem.line_ok") : t("telem.line_lost"));
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

    /* Grouped by the English name: it is the one field webcontrol.py guarantees is
       non-empty, and it does not move when the language changes, so the sections
       keep their order across a switch. The key has to be a string -- Map compares
       keys by identity, and grouping on the {en, zh} object itself would drop every
       parameter into a section of its own. */
    const groups = new Map();
    for (const p of schema) {
        const key = (p.group && p.group.en) || "?";
        if (!groups.has(key)) groups.set(key, []);
        groups.get(key).push(p);
    }

    for (const params of groups.values()) {
        const section = document.createElement("div");
        section.className = "group";
        const heading = document.createElement("h2");
        heading.textContent = pick(params[0].group);
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
    label.textContent = pick(p.label);
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

    const noteText = pick(p.note);
    if (noteText) {
        const note = document.createElement("div");
        note.className = "note";
        note.textContent = noteText;
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
    if (!data) { statusLine("tune-status", t("status.no_response"), "bad"); return; }
    const rejected = data.rejected || {};
    const keys = Object.keys(rejected);
    if (keys.length) {
        statusLine("tune-status", t("status.rejected") + keys.map((k) => k + " (" + rejected[k] + ")").join(", "), "bad");
    } else {
        const count = Object.keys(data.applied || {}).length;
        statusLine("tune-status", t("status.applied").replace("{n}", count), "good");
    }
}

function bindTuningButtons() {
    const resetPid = $("btn-reset-pid");
    if (resetPid) resetPid.addEventListener("click", async () => {
        await postJSON("/api/tune", { action: "reset_pid" });
        statusLine("tune-status", t("status.pid_reset"), "good");
    });

    const resetDefaults = $("btn-reset-defaults");
    if (resetDefaults) resetDefaults.addEventListener("click", async () => {
        await postJSON("/api/tune", { action: "reset_defaults" });
        await pollState();
        statusLine("tune-status", t("status.defaults"), "good");
    });

    const snippet = $("btn-snippet");
    if (snippet) snippet.addEventListener("click", async () => {
        const text = configSnippet();
        const pre = $("snippet");
        pre.textContent = text;
        pre.hidden = false;
        statusLine("tune-status", (await copyText(text))
            ? t("status.copied") : t("status.copy_manual"), "good");
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
 * Manual tab - the driving cockpit
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
        await postJSON("/api/manual", { steering: AXIS.steering, throttle: AXIS.throttle });
    } catch (e) { /* transient network hiccup; the deadman covers a real outage */ }
    finally { inFlight = false; }
}

/* Integrate the held keys into the two axis values.
 *
 * A key press is an intent, not a position. Stepping straight to full lock every
 * time a key goes down shock-loads the steering servo and the ESC, and a car
 * that jumps to max throttle is a miserable thing to drive near a wall. Nothing
 * latches: with no key held, both axes walk back to centre on their own. */
function updateAxes(dt) {
    const steerDir = (HELD.d ? 1 : 0) - (HELD.a ? 1 : 0);
    if (steerDir !== 0) {
        const limit = STATE.limits.max_steering || 1;
        AXIS.steering = clamp(AXIS.steering + steerDir * STEER_RATE * dt, -limit, limit);
    } else {
        AXIS.steering = approach(AXIS.steering, 0, STEER_RETURN * dt);
    }

    const thrDir = (HELD.w ? 1 : 0) - (HELD.s ? 1 : 0);
    if (thrDir > 0) {
        AXIS.throttle = Math.min(AXIS.throttle + THROTTLE_RISE * dt, STATE.limits.max_throttle);
    } else if (thrDir < 0) {
        AXIS.throttle = Math.max(AXIS.throttle - THROTTLE_FALL * dt, STATE.limits.max_reverse);
    } else {
        AXIS.throttle = approach(AXIS.throttle, 0, THROTTLE_FALL * dt);
    }
}

/* The gauges read the local axis values rather than the polled telemetry, so they
   move at 60 fps instead of stepping at the 500 ms state poll. */
function renderDash() {
    const needle = $("needle-steer");
    const fill = $("fill-thr");
    if (!needle || !fill) return;

    const steerLimit = STATE.limits.max_steering || 1;
    const steerRatio = clamp(AXIS.steering / steerLimit, -1, 1);
    needle.style.left = (50 + steerRatio * 50) + "%";
    needle.classList.toggle("wide", Math.abs(steerRatio) > 0.75);

    // The throttle range is asymmetric (+0.40 / -0.25), so the scale is the larger
    // half and the centre line always means zero.
    const thrLimit = Math.max(STATE.limits.max_throttle || 0.4,
                              Math.abs(STATE.limits.max_reverse || 0.25));
    const thrRatio = clamp(AXIS.throttle / thrLimit, -1, 1);
    const span = Math.abs(thrRatio) * 50;
    fill.style.height = span + "%";
    fill.style.bottom = (thrRatio >= 0 ? 50 : 50 - span) + "%";
    fill.classList.toggle("reverse", thrRatio < 0);

    if ($("dash-steer")) $("dash-steer").textContent = signed(AXIS.steering);
    if ($("dash-thr")) $("dash-thr").textContent = signed(AXIS.throttle);
}

/* Released, blurred, hidden, stopped -- every one of them means the operator is no
   longer driving, so the axes and the physical key state are both dropped.
   Clearing HELD matters: no keyup ever arrives for a key held through a window
   blur, and without this that key still reads as pressed on the way back in. */
function releaseAll() {
    for (const key in HELD) HELD[key] = false;
    AXIS.steering = 0;
    AXIS.throttle = 0;
    for (const button of document.querySelectorAll(".pad-btn.held")) button.classList.remove("held");
    renderDash();
}

function syncInputs() {
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
    for (const button of document.querySelectorAll(".pad-btn")) {
        const key = button.dataset.key;
        const press = (event) => {
            event.preventDefault();
            button.setPointerCapture(event.pointerId);
            button.classList.add("held");
            // Arming is a deliberate two-second hold, and a throttle key already
            // down when it completes would launch the car the instant it arms.
            if (STATE.mode !== "manual") return;
            HELD[key] = true;
        };
        const release = () => {
            button.classList.remove("held");
            HELD[key] = false;
        };
        button.addEventListener("pointerdown", press);
        button.addEventListener("pointerup", release);
        // pointercancel fires on an incoming call or a system gesture; without it
        // the finger is gone but the car is still driving.
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
                ? t("status.armed")
                : (t("status.arm_failed") + " " + ((data && data.error) || t("common.no_response"))),
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
        statusLine("manual-status", (data && data.ok) ? t("status.autonomous")
            : (t("status.start_failed") + " " + ((data && data.error) || t("common.no_response"))),
            (data && data.ok) ? "good" : "bad");
    });
}

function doStop() {
    releaseAll();
    cancelHold();
    postJSON("/api/manual", { action: "stop" });
    statusLine("manual-status", t("status.stopped"), "good");
}

/* ------------------------------------------------------------------ *
 * Input, lifecycle
 * ------------------------------------------------------------------ */

function bindKeyboard() {
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
                statusLine("manual-status", (data && data.ok) ? t("status.armed_keyboard")
                    : (t("status.arm_failed") + " " + ((data && data.error) || t("common.no_response"))),
                    (data && data.ok) ? "good" : "bad");
            }, ARM_HOLD_MS);
            return;
        }
        if (key in HELD) {
            event.preventDefault();
            // Same rule as the on-screen pad: a key already down when the ARM hold
            // completes must not be able to launch the car the instant it arms.
            if (STATE.mode !== "manual") return;
            HELD[key] = true;
        }
    });

    window.addEventListener("keyup", (event) => {
        const key = event.key.toLowerCase();
        if (key === "m" && armKeyTimer !== null) { clearTimeout(armKeyTimer); armKeyTimer = null; return; }
        if (key in HELD) HELD[key] = false;
    });

    window.addEventListener("blur", releaseAll);
}

function bindLifecycle() {
    // A backgrounded tab stops being a reliable operator: drop to zero at once
    // rather than let the deadman be the only thing between us and a runaway.
    document.addEventListener("visibilitychange", () => {
        if (!document.hidden) return;
        releaseAll();
        lastFrame = 0;   // the animation clock stopped with the tab; do not integrate the gap
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
            updateHud();
        });
    }
    updateHud();
}

/* The gauge cluster belongs to the driving view, so it follows the Manual tab and
   not the driving mode -- a page parked on Tuning is not being driven. */
function updateHud() {
    const dash = $("hud-dash");
    if (!dash) return;
    dash.hidden = !document.querySelector('.panel[data-panel="manual"].active');
}

let lastFrame = 0;

function driveLoop(now) {
    // Clamped, because a dropped frame must not turn into one enormous step.
    const dt = lastFrame ? Math.min((now - lastFrame) / 1000, MAX_FRAME_DT) : 0;
    lastFrame = now;
    if (STATE.mode === "manual") updateAxes(dt);
    renderDash();
    requestAnimationFrame(driveLoop);
}

function init() {
    bindLangButtons();
    // First, so nothing renders in the wrong language and then flips. A saved
    // choice outranks the Accept-Language the server picked for us: it is the
    // operator's own last decision, and the server cannot know about it.
    applyLanguage(savedLang() || INITIAL_LANG, false);

    bindTabs();
    bindTuningButtons();
    bindManualInputs();
    bindArmButton();
    bindManualButtons();
    bindKeyboard();
    bindLifecycle();

    // Owns the axis integration and the gauges, so it runs whether or not a
    // remote is attached -- with no remote there is simply nothing to drive.
    requestAnimationFrame(driveLoop);

    if (!HAS_REMOTE) return;
    pollState();
    setInterval(pollState, 500);
}

document.addEventListener("DOMContentLoaded", init);
</script>
</body>
</html>
"""


def render_page(remote: Optional[RemoteState], accept_language: str = "") -> str:
    """
    Build the console page for the current launch flags.

    `accept_language` only decides the first paint. The page carries both languages
    and the buttons override it from then on, so a wrong guess costs one click.
    """
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

    lang = pick_language(accept_language)
    # Only the badge is server-rendered; everything else is filled in by
    # applyLanguage() the moment the script runs. That still matters -- the badge
    # sits above the fold, and it is the one element whose first paint a viewer
    # would notice being in the wrong language.
    mode_text = _STRINGS[lang].get("badge.mode." + mode, mode.upper())

    return (_TEMPLATE
            .replace("__I18N_JSON__", _I18N_JSON)
            .replace("__INITIAL_LANG__", lang)
            .replace("__TABS__", _tabs_html(allow_tuning, allow_manual, default_tab))
            .replace("__PANELS__", _panels_html(allow_tuning, allow_manual, default_tab))
            .replace("__DASH__", _dash_html(allow_manual))
            .replace("__INITIAL_MODE_TEXT__", mode_text)
            .replace("__INITIAL_MODE__", mode)
            .replace("__HAS_REMOTE__", "true" if remote is not None else "false")
            .replace("__ARM_HOLD_MS__", str(ARM_HOLD_MS))
            .replace("__SEND_INTERVAL_MS__", str(SEND_INTERVAL_MS))
            .replace("__TUNE_DEBOUNCE_MS__", str(TUNE_DEBOUNCE_MS))
            .replace("__STEER_RATE__", str(STEER_RATE))
            .replace("__STEER_RETURN__", str(STEER_RETURN))
            .replace("__THROTTLE_RISE__", str(THROTTLE_RISE))
            .replace("__THROTTLE_FALL__", str(THROTTLE_FALL))
            .replace("__MAX_FRAME_DT__", str(MAX_FRAME_DT)))
