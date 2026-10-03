[简体中文](MANUAL-CHECKS.md) | **English**

# Manual Operations and Test Checklist

The development machine has no numpy / cv2 / Picamera2 / RPi.GPIO / piracer, so
`main.py`'s main loop **has never run end to end**, and the video overlay has only
been checked at the code level. Every item below must be performed by a person on the
Raspberry Pi — treat anything unticked as unverified.

---

## 1. Deployment (on the Pi)

- [ ] Install dependencies: `python3-opencv` `python3-numpy` `python3-picamera2`, plus `pip3 install piracer-py`
- [ ] `i2cdetect -y 1` shows the PCA9685 at `0x40`
- [ ] With the **wheels off the ground**, run `python3 test_hardware.py` and pass all five: I2C / ESC arming / servo sweep / motor forward and reverse / camera

## 2. Bench test — mandatory, wheels off the ground

Lower the speed first, so a slip of the finger cannot launch the car:

- [ ] Set `RemoteConfig.max_manual_throttle` to `0.15` and `max_manual_reverse` to `-0.10` in `config.py`
- [ ] Start: `python3 main.py --stream --allow-manual`
- [ ] Put the PC or phone on the same Wi-Fi as the Pi and open `http://<PiIP>:8080`

Confirm each of these:

- [ ] The car **does not move** on startup; the top of the video shows an orange `PAUSED - CAR HELD` banner and the badge reads `PAUSED`
- [ ] A short press of ARM (<2 s) then release → must **not** enter MANUAL
- [ ] Hold ARM for the full 2 s (the progress bar fills) → enters MANUAL and the banner turns red `MANUAL CONTROL - NOT AUTONOMOUS`
- [ ] During a hold, slide the finger off the button → must cancel, no MANUAL
- [ ] Once in MANUAL, **press nothing** and wait 3 s → the wheels do not move at all (armed is not moving)
- [ ] Hold the ▲ throttle button → wheels **ramp up** (about 0.45 s to the top); release → back to zero in about 0.2 s
- [ ] Press ◀ / ▶ to steer → **confirm the direction matches the video**. If it is reversed, change `invert_steering` in `config.py` (it is deliberately not exposed in the web UI); releasing should let the needle walk back to centre
- [ ] The gauges at the bottom of the picture follow along: the steering dot tracks ◀ ▶, the throttle bar tracks ▲ ▼ (green forward, amber reverse)
- [ ] Keyboard: `W` `S` `A` `D`, `Space` to stop, hold `M` for 2 s to ARM
- [ ] **Alt-Tab away while holding `W`** → wheels stop at once; after switching back, pressing a key again must work normally (the held keys have to be cleared, or that key stays stuck down)
- [ ] The `EN` / `中文` buttons in the top right switch language → the **video must not flicker or reconnect**, and the parameter names and notes in the Tuning tab must change with it; reload → the choice stuck (a switch that reloads the page would trip the deadman mid-drive)
- [ ] **Deadman A**: while holding the throttle, **close the browser tab outright** → wheels stop within 0.8 s
- [ ] **Deadman B**: while holding the throttle, unplug the network cable or turn off Wi-Fi → wheels stop within 0.8 s, the banner becomes `DEADMAN - COMMANDS LOST`, and the mode **stays MANUAL** (it never falls back to autonomous)
- [ ] After the network returns, press `START AUTONOMOUS` → back to AUTO and the banner disappears
- [ ] **Tuning actually applies (critical)**: in the Tuning tab, drag `Kp` from 0.65 to 0.05 → the `Steer` amplitude on the telemetry strip must shrink **immediately**. This is the on-car check for the PID gain value-copy trap; if nothing changes, live tuning is not reaching the controller at all
- [ ] Drag `ROI top` to its maximum of 0.90 → it conflicts with `ROI bottom` 0.95, so the whole batch must be refused and the slider snapped back
- [ ] `Reset PID State` gives feedback; `Copy as config.py` copies pasteable text
- [ ] Open the page on a **phone** and work through the ◀ ▶ ▲ ▼ buttons — releasing must stop the car (the touch `pointercancel` path has never been exercised on real hardware)
- [ ] If ultrasonics are fitted: in manual mode, bring a board close → the emergency stop must fire (**the emergency brake stays active in every mode**)
- [ ] `Ctrl-C` → the log shows a safe stop, the process exits cleanly, and the motors receive no further output
- [ ] **Restore `max_manual_throttle` / `max_manual_reverse` to `0.40` / `-0.25`**

## 3. Permission gates (the security core — run these on the Pi itself)

A page visitor must have no way to enable control. Run these **on the Raspberry Pi** (quoting is cleanest on Linux):

- [ ] Start `python3 main.py --stream`, open the page → **video only, no tabs at all**
- [ ] In the same process:
      ```bash
      curl -i -X POST http://127.0.0.1:8080/api/manual -H 'Content-Type: application/json' -d '{"action":"arm"}'
      ```
      → must be **403**
- [ ] ```bash
      curl -i -X POST http://127.0.0.1:8080/api/tune -H 'Content-Type: application/json' -d '{"kp":0.9}'
      ```
      → must be **403**
- [ ] Drop the `-H 'Content-Type: ...'` and send again → must be **415**
- [ ] Restart with `--allow-tuning` → `/api/tune` works, but `/api/manual` is **still 403**
- [ ] Restart with `--allow-manual` → only then does `/api/manual` return 200

> In PowerShell `curl` is an alias for `Invoke-WebRequest`, so you must write `curl.exe`,
> and the JSON quotes need `--%` to pass through untouched — which is why testing on the
> Pi itself is preferable.

## 4. Track tuning

- [ ] `python3 main.py --stream --allow-tuning` (the car keeps following the line autonomously; parameters apply live)
- [ ] Tune the PID while driving, then press `Copy as config.py` when you are happy
- [ ] Write the values back into `config.py` — tuning lives in memory only and is **lost when the program exits**

## 5. Race day

- [ ] The race command is `python3 main.py --throttle 0.32`, with **none of the new flags**
- [ ] Confirm that command still serves a plain video page and behaves exactly as it did before this feature existed

---

## 6. Decisions a human has to make

- [ ] **Both READMEs disagree with the code**: `base_throttle` is documented as 0.28 but is 0.30, and `turn_slowdown_factor` is documented as 0.5 but is 0.4. Fix the docs or the code?
- [ ] Is `RemoteConfig.max_manual_throttle = 0.40` appropriate (autonomous driving is capped at 0.50)?
