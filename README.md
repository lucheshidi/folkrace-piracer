# WaveShare PiRacer Pro - Chalmers Folkrace 自动驾驶控制程序

本项目是专为 **WaveShare PiRacer Pro AI Kit** 参加 **Chalmers 机器人 Folkrace 比赛** 设计的自动驾驶巡线与路况感知控制系统。系统基于 **OpenCV2**、**NumPy**、**Picamera2** 和 **PiRacerPro** 硬件驱动，并预留了**两侧红外测距/超声波避障传感器扩展接口**。

---

## 📁 项目架构

- **`config.py`**：核心参数配置文件（包含相机分辨率、HSV 赛道阈值、ROI 裁剪区域、PID 转向参数、动态速度限制以及传感器 GPIO 引脚映射）。
- **`camera.py`**：相机抽象封装（优先使用树莓派官方 `Picamera2` 采集，支持本地 OpenCV 摄像头及无硬件合成帧调试回退）。
- **`vision.py`**：计算机视觉赛道感知模块（多层水平切片加权质心扫描、自适应/HSV 赛道提取、前瞻距离计算）。
- **`controller.py`**：PID 转向控制器与 PiRacerPro 底盘控制封装（支持弯道自适应减速、失焦减速寻迹与紧急断电保护）。
- **`sensors.py`**：左右两侧超声波（HC-SR04）与红外避障传感器管理模块（贴墙推力修正与紧急制动）。
- **`main.py`**：系统主控制循环入口（支持帧率控制、键盘/系统信号安全中断退出与调试窗口可视化）。

---

## 🚀 树莓派环境安装与依赖

在 PiRacer Pro（Raspberry Pi OS Bookworm / Bullseye）上运行：

```bash
# 1. 更新系统并安装系统级依赖
sudo apt update
sudo apt install -y python3-pip python3-opencv python3-numpy python3-rpi.gpio python3-smbus

# 2. 安装 Picamera2（通常 Bookworm 镜像已预装）
sudo apt install -y python3-picamera2

# 3. 安装底盘与舵机驱动库（二选一或均安装，程序自动识别）
pip3 install piracer-py
# 或者使用 Adafruit ServoKit 驱动 PCA9685
pip3 install adafruit-circuitpython-servokit
```

---

## 🔧 硬件独立自检与诊断 (重要)

在正式开始自主巡线前，请先运行硬件自检脚本（**注意：测试前请将小车车轮悬空架起，防止飞车**）：

```bash
python3 test_hardware.py
```

该脚本将依次测试：
1. **I2C 总线与 PCA9685 芯片通信 (0x40)**
2. **ESC 电调中位自检解锁序列 (1.5s)**
3. **转向舵机摆动 (居中 -> 左转 -> 居中 -> 右转 -> 居中)**
4. **后驱电机旋转 (前进 0.28 -> 刹车 -> 后退 -0.25 -> 停止)**
5. **Picamera2 摄像头图像采集**

---

## 🎮 运行方式

### 1. 局域网 Web 实时投屏模式（推荐：在电脑/手机浏览器中直接查看画面）
在树莓派上启动推流：
```bash
python3 main.py --stream
```
然后在电脑或手机浏览器（与树莓派处于同一 Wi-Fi）中打开：
```text
http://<树莓派IP>:8080
```
> 页面将实时显示小车摄像头前视画面、赛道中线识别轨迹以及实时遥测数据（FPS、实时转向角 Steer、实时油门 Thr）。
> 可自定义端口：`python3 main.py --stream --port 8080 --throttle 0.32`

### 2. 比赛实车运行（极速无界面模式，最高帧率）
```bash
python3 main.py --throttle 0.32
```

### 3. 本地桌面 GUI 调试模式（需接 HDMI 屏幕或 X11 转发）
```bash
python3 main.py --display
```

### 4. 启用两侧超声波/红外传感器避障
```bash
python3 main.py --stream --enable-sensors
```

### 5. 切换赛道感知模式
- `edge_contours`（默认，双侧赛道边墙/边界检测与自适应走廊中线追踪）
- `lane_line`（明亮引导线/白线模式，支持 HSV 与自适应高光分割）
- `color_mask`（暗色赛道/深色沥青模式）

```bash
python3 main.py --mode lane_line --throttle 0.35
```

---

## 🛠 调参指南（针对 Chalmers Folkrace 赛道）

在 `config.py` 中可针对具体场地快速调整：

1. **转向响应与过弯震荡**：
   - 如果车体入弯迟钝，适当增大 `ControlConfig.kp`（如从 `0.65` 调至 `0.80`）。
   - 如果在直道左右蛇形震荡，适当增大 `ControlConfig.kd`（如调至 `0.15~0.20`），并减小 `kp`。
2. **直道加速与弯道减速**：
   - `base_throttle`: 巡航速度（默认 `0.28`）。
   - `turn_slowdown_factor`: 弯道降速系数（默认 `0.5`），转向角度越大车速越低，防止过弯推头翻车。
3. **视觉感知区域 (ROI)**：
   - `roi_top_ratio`: 默认 `0.45`（忽略天花板与赛道远处背景，聚焦车头前方路面）。
   - `roi_bottom_ratio`: 默认 `0.95`（忽略车头保险杠阴影）。
4. **左右传感器避障接入**：
   - 超声波左侧默认引脚：TRIG `GPIO 23`, ECHO `GPIO 24`
   - 超声波右侧默认引脚：TRIG `GPIO 27`, ECHO `GPIO 22`
   - 红外传感器默认引脚：左侧 `GPIO 17`, 右侧 `GPIO 18`
