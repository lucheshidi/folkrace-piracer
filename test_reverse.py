#!/usr/bin/env python3
"""
PiRacer Pro 的倒车油门诊断脚本。

回答一个问题：这颗 ESC 到底会不会让电机倒转？

test_hardware.py 已经跑过教科书式的序列（前进 → 中位停留 → 倒车），轮子
没动，所以"ESC 需要先在中位停一下"这条已经排除。软件侧剩下的可能只有
一个：幅度。-0.25 只比 1.5 ms 中位脉冲低 0.125 ms，而 +0.40 高出 0.2 ms。
如果这颗 ESC 的倒车区间起点比 -0.25 更远，那所有代码路径都会失败，而改
一个配置值就是全部的解。

两种模式都试，因为 ESC 之间不一样：
    A) 持续保持同一负值，幅度递增
    B) 双击式（刹车 → 回中 → 再刹车）—— 有些 ESC 要第二次拉刹车才进
       倒车，而不是一直按着

用法：
    python3 test_reverse.py
    # 或者 chmod +x 之后：
    ./test_reverse.py
"""

import time
import logging

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s")

# 每一档都停留足够长，既能等 ESC 反应，也够人看清楚。
REVERSE_STEPS = [-0.2, -0.4, -0.6, -0.8, -1.0]


def load_driver():
    """返回 (driver, driver_type)，回退顺序和 test_hardware.py 一致。"""
    try:
        from piracer.vehicles import PiRacerPro
        logging.info("✅ 已加载 piracer-py (PiRacerPro)")
        return PiRacerPro(), "piracer-py"
    except Exception as e:
        logging.warning(f"piracer-py 不可用：{e}")

    try:
        from adafruit_servokit import ServoKit
        driver = ServoKit(channels=16)
        driver.servo[0].set_pulse_width_range(1000, 2000)
        driver.continuous_servo[1].set_pulse_width_range(1000, 2000)
        logging.info("✅ 已加载 adafruit-servokit (PCA9685)")
        return driver, "servokit"
    except Exception as e:
        logging.warning(f"ServoKit 不可用：{e}")

    return None, None


def main():
    logging.info("==================================================")
    logging.info(" 倒车油门诊断                                      ")
    logging.info("==================================================")

    driver, driver_type = load_driver()
    if driver is None:
        logging.error("❌ 没有可用的硬件驱动！请检查 I2C 和 piracer-py 是否装好。")
        return

    def throttle(value):
        if driver_type == "piracer-py":
            driver.set_throttle_percent(value)
        else:
            driver.continuous_servo[1].throttle = value

    def hold(value, seconds):
        logging.info(f"  -> 油门 {value:+.2f}")
        throttle(value)
        time.sleep(seconds)

    logging.info("注意：车轮必须悬空！3 秒后开始运行。")
    time.sleep(3.0)

    try:
        # ESC 在解锁期间读取中位，并把"正 → 负"的跳变读成刹车，所以两种
        # 模式都先用一小段前进加一次中位停顿开场，再往负走。
        logging.info("中位解锁 2 秒（注意听 ESC 的提示音）……")
        hold(0.0, 2.0)

        logging.info("--- A) 持续保持同一负值，幅度逐级加大 ---")
        logging.info("    盯住轮子：从哪一档开始倒转？一档都没有就记「全无」。")
        hold(0.3, 1.0)
        hold(0.0, 2.0)
        for value in REVERSE_STEPS:
            hold(value, 2.0)
        hold(0.0, 1.0)

        logging.info("--- B) 双击式（刹车 → 回中 → 再刹车）---")
        logging.info("    有些 ESC 要第二次拉刹车才进倒车，一直按着反而只当刹车。")
        hold(0.3, 1.0)
        hold(0.0, 2.0)
        for _ in range(2):
            hold(-1.0, 0.4)
            hold(0.0, 0.4)
            time.sleep(0.6)
        hold(0.0, 1.0)

    finally:
        # 退出时绝不能让 ESC 保持某个值，Ctrl-C 也算。
        throttle(0.0)
        logging.info("油门已回中位。")

    logging.info("==================================================")
    logging.info(" 如果从头到尾轮子都没有倒转，那就是 ESC 本身没有在做倒车。")
    logging.info(" 按成本从低到高检查：")
    logging.info("   1. 运行模式 —— Forward/Brake 根本没有倒车档，必须设成")
    logging.info("      Forward/Brake/Reverse")
    logging.info("   2. 油门行程标定 —— 中位点漂移会把整个倒车区间吃掉，")
    logging.info("      而前进幅度大，照样能过")
    logging.info("   3. 电池 —— 电压偏低时部分 ESC 会锁掉倒车")
    logging.info("==================================================")


if __name__ == "__main__":
    main()
