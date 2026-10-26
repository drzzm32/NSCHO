"""基线版本 —— 加甲醛传感器**之前**的结构，用于对照测试。

和正式版 main.py 的唯一区别：
  * UART0 固定接 GPIO17 读 CO2，不做引脚切换（没有 uart0_select）
  * 不读甲醛（d["hcho"] 固定为 None，ui.draw 需要这个键）
  * 保留 EnvSensor 的超时修正（那是独立的好改动）

接线：PM -> UART1 RX = GPIO21，CO2 -> UART0 RX = GPIO17，全部 9600、只收不发。

用途：如果这一版显示正常、正式版花屏，那问题就在 UART0 引脚切换或甲醛读取上。
"""

import time
import machine
from machine import Pin, UART

import SSD1325 as OLED
import EnvSensor as Env
import ui

LED = Pin(25, Pin.OUT)

PM_ROTATE_MS = 4000      # 主区 PM 值轮换周期
READ_MS = 500            # 读数周期


def main():
    LED.value(0)
    # ⚠️ 超频必须在 OLED.init() **之前**：PIO 状态机的时钟是从主频分频出来的，
    #    init 时按当时的主频算好分频值。先 init 再改主频，PIO 的实际输出频率会
    #    跟着变成 1.92 倍（20MHz -> 38MHz），显示总线超速 —— 表现就是开机画面
    #    正常（那时还没改主频）、进主循环后坐标全乱。
    machine.freq(240_000_000)
    OLED.init()
    ui.draw_boot(OLED, "BOOTING")           # 美化的开机画面
    time.sleep(3)

    LED.value(1)
    time.sleep_ms(500)

    uart_co2 = UART(0, baudrate=9600, tx=Pin(16), rx=Pin(17))
    uart_pmx = UART(1, baudrate=9600, tx=Pin(20), rx=Pin(21))

    OLED.clear()

    d = {"pm1": 0, "pm25": 0, "pm10": 0, "co2": 0, "hcho": None}
    which = 0
    last_rotate = time.ticks_ms()

    while True:
        try:
            pm = Env.get_pmx(uart_pmx)
            if pm is not None and pm[1] is not None:
                d["pm1"], d["pm25"], d["pm10"] = pm[0], pm[1], pm[2]
        except (TypeError, ValueError, IndexError):
            pass

        try:
            co2 = Env.get_co2(uart_co2)
            if co2 is not None:
                d["co2"] = co2
        except (TypeError, ValueError, IndexError):
            pass

        now = time.ticks_ms()
        if time.ticks_diff(now, last_rotate) >= PM_ROTATE_MS:
            last_rotate = now
            which = (which + 1) % len(ui.PM_ITEMS)

        ui.draw(OLED, d, which)
        time.sleep_ms(READ_MS)


main()
