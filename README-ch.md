[English](README.md) | **简体中文**

# WaveShare PiRacer Pro - Chalmers Folkrace 自动驾驶控制程序

本项目是一个专为 **WaveShare PiRacer Pro AI 套件** 设计的自主循线与道路感知控制系统，用于参加 **Chalmers 机器人 Folkrace 竞赛**。系统基于 **OpenCV2**、**NumPy**、**Picamera2** 和 **PiRacerPro** 硬件驱动，并预留了**侧面红外测距/超声波避障传感器**的扩展接口。

---

## 📁 项目架构

- **`config.py`**：核心参数配置文件（包括相机分辨率、HSV 赛道阈值、ROI 裁剪区域、PID 转向参数、动态速度限制以及传感器 GPIO 引脚映射）。
- **`camera.py`**：相机抽象封装（优先使用树莓派官方 `Picamera2` 采集，支持本地 OpenCV 相机以及无硬件时的合成帧调试回退）。
- **`vision.py`**：计算机视觉赛道感知模块（多层水平切片加权质心扫描、自适应/HSV 赛道提取、前视距离计算）。
- **`controller.py`**：PID 转向控制器和 PiRacerPro 底盘控制封装（支持弯道自适应减速、失焦减速循线以及紧急断电保护）。
- **`sensors.py`**：左右两侧超声波（HC-SR04）和红外避障传感器管理模块（贴墙推力修正和紧急制动）。
- **`main.py`**：系统主控制循环入口（支持帧率控制、键盘/系统信号安全中断退出以及调试窗口可视化）。

---

## 🚀 树莓派环境安装与依赖

在 PiRacer Pro 上运行（Raspberry Pi OS Bookworm / Bullseye）：

```bash
# 1. 更新系统并安装系统级依赖
sudo apt update
sudo apt install -y python3-pip python3-opencv python3-numpy python3-rpi.gpio python3-smbus

# 2. 安装 Picamera2（Bookworm 镜像通常已预装）
sudo apt install -y python3-picamera2

# 3. 安装底盘和舵机驱动库（任选其一或两者都安装，程序会自动检测）
pip3 install piracer-py
# 或使用 Adafruit ServoKit 驱动 PCA9685
pip3 install adafruit-circuitpython-servokit
```

---

## 🔧 硬件自检与诊断（重要）

在开始自主循线之前，请先运行硬件自检脚本（**注意：测试前请将车轮悬空，以防止车辆失控**）：

```bash
python3 test_hardware.py
```

该脚本将依次测试：
1. **I2C 总线和 PCA9685 芯片通信（0x40）**
2. **ESC 电子调速器中位自检解锁序列（1.5 秒）**
3. **转向舵机扫掠（中位 -> 左转 -> 中位 -> 右转 -> 中位）**
4. **后轮驱动电机旋转（前进 0.28 -> 刹车 -> 后退 -0.25 -> 停止）**
5. **Picamera2 相机图像采集**

---

## 🎮 运行模式

### 1. 局域网 Web 实时流模式（推荐：直接在电脑/手机浏览器中查看）
在树莓派上启动推流：
```bash
python3 main.py --stream
```
然后在电脑或手机浏览器中打开（需与树莓派处于同一 Wi-Fi）：
```text
http://<RaspberryPiIP>:8080
```
> 页面将显示车辆摄像头实时前视图、赛道中心线识别轨迹以及实时遥测数据（FPS、实时转向角 Steer、实时油门 Thr）。
> 可自定义端口：`python3 main.py --stream --port 8080 --throttle 0.32`

### 2. 竞赛实车运行（最高速度无界面模式，最高帧率）
```bash
python3 main.py --throttle 0.32
```

### 3. 本地桌面 GUI 调试模式（需要 HDMI 屏幕或 X11 转发）
```bash
python3 main.py --display
```

### 4. 启用侧面超声波/红外传感器避障
```bash
python3 main.py --stream --enable-sensors
```

### 5. 切换赛道感知模式
- `edge_contours`（默认，双侧赛道墙/边界检测和自适应走廊中心线跟踪）
- `lane_line`（亮色引导线/白线模式，支持 HSV 和自适应高亮分割）
- `color_mask`（深色赛道/深色沥青模式）

```bash
python3 main.py --mode lane_line --throttle 0.35
```

---

## 🛠 调参指南（适用于 Chalmers Folkrace 赛道）

在 `config.py` 中针对特定场地进行快速调整：

1. **转向响应和弯道振荡**：
   - 如果车辆入弯迟缓，适当增大 `ControlConfig.kp`（例如从 `0.65` 到 `0.80`）。
   - 如果直道上出现左右蛇形振荡，适当增大 `ControlConfig.kd`（例如到 `0.15~0.20`），并减小 `kp`。
2. **直线加速和弯道减速**：
   - `base_throttle`：巡航速度（默认 `0.28`）。
   - `turn_slowdown_factor`：弯道减速因子（默认 `0.5`），转向角越大，速度越低，以防止弯道推头/侧翻。
3. **视觉感知区域（ROI）**：
   - `roi_top_ratio`：默认 `0.45`（忽略天花板和远处赛道背景，聚焦车头前方路面）。
   - `roi_bottom_ratio`：默认 `0.95`（忽略车头保险杠阴影）。
4. **左/右传感器避障连接**：
   - 超声波左侧默认引脚：TRIG `GPIO 23`，ECHO `GPIO 24`
   - 超声波右侧默认引脚：TRIG `GPIO 27`，ECHO `GPIO 22`
   - 红外传感器默认引脚：左 `GPIO 17`，右 `GPIO 18`

# 贡献者
- Pengpung
- Duckystew
