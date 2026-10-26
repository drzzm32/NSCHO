"""新的 main.py —— 空气质量站（RP2040 + SSD1325 128x64 4 位灰度）。

和原版的区别：**只改了显示层**，读数逻辑（两个 9600 串口、500ms 一轮）原样保留。
绘制全部委托给 ui.py —— 那是个不碰硬件的模块，所以同一套界面能在电脑上
用 preview/ 里的模拟器先看好再拷进设备。

显示设计（扁平化 + 灰度分层）：
    y=0..15   状态带 bg=6   轮换的标签(PM2.5/PM1.0/PM10) + 中文等级单字
    y=16..47  主区   bg=0   数码管大数字 20x32 独占这 32 行 + 右上角 32x32 角标
    y=48..63  CO2    bg=1   CO2 单独一行，不参与轮换
    PM 值每 PM_ROTATE_MS 换一个；PM2.5 的分档决定等级字和角标（见 ui.GRADES）。

接线（全部 9600、只收不发）：
    PM 传感器    -> UART1 RX = GPIO21（独占）
    CO2 传感器   -> UART0 RX = GPIO17  ┐ 两者**共用 UART0**，靠切换引脚复用
    甲醛传感器   -> UART0 RX = GPIO29  ┘
"""

import time
import machine
from machine import Pin, UART

import SSD1325 as OLED
import EnvSensor as Env
import ui
import logger

LED = Pin(25, Pin.OUT)

PM_ROTATE_MS = 4000      # 主区 PM 值轮换周期
READ_MS = 500            # 读数周期（和原版一致）


UART0_CO2 = 17            # CO2 接在 GPIO17（UART0 RX）
UART0_CH2O = 29           # 甲醛接在 GPIO29（UART0 RX）


def uart0_select(uart, rx_pin):
    """把 UART0 的 RX 切到指定引脚，并清掉切换瞬间的残帧。

    uart 显式传进来而不是用全局变量 —— 这个函数在模块级，而 UART 实例是在
    main() 里创建的，直接引用会 NameError（真机上踩过）。

    ⚠️ tx 引脚必须显式给：RP2040 上 UART1 省略 tx 会回落到默认引脚 GPIO8，
    而 GPIO8 正是显示总线的 sideset base —— 一旦被夺走，屏幕立刻坐标错乱。
    （真机上踩过，表现为"建完 UART 就花屏"。）

    ⚠️ 两个引脚都映射到 UART0 RX，所以**必须先把候选引脚都恢复成普通输入**
    （Pin(n, Pin.IN) 会把功能选择从 UART 改回 SIO），再 init 新引脚。
    不这么做的话旧引脚仍然占着 UART0 RX 的功能，两路信号会同时驱动 RX ——
    表现就是收到的全是乱码、校验永远不过。
    """
    Pin(UART0_CO2, Pin.IN)
    Pin(UART0_CH2O, Pin.IN)
    uart.init(baudrate=9600, tx=Pin(16), rx=Pin(rx_pin))
    time.sleep_ms(20)         # 等 UART 稳定
    uart.read()               # 扔掉切换期间收到的残帧


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

    # PM 独占 UART1；CO2 和甲醛共用 UART0，靠切换 RX 引脚复用
    uart_pmx = UART(1, baudrate=9600, tx=Pin(20), rx=Pin(21))
    uart0 = UART(0, baudrate=9600, tx=Pin(16), rx=Pin(17))

    OLED.clear()                            # 清掉开机画面
    # ⚠️ clear() 之后必须重置 ui 的增量重画缓存：否则 ui 以为屏幕还是上一帧的内容，
    #    增量重画会跳过本该重画的区域，屏幕就停在开机画面或残缺状态。
    ui.reset()

    # 上电次数 +1（写在 log/boot.id），并把日志计时起点设在真正开始运行的时候
    boot_id = logger.begin()
    print("[log] 上电次数", boot_id)

    d = {"pm1": 0, "pm25": 0, "pm10": 0, "co2": 0, "hcho": None}
    sel = 0                   # UART0 交替选择：0=CO2，1=甲醛
    which = 0
    last_rotate = time.ticks_ms()

    while True:
        # ⚠️ EnvSensor.find_frame() 找不到帧会返回 None，而 get_pmx/get_co2 是
        # 直接 return parse_frame(...)。**原版 main.py 直接解包**，帧异常时会抛异常
        # 把整个循环打断。这里包一层 try 并检查 None：读不到的这一次就保留上一次的
        # 有效值，屏上不会跳到 0、程序也不会崩。
        try:
            pm = Env.get_pmx(uart_pmx)
            if pm is not None and pm[1] is not None:
                d["pm1"], d["pm25"], d["pm10"] = pm[0], pm[1], pm[2]
        except (TypeError, ValueError, IndexError):
            pass

        # UART0 交替：这一轮读 CO2、下一轮读甲醛。两个传感器交替，
        # 各自约 1 秒更新一次，对温湿度那种慢变量足够。
        sel = 1 - sel
        if sel == 0:
            uart0_select(uart0, UART0_CO2)
            try:
                co2 = Env.get_co2(uart0)
                if co2 is not None:
                    d["co2"] = co2
            except (TypeError, ValueError, IndexError):
                pass
        else:
            uart0_select(uart0, UART0_CH2O)
            try:
                ppb = Env.get_ch2o(uart0)
                if ppb is not None:
                    # ppb -> mg/m³：分子量 30.03，常温摩尔体积 24.45 L/mol
                    d["hcho"] = ppb * 30.03 / 24.45 / 1000.0
            except (TypeError, ValueError, IndexError):
                pass

        now = time.ticks_ms()
        if time.ticks_diff(now, last_rotate) >= PM_ROTATE_MS:
            last_rotate = now
            which = (which + 1) % len(ui.PM_ITEMS)

        ui.draw(OLED, d, which)

        # 每分钟记一条日志（先攒在 RAM，每 30 分钟合并落盘一次 —— 见 logger.py 文件头
        # 的 flash 寿命计算：每分钟落盘会让元数据块约 5 个月写穿）
        logger.tick(now, d, boot_id)

        time.sleep_ms(READ_MS)


main()
