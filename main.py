"""温湿度监控终端 —— ESP32 + SSD1351(128x128 彩屏) + SHT30 + LIS3DH。

和原版 main.py 的区别（只改"用什么数据"和"怎么显示"，硬件接线没动）：
  * 删掉 WiFi：原来会连天气服务器并用服务器数据**覆盖本地读数**，现在只信本地传感器。
  * 删掉 WS2812 RGB 灯、BQ24072 充电管理（set_charge / set_charge_current）。
  * 删掉三种手势开关（倾 X 开关 WiFi / 倾 Y 开关灯 / 倾 Z 开关屏，以及 tri_* 迟滞标志）——
    LIS3DH 现在用来**解算姿态角**，驱动屏幕上的小球水平仪。
  * 显示全部委托给 ui.py（不碰硬件的界面层，电脑上可先预览）。
原文件留在 main.v1.bak（这目录不是 git 仓库，所以用 .bak 留档）。

保留：开机画面、SHT30 的原有偏置修正、led = Pin(45) 的板级初始化。

⚠️ SHT30 的两个偏置（温度 -3.5、湿度 +11）是**用户标定的系统误差校正**：
   板子自身的热源/气流让读数存在固定偏差，这两个常数是实测比对后定下来的。
   不是随手写的数，改动前请重新标定。

⚠️ 节奏改成非阻塞：原来是"50 次取样 × 20ms 间隔"再平均，一轮**阻塞 1 秒**，
   那样水平仪一秒才动一次、完全没法用。现在：
     - LIS3DH 每 50ms 读一次（姿态要跟手）
     - SHT30 每 1 秒读一次，滑进 8 个样本的窗口做平均（温湿度不需要实时）
     - 屏幕独立节流在 DRAW_MS（全屏 32KB 走 SPI，约 6Hz 是稳妥上限）
"""

import math
import time
from machine import Pin, SoftI2C

import SSD1351 as OLED
import ui

led = Pin(45, Pin.OUT, value=1)

# ---------------------------------------------------------------- 参数
LOOP_MS = 50            # 姿态取样节拍
DRAW_MS = 160           # 重绘节流：全屏 32KB，6Hz 左右
SHT30_MS = 1000         # 温湿度取样周期
SHT30_AVG = 8           # 平均窗口（8 个样本 ≈ 8 秒，比原来的 1 秒更稳）
ATT_ALPHA = 0.25        # 姿态低通系数：越小越稳、跟手越慢

# SHT30 系统误差校正（用户标定值，不要当垃圾删掉）：
# 板子本身的热源/气流让读数有固定偏差，这两个常数是实测比对后定下来的。
T_OFFSET = -3.5
R_OFFSET = 11.0

LIS_GAIN = 0.001        # ±2g + HR(12 位) -> 1mg/digit

# 运动检测：加速度模长偏离 1g 超过这个量就算"设备在动"，此时冻结角度更新。
# 0.08g 大约相当于 4.6 度的虚假倾角 —— 低于它就当噪声容忍，高于它明显是碰到了。
MOTION_G = 0.08
# 单次允许的最大角度变化（度）。为什么需要：加速度计**无法区分**"倾斜"和
# "水平 + 横向加速" —— 0.2g 的横向加速度只让模长变 2%，模长检测抓不到，
# 但算出来是 11 度的假倾角。没有陀螺仪就没有真正的判据，只能用速率限制兜底：
# 桌面设备不会真的以 80 度/秒翻转，所以出现的突跳一定是运动干扰。
ATT_MAX_STEP = 4.0
# 零偏标定：开机时采这么多样本取平均当作水平参考。要求这段时间设备静止且水平。
CAL_N = 24
CAL_MS = 25             # 24 x 25ms = 0.6 秒

# ---------------------------------------------------------------- I2C
iic = SoftI2C(scl=Pin(39), sda=Pin(40), freq=400000)


# ---------------------------------------------------------------- LIS3DH
def lis_init():
    """CTRL_REG1 400Hz 三轴使能；CTRL_REG4 BDU + **HR(12 位)** + ±2g。

    原代码只写 0x20=0x8F（普通模式 10 位）且只读高字节，等于 8 位精度。
    算姿态角要打开 HR 读满 12 位 —— ±2g 下就是 1mg/digit。
    """
    iic.writeto(0x18, b"\x20\x8F")
    iic.writeto(0x18, b"\x23\x88")


# 加速度计零偏（calibrate() 填）。便宜的加速度计有几个 mG 固定偏差，
# 折算到角度上是 0.5~1 度的固定误差 —— 不减掉的话"水平"永远差一点。
LIS_ZERO = (0.0, 0.0, 1.0)


def lis_read_raw():
    """读原始 g 值（未减零偏）。"""
    """读 12 位三轴，返回 (ax, ay, az)，单位 g。

    HR 模式下数据是**16 位左对齐的 12 位补码**，所以拼成 int16 后算术右移 4 位。
    0xA8 = 0x28(OUT_X_L) | 0x80，最高位置 1 表示"连续读、地址自增" ——
    一次事务取 6 字节，比原来逐寄存器读省 5 次往返。
    """
    iic.writeto(0x18, b"\xA8")
    d = iic.readfrom(0x18, 6)
    ax = d[0] | d[1] << 8
    ay = d[2] | d[3] << 8
    az = d[4] | d[5] << 8
    if ax & 0x8000:
        ax -= 0x10000
    if ay & 0x8000:
        ay -= 0x10000
    if az & 0x8000:
        az -= 0x10000
    return (ax >> 4) * LIS_GAIN, (ay >> 4) * LIS_GAIN, (az >> 4) * LIS_GAIN


def lis_read():
    """读 g 值并减掉标定出的零偏。"""
    (x, y, z) = lis_read_raw();
    (zx, zy, zz) = LIS_ZERO;
    return (x - zx, y - zy, z - zz)


def calibrate():
    """采集静置样本作为零偏。要求调用时设备**静止且水平**。

    采平均而不是取一个样本：单样本的噪声有几个 LSB，平均后小一个数量级。
    """
    global LIS_ZERO;
    ax = ay = 0.0;
    az = 1.0;
    ok = 0;
    for _ in range(CAL_N):
        try:
            (x, y, z) = lis_read_raw();
            ax += x;
            ay += y;
            az += z;
            ok += 1;
        except OSError:
            pass;
        time.sleep_ms(CAL_MS);
    if (ok < 4):
        return False;
    # ⚠️ 只存**相对理想值 (0, 0, 1g) 的偏差**，不能把整个向量当零偏。
    #    否则水平时校正结果是 (0,0,0)，角度虽然还是 0，但运动检测的模长变成 0，
    #    |0-1| = 1 > MOTION_G，会被永远判定为"在动"、角度永久冻结。
    LIS_ZERO = (ax / ok, ay / ok, az / ok - 1.0);
    return True;


def attitude(ax, ay, az):
    """重力向量 -> (pitch, roll)，单位度。

    pitch：绕 Y 轴（机头上下）
    roll ：绕 X 轴（左右倾斜）
    符号与 ui.level() 的小球一致：**设备往某一侧倾斜时，球朝那一侧滚**（物理水平仪）。
    真机上如果觉得方向反了，把下面两行的 atan2 参数对调即可。
    """
    pitch = math.atan2(-ax, math.sqrt(ay * ay + az * az)) * 57.29578
    roll = math.atan2(ay, az) * 57.29578
    return pitch, roll


# ---------------------------------------------------------------- SHT30
def sht30_read():
    """返回 (温度 C, 湿度 %)，已加原代码的偏置。"""
    iic.writeto(0x44, b"\x2C\x06")
    time.sleep_ms(20)                    # 高重复性测量的转换时间约 15ms
    d = iic.readfrom(0x44, 6)
    t = -45 + 175 * (d[0] << 8 | d[1]) / 65535.0
    r = 100 * (d[3] << 8 | d[4]) / 65535.0
    return t + T_OFFSET, r + R_OFFSET


class Avg:
    """定长滑动平均。用定长列表原地滚动，不反复分配，省内存。"""

    def __init__(self, n, first):
        self.buf = [first] * n
        self.n = n
        self.i = 0
        self.sum = first * n

    def push(self, v):
        self.sum += v - self.buf[self.i]
        self.buf[self.i] = v
        self.i = (self.i + 1) % self.n
        return self.sum / self.n

    def value(self):
        return self.sum / self.n


# ---------------------------------------------------------------- 开机
def boot():
    """开机：初始化屏幕、画开机图。

    这一版走**直写**路径（没有帧缓冲）—— 帧缓冲那套在真机上卡在绘制阶段，
    已整体废弃（见 SSD1351.v2.broken.bak）。
    """
    led.value(0)
    OLED.init()
    OLED.clear(0x000000)
    print("[boot] init ok")
    # 开机图要读 12800 字节的 font/boot.bin，是开机路径里最大的一次性分配；
    # 内存紧的时候失败不该让整机起不来，所以包一层。
    try:
        OLED.bmpf(64, 56, 80, 80, "font/boot.bin")
        OLED.prtc(64, 108, 0, 0x808080, 0x000000, "v2.0")
        print("[boot] logo ok")
    except MemoryError:
        OLED.prt(20, 60, 0, 0x808080, 0x000000, "no mem")
        print("[boot] logo skipped")
    time.sleep(2)
    OLED.clear(ui.BG)
    led.value(1)
    print("[boot] done")


def main():
    boot()
    lis_init()
    # 标定加速度计零偏：要求此时设备静止且水平（开机画面那 2 秒正好用上）
    if (calibrate()):
        print("[cal] 零偏", LIS_ZERO)
    else:
        print("[cal] 采样失败，用默认零偏")
    try:
        (t0, r0) = sht30_read()
    except OSError:
        (t0, r0) = (0.0, 0.0)
    avg_t = Avg(SHT30_AVG, t0)
    avg_r = Avg(SHT30_AVG, r0)

    pitch = 0.0
    roll = 0.0
    t_att = time.ticks_ms()
    t_sht = t_att
    t_draw = t_att - DRAW_MS          # 上电立刻画一帧

    while True:
        now = time.ticks_ms()

        # 姿态：每 50ms。读失败就跳过 —— I2C 偶发错误不该让程序停或复位角度
        if time.ticks_diff(now, t_att) >= LOOP_MS:
            t_att = now
            try:
                (ax, ay, az) = lis_read()
                # 运动检测：模长偏离 1g 说明加速度里混了运动分量，
                # 此时算出来的"倾角"是假的（碰桌子就会跳），直接跳过这一帧、
                # 保持上一次的角度。
                mag = math.sqrt(ax * ax + ay * ay + az * az)
                if abs(mag - 1.0) <= MOTION_G:
                    (p, rl) = attitude(ax, ay, az)
                    # 单次变化限幅（见 ATT_MAX_STEP 的说明）
                    dp = p - pitch
                    if (dp > ATT_MAX_STEP):
                        dp = ATT_MAX_STEP
                    elif (dp < -ATT_MAX_STEP):
                        dp = -ATT_MAX_STEP
                    dr = rl - roll
                    if (dr > ATT_MAX_STEP):
                        dr = ATT_MAX_STEP
                    elif (dr < -ATT_MAX_STEP):
                        dr = -ATT_MAX_STEP
                    pitch += dp * ATT_ALPHA
                    roll += dr * ATT_ALPHA
            except OSError:
                pass

        # 温湿度：每 1 秒滑进窗口
        if time.ticks_diff(now, t_sht) >= SHT30_MS:
            t_sht = now
            try:
                (t, r) = sht30_read()
                avg_t.push(t)
                avg_r.push(r)
            except OSError:
                pass

        # 重绘：节流
        if time.ticks_diff(now, t_draw) >= DRAW_MS:
            t_draw = now
            ui.draw(OLED, avg_t.value(), avg_r.value(), pitch, roll, now)

        time.sleep_ms(5)


main()
