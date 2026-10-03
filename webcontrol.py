"""
Remote control state for web-based debugging (live parameter tuning + manual drive).

This module is deliberately free of HTTP, hardware and OpenCV dependencies so the
state machine and the parameter validation can be exercised on a development
machine without a Raspberry Pi, a camera, or the car.

Threading model (mirrors SensorManager._distance_lock in sensors.py): HTTP handler
threads never touch the vehicle or the hardware. They only update cached values
under a lock, and the main control loop reads a single snapshot per frame.
"""

import logging
import threading
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from config import AppConfig, RemoteConfig

# Driving modes. The car is autonomous unless a human explicitly changes this,
# and only ever from PAUSED.
MODE_AUTO = "auto"       # Autonomous line following. Remote drive commands are ignored.
MODE_PAUSED = "paused"   # Car stopped, waiting for an operator. The resting state.
MODE_MANUAL = "manual"   # Operator drives, protected by the deadman timeout.

# Command sources reported to the main loop and drawn onto the video overlay.
SOURCE_AUTO = "auto"
SOURCE_PAUSED = "paused"
SOURCE_MANUAL = "manual"
SOURCE_DEADMAN = "deadman"


@dataclass(frozen=True)
class DriveCommand:
    """One operator command resolved for a single main-loop iteration."""
    source: str
    steering: float
    throttle: float


@dataclass(frozen=True)
class Param:
    """A single remotely tunable configuration field."""
    key: str                  # Dotted path into AppConfig, e.g. "control.kp".
    label: str                # Short name shown next to the slider.
    group: str                # UI section heading.
    kind: str                 # "float" | "int" | "enum"
    minimum: float = 0.0
    maximum: float = 1.0
    step: float = 0.01
    choices: Tuple[str, ...] = ()
    note: str = ""
    # Simplified Chinese for the same three slots, shown when the console is
    # switched to 中文. Empty means "falls back to the English above", which is the
    # right answer for the ones that are notation already (Kp, Ki, ROI, Canny).
    label_zh: str = ""
    group_zh: str = ""
    note_zh: str = ""

    def coerce(self, raw):
        """Validate one incoming value and convert it to the target type."""
        if self.kind == "enum":
            if raw not in self.choices:
                raise ValueError(f"must be one of: {', '.join(self.choices)}")
            return raw

        # bool is an int subclass, and JSON true/false must not silently become 1/0.
        if isinstance(raw, bool):
            raise ValueError("must be a number")
        try:
            value = int(raw) if self.kind == "int" else float(raw)
        except (TypeError, ValueError):
            raise ValueError("must be a number")

        if value != value or value in (float("inf"), float("-inf")):
            raise ValueError("must be a finite number")
        if not (self.minimum <= value <= self.maximum):
            raise ValueError(f"must be within [{self.minimum}, {self.maximum}]")
        return value

    def to_dict(self) -> dict:
        """
        Serialise for the web UI.

        Both languages travel in the same payload so that switching language can
        rebuild the tab in place. Re-fetching the schema would mean a page reload,
        and a reload drops the MJPEG connection -- and an operator mid-drive into
        the deadman.
        """
        return {
            "key": self.key,
            "label": {"en": self.label, "zh": self.label_zh or self.label},
            "group": {"en": self.group, "zh": self.group_zh or self.group},
            "kind": self.kind,
            "min": self.minimum,
            "max": self.maximum,
            "step": self.step,
            "choices": list(self.choices),
            "note": {"en": self.note, "zh": self.note_zh or self.note},
        }


# Whitelist of everything the tuning tab may change.
#
# Deliberately NOT tunable, and the reasons matter:
#   vision.show_debug_window  - vision.py reads it every frame to decide whether to
#                               build the debug frame; turning it off strips the whole
#                               overlay off the video stream.
#   control.invert_steering   - flipping it while driving means full opposite lock.
#   control.invert_throttle   - flipping it while driving means full reverse.
#   control.esc_arm_time      - only meaningful during startup.
#   control.min/max_steering  - bounds of the steering authority itself.
#   SensorConfig.*            - the emergency distance thresholds are the safety
#                               layer; being able to lower them remotely is being
#                               able to switch that layer off.
TUNABLES: Tuple[Param, ...] = (
    Param("control.kp", "Kp", "Steering PID", "float", 0.0, 2.0, 0.01,
          note="Higher reacts sooner to lane error; too high oscillates.",
          group_zh="转向 PID",
          note_zh="越高对循线误差反应越快；过高会震荡。"),
    Param("control.ki", "Ki", "Steering PID", "float", 0.0, 1.0, 0.01,
          note="Corrects steady offset; rarely needed on a symmetric track.",
          group_zh="转向 PID",
          note_zh="修正固定偏移；对称赛道上基本用不到。"),
    Param("control.kd", "Kd", "Steering PID", "float", 0.0, 1.0, 0.01,
          note="Dampens oscillation on straights.",
          group_zh="转向 PID",
          note_zh="抑制直道上的左右摆动。"),

    Param("control.base_throttle", "Base throttle", "Speed", "float", 0.0, 0.6, 0.01,
          label_zh="基础油门", group_zh="速度"),
    Param("control.max_throttle", "Max throttle", "Speed", "float", 0.0, 0.8, 0.01,
          label_zh="最高油门", group_zh="速度"),
    Param("control.min_throttle", "Min throttle", "Speed", "float", 0.0, 0.5, 0.01,
          label_zh="最低油门", group_zh="速度"),
    Param("control.throttle_deadband", "Throttle deadband", "Speed", "float", 0.0, 0.4, 0.01,
          note="Below this the motor does not overcome static friction.",
          label_zh="油门死区", group_zh="速度",
          note_zh="低于此值电机克服不了静摩擦，车子不会动。"),
    Param("control.turn_slowdown_factor", "Turn slowdown", "Speed", "float", 0.0, 1.0, 0.01,
          label_zh="弯道减速", group_zh="速度"),
    Param("control.reverse_throttle", "Reverse throttle", "Speed", "float", -0.5, 0.0, 0.01,
          label_zh="倒车油门", group_zh="速度"),

    Param("control.steering_trim", "Steering trim", "Steering", "float", -0.3, 0.3, 0.005,
          note="Hardware zero-point calibration.",
          label_zh="转向中位微调", group_zh="转向",
          note_zh="硬件零点校准，补偿舵机中位偏。"),

    Param("vision.roi_top_ratio", "ROI top", "Region of Interest", "float", 0.0, 0.9, 0.01,
          note="Ignore ceiling and horizon.",
          label_zh="ROI 上界", group_zh="感兴趣区域",
          note_zh="忽略天花板和远处背景。"),
    Param("vision.roi_bottom_ratio", "ROI bottom", "Region of Interest", "float", 0.1, 1.0, 0.01,
          note="Ignore the bumper shadow. Must stay above ROI top.",
          label_zh="ROI 下界", group_zh="感兴趣区域",
          note_zh="忽略车头保险杠阴影。必须保持在 ROI 上界之下。"),

    Param("vision.detection_mode", "Detection mode", "Track Detection", "enum",
          choices=("edge_contours", "lane_line", "color_mask"),
          label_zh="检测模式", group_zh="赛道检测"),
    Param("vision.num_scan_slices", "Scan slices", "Track Detection", "int", 1, 12, 1,
          note="Too many slices per ROI leaves too few edge pixels per slice.",
          label_zh="扫描切片数", group_zh="赛道检测",
          note_zh="切片太多会让每片里的边缘像素过少，反而测不准。"),
    Param("vision.canny_threshold1", "Canny low", "Track Detection", "int", 0, 255, 1,
          note="Combined with an adaptive estimate, so the effect may be muted.",
          label_zh="Canny 低阈值", group_zh="赛道检测",
          note_zh="会与自适应估计值合并取值，效果可能不明显。"),
    Param("vision.canny_threshold2", "Canny high", "Track Detection", "int", 0, 255, 1,
          note="Combined with an adaptive estimate, so the effect may be muted.",
          label_zh="Canny 高阈值", group_zh="赛道检测",
          note_zh="会与自适应估计值合并取值，效果可能不明显。"),
)

PARAMS_BY_KEY: Dict[str, Param] = {param.key: param for param in TUNABLES}

# Allow the flat spelling the UI uses: "kp" resolves to "control.kp".
SHORT_NAMES: Dict[str, str] = {p.key.rsplit(".", 1)[-1]: p.key for p in TUNABLES}

# The smallest allowed gap between the ROI bounds.
_MIN_ROI_SPAN = 0.05


def _get_config_value(config: AppConfig, key: str):
    section, _, field_name = key.partition(".")
    return getattr(getattr(config, section), field_name)


def _set_config_value(config: AppConfig, key: str, value) -> None:
    """
    Write a single field in place.

    Never rebind a sub-config object (e.g. `config.control = ControlConfig(...)`):
    VehicleController and RoadPerception hold references to the originals and would
    keep reading the stale one.
    """
    section, _, field_name = key.partition(".")
    setattr(getattr(config, section), field_name, value)


def _flatten(payload: dict) -> Dict[str, object]:
    """Accept both {"control": {"kp": 0.7}} and {"control.kp": 0.7} / {"kp": 0.7}."""
    flat: Dict[str, object] = {}
    for key, value in payload.items():
        if isinstance(value, dict):
            for sub_key, sub_value in value.items():
                flat[f"{key}.{sub_key}"] = sub_value
        else:
            flat[key] = value
    return flat


def roi_invariant_violation(config: AppConfig) -> Optional[str]:
    """
    Check the cross-field invariant between the two ROI bounds.

    An inverted ROI crops to an empty image, vision then reports "track lost" on
    every frame, and controller.compute_control keeps the car rolling at
    min_throttle in a straight line. Single-field range checks cannot catch this.
    """
    if config.vision.roi_top_ratio >= config.vision.roi_bottom_ratio - _MIN_ROI_SPAN:
        return f"ROI top must stay at least {_MIN_ROI_SPAN} below ROI bottom"
    return None


class RemoteState:
    """
    Thread-safe bridge between the HTTP handler threads and the main control loop.

    HTTP threads call the setter methods; the main loop calls resolve() once per
    frame. Nothing here touches hardware.
    """

    def __init__(self, config: AppConfig, remote: RemoteConfig):
        self.config = config
        self.remote = remote

        self._lock = threading.Lock()
        # Manual driving is only ever entered from PAUSED, so an --allow-manual run
        # starts stopped and waits for the operator instead of driving off.
        self._mode = MODE_PAUSED if remote.allow_manual else MODE_AUTO
        self._steering = 0.0
        self._throttle = 0.0
        self._last_cmd_ts: Optional[float] = None   # time.monotonic() domain
        self._reset_pid_requested = True
        self._logged_source: Optional[str] = None
        self._telemetry: dict = {}

    # ------------------------------------------------------------------
    # Main control loop side
    # ------------------------------------------------------------------

    def resolve(self, now: float) -> Optional[DriveCommand]:
        """
        Resolve the drive command for one main-loop iteration.

        Returns None to stay fully autonomous. Otherwise returns a DriveCommand --
        including (0, 0) when paused or when the deadman has expired. It never
        returns None for a non-autonomous mode: falling back to autonomous after an
        operator disconnect would make the car accelerate away on its own.
        """
        with self._lock:
            mode = self._mode
            if mode == MODE_AUTO:
                source, command = SOURCE_AUTO, None
            elif mode == MODE_PAUSED:
                source, command = SOURCE_PAUSED, DriveCommand(SOURCE_PAUSED, 0.0, 0.0)
            else:
                # No command since arming counts as stale, so arming alone never moves the car.
                stale = (self._last_cmd_ts is None) or \
                        (now - self._last_cmd_ts > self.remote.deadman_timeout_s)
                if stale:
                    source, command = SOURCE_DEADMAN, DriveCommand(SOURCE_DEADMAN, 0.0, 0.0)
                else:
                    source = SOURCE_MANUAL
                    command = DriveCommand(SOURCE_MANUAL, self._steering, self._throttle)

            changed = source != self._logged_source
            if changed:
                self._logged_source = source

        if changed:
            logging.info(f"Drive source -> {source} (mode={mode})")
        return command

    def consume_pid_reset(self) -> bool:
        """One-shot flag consumed by the main loop on a driving-mode transition."""
        with self._lock:
            requested, self._reset_pid_requested = self._reset_pid_requested, False
        return requested

    def publish_telemetry(self, telemetry: dict) -> None:
        """Called by the main loop once per frame to feed the web telemetry strip."""
        with self._lock:
            self._telemetry = dict(telemetry)

    # ------------------------------------------------------------------
    # HTTP side
    # ------------------------------------------------------------------

    def set_mode(self, action: str) -> dict:
        """Handle arm / stop / start. Returns a JSON-serialisable result."""
        with self._lock:
            if action == "arm":
                if not self.remote.allow_manual:
                    return {"ok": False, "error": "manual control is not enabled"}
                if self._mode != MODE_PAUSED:
                    return {"ok": False,
                            "error": f"can only arm from paused (currently {self._mode})"}
                self._mode = MODE_MANUAL
                self._steering = 0.0
                self._throttle = 0.0
                # Arming alone must not move the car: require a fresh drive command.
                self._last_cmd_ts = None
                self._reset_pid_requested = True
                logging.warning("MANUAL CONTROL ARMED from the web UI (deadman %.0f ms).",
                                self.remote.deadman_timeout_s * 1000.0)

            elif action == "stop":
                # Reachable from every mode, and always safe.
                if self._mode != MODE_PAUSED:
                    logging.info("Drive mode -> paused (stop requested from the web UI).")
                self._mode = MODE_PAUSED
                self._steering = 0.0
                self._throttle = 0.0
                self._last_cmd_ts = None
                self._reset_pid_requested = True

            elif action == "start":
                if not self.remote.allow_manual:
                    return {"ok": False, "error": "not enabled"}
                if self._mode != MODE_PAUSED:
                    return {"ok": False,
                            "error": f"can only start from paused (currently {self._mode})"}
                self._mode = MODE_AUTO
                self._reset_pid_requested = True
                logging.info("Autonomous drive resumed from the web UI.")

            else:
                return {"ok": False, "error": f"unknown action '{action}'"}

            return {"ok": True, "mode": self._mode}

    def set_drive(self, steering: float, throttle: float) -> dict:
        """Accept one manual drive command. Clamped here and again in the main loop."""
        with self._lock:
            if not self.remote.allow_manual:
                return {"ok": False, "error": "manual control is not enabled"}
            if self._mode != MODE_MANUAL:
                # A stale page must never be able to drive, or re-arm, the car.
                return {"ok": False, "error": f"not armed (mode={self._mode})"}

            self._steering = self._clamp(steering,
                                         -self.remote.max_manual_steering,
                                         self.remote.max_manual_steering)
            self._throttle = self._clamp(throttle,
                                         self.remote.max_manual_reverse,
                                         self.remote.max_manual_throttle)
            self._last_cmd_ts = time.monotonic()
            return {"ok": True, "mode": self._mode}

    def apply_tuning(self, payload: dict) -> Tuple[dict, dict]:
        """
        Validate and apply a tuning payload.

        Returns:
            applied (dict): parameter key -> new value, for the keys that took effect.
            rejected (dict): parameter key -> reason, for the keys that did not.
        """
        if not self.remote.allow_tuning:
            return {}, {"*": "live tuning is not enabled"}

        applied: Dict[str, object] = {}
        rejected: Dict[str, str] = {}

        with self._lock:
            if payload.get("action") == "reset_defaults":
                return self._reset_defaults(), {}

            if payload.get("action") == "reset_pid":
                self._reset_pid_requested = True
                return {"action": "reset_pid"}, {}

            # 1. Validate the whole batch before touching the live config.
            #    Both result dicts are keyed by the canonical dotted name so the UI
            #    can match a rejection back to the control that produced it.
            pending: Dict[str, object] = {}
            for raw_key, raw_value in _flatten(payload).items():
                key = SHORT_NAMES.get(raw_key, raw_key)
                param = PARAMS_BY_KEY.get(key)
                if param is None:
                    rejected[key] = "not a tunable parameter"
                    continue
                try:
                    pending[key] = param.coerce(raw_value)
                except ValueError as exc:
                    rejected[key] = str(exc)

            if not pending:
                return applied, rejected

            # 2. Apply, remembering the previous values in case the batch is rejected.
            previous = {key: _get_config_value(self.config, key) for key in pending}
            for key, value in pending.items():
                _set_config_value(self.config, key, value)

            # 3. Cross-field invariant: reject the whole batch rather than leave the
            #    car in a state that makes it drive blind.
            problem = roi_invariant_violation(self.config)
            if problem is not None:
                for key, value in previous.items():
                    _set_config_value(self.config, key, value)
                for key in pending:
                    rejected[key] = problem
            else:
                applied = dict(pending)

        return applied, rejected

    def snapshot(self) -> dict:
        """Full state for the web UI: permissions, mode, limits, parameter values."""
        with self._lock:
            mode = self._mode
            remaining_ms: Optional[int] = None
            if mode == MODE_MANUAL and self._last_cmd_ts is not None:
                remaining = self.remote.deadman_timeout_s - (time.monotonic() - self._last_cmd_ts)
                remaining_ms = max(0, int(remaining * 1000))
            telemetry = dict(self._telemetry)

        return {
            "permissions": {
                "tuning": self.remote.allow_tuning,
                "manual": self.remote.allow_manual,
            },
            "mode": mode,
            "limits": {
                "max_throttle": self.remote.max_manual_throttle,
                "max_reverse": self.remote.max_manual_reverse,
                "max_steering": self.remote.max_manual_steering,
                "deadman_timeout_ms": int(self.remote.deadman_timeout_s * 1000),
            },
            "params": {param.key: _get_config_value(self.config, param.key)
                       for param in TUNABLES},
            "schema": [param.to_dict() for param in TUNABLES],
            "telemetry": telemetry,
            "deadman_remaining_ms": remaining_ms,
        }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _reset_defaults(self) -> dict:
        """Write the dataclass defaults back field by field (never rebind the object)."""
        from config import ControlConfig, VisionConfig

        defaults = {"control": ControlConfig(), "vision": VisionConfig()}
        restored: Dict[str, object] = {}
        for param in TUNABLES:
            section, _, field_name = param.key.partition(".")
            value = getattr(defaults[section], field_name)
            _set_config_value(self.config, param.key, value)
            restored[param.key] = value
        return restored

    @staticmethod
    def _clamp(value: float, low: float, high: float) -> float:
        try:
            value = float(value)
        except (TypeError, ValueError):
            return 0.0
        if value != value:   # NaN
            return 0.0
        return float(max(low, min(high, value)))
