**简体中文** | [English](MANUAL-CHECKS-en.md)

# 人工操作与测试清单

开发机上没有 numpy / cv2 / Picamera2 / RPi.GPIO / piracer，因此 `main.py` 的主循环
**从未端到端跑过**，视频叠加横幅也只做过代码层面的检查。下面每一项都需要在树莓派上
由人执行 —— 没打勾的一律当作"未验证"。

---

## 1. 部署（树莓派）

- [ ] 安装依赖：`opencv-python` `python3-numpy` `python3-picamera2`，以及 `pip3 install piracer-py`
- [ ] `i2cdetect -y 1` 能看到 PCA9685 的 `0x40`
- [ ] **车轮悬空**跑 `python3 test_hardware.py`，I2C / ESC 解锁 / 舵机扫掠 / 电机正反转 / 相机五项全过

## 2. 台架测试 —— 必做，车轮悬空

先临时降速，防止手滑冲出去：

- [ ] 把 `config.py` 里 `RemoteConfig.max_manual_throttle` 改成 `0.15`、`max_manual_reverse` 改成 `-0.10`
- [ ] 启动：`python3 main.py --stream --allow-manual`
- [ ] 电脑/手机与树莓派连同一个 Wi-Fi，打开 `http://<树莓派IP>:8080`

逐项确认：

- [ ] 启动后车**不动**，画面顶部是橙色 `PAUSED - CAR HELD`，徽章显示 `PAUSED`
- [ ] 短按 ARM（<2 秒）后松手 → **不应**进入 MANUAL
- [ ] 长按 ARM 满 2 秒（进度条走满）→ 进入 MANUAL，横幅变红 `MANUAL CONTROL - NOT AUTONOMOUS`
- [ ] 长按中途把手指移出按钮 → 应取消，不进 MANUAL
- [ ] 进入 MANUAL 后**什么都不按**，等 3 秒 → 轮子一动不动（解锁 ≠ 开动）
- [ ] 按住 ▲ 油门 → 轮子**逐渐**加速（约 0.45 秒到顶）；松开 → 约 0.2 秒回零并停住
- [ ] 按 ◀ / ▶ 转向 → **确认方向与画面一致**。反了要改 `config.py` 的 `invert_steering`
      （它刻意不在网页可调列表里）；松手后指针应自己回到中位
- [ ] 画面底部仪表跟着动：转向圆点随 ◀ ▶ 移动，油门条随 ▲ ▼ 涨落（绿=前进，琥珀=倒车）
- [ ] 键盘：`W` `S` `A` `D`、`Space` 急停、长按 `M` 2 秒 = ARM
- [ ] **按着 `W` 时 Alt-Tab 切走窗口** → 轮子立刻停；切回来重新按键应正常响应
      （按键状态必须被清掉，否则那个键会一直算作按着）
- [ ] 右上角 `EN` / `中文` 按钮切换语言 → **画面不闪断、不重连**，Tuning 里的参数名
      与说明也跟着变；刷新后仍是上次选的语言（切换若导致重新加载，正在驾驶时会触发死手）
- [ ] **死手 A**：按住油门按钮的同时**直接关掉浏览器标签页** → 0.8 秒内轮子停
- [ ] **死手 B**：按住油门时拔掉网线 / 关掉 Wi-Fi → 0.8 秒内停，画面横幅变
      `DEADMAN - COMMANDS LOST`，网页徽章变**琥珀色闪烁**的 `MANUAL - 指令没送达`，
      且模式**仍是 MANUAL**（绝不自动回到自主驾驶）
- [ ] 接死手 B，网还没恢复时**按着 `W` 别松** → 仪表上的油门条和转向指针应**停在零**。
      车既然收不到指令，页面就不该继续把轴往上拧
- [ ] 接死手 B，把网接回去、**`W` 全程按着** → 车从零**重新爬**上去，不能"攒了一脚
      油门"猛冲一下；徽章同时变回红色 `MANUAL - 非自主控制`。这一条是这次修复的主症状
      （旧版松手瞬间会窜一下），务必实测
- [ ] 网络恢复后按 `START AUTONOMOUS` → 回到 AUTO，横幅消失
- [ ] **调参生效（关键）**：Tuning 标签页把 `Kp` 从 0.65 拖到 0.05 →
      画面下方遥测条的 `Steer` 幅值应**立刻**变小。这是 PID 增益值拷贝陷阱的现场验证，
      若没变化说明热改参数根本没生效
- [ ] 把 `ROI top` 拖到最大 0.90 → 与 `ROI bottom` 0.95 冲突，应被整批拒绝并弹回
- [ ] `Reset PID State` 有反馈；`Copy as config.py` 能复制出一段可粘贴的文本
- [ ] 用**手机**打开页面，摸一遍 ◀ ▶ ▲ ▼ 四个按钮，确认松手即停（触屏的
      `pointercancel` 路径完全没在真机验证过）
- [ ] 若装了超声波：手动模式下拿挡板靠近 → 应触发紧急停车（**紧急制动在任何模式下都有效**）
- [ ] `Ctrl-C` 退出 → 日志出现 safe stop，进程正常结束，轮子不再有输出
- [ ] **测完把 `max_manual_throttle` / `max_manual_reverse` 改回 `0.40` / `-0.25`**

## 3. 权限门验证（安全核心，建议在树莓派本机跑）

网页访问者不应有任何办法开启控制。以下命令在**树莓派本机**执行（Linux 引号最干净）：

- [ ] `python3 main.py --stream` 启动后打开网页 → **只有视频，没有任何标签页**
- [ ] 同一进程下：
      ```bash
      curl -i -X POST http://127.0.0.1:8080/api/manual -H 'Content-Type: application/json' -d '{"action":"arm"}'
      ```
      → 必须 **403**
- [ ] ```bash
      curl -i -X POST http://127.0.0.1:8080/api/tune -H 'Content-Type: application/json' -d '{"kp":0.9}'
      ```
      → 必须 **403**
- [ ] 去掉 `-H 'Content-Type: ...'` 再发一次 → 必须 **415**
- [ ] 改用 `--allow-tuning` 启动 → `/api/tune` 正常，但 `/api/manual` **仍然 403**
- [ ] 改用 `--allow-manual` 启动 → `/api/manual` 才返回 200

> PowerShell 里 `curl` 是 `Invoke-WebRequest` 的别名，要用 `curl.exe`，且 JSON 引号
> 需要 `--%` 才能原样传递 —— 所以更推荐在树莓派上测。

## 4. 赛道调参

- [ ] `python3 main.py --stream --allow-tuning`（车仍自主循线，参数热改）
- [ ] 边跑边调 PID，找到满意值后按 `Copy as config.py`
- [ ] 把数值写回 `config.py` —— 调参只存在于内存，**程序退出即丢失**

## 5. 比赛

- [ ] 比赛命令是 `python3 main.py --throttle 0.32`，**不加任何新参数**
- [ ] 确认这个命令下网页仍是纯视频、行为与加本功能之前完全一致

---

## 6. 需要人工决定的事

- [ ] **两份 README 的数字与代码不符**：`base_throttle` 文档写 0.28、实际 0.30；
      `turn_slowdown_factor` 文档写 0.5、实际 0.4。改文档还是改代码？
- [ ] `RemoteConfig.max_manual_throttle = 0.40` 是否合适（自主驾驶上限是 0.50）
