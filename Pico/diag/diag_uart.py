"""三路串口原始字节诊断。拷到板子上，在 REPL 里 `import diag_uart` 或直接跑。

用途：确认每个传感器到底往哪根引脚、以什么内容在输出。比对着协议文档猜快得多。
"""

import time
from machine import Pin, UART

PINS = (17, 29, 21)


def switch(u, rx):
    """把指定引脚设为 UART 的 RX。先把所有候选引脚恢复成普通输入。"""
    for p in PINS:
        Pin(p, Pin.IN)
    u.init(baudrate=9600, rx=Pin(rx))
    time.sleep_ms(300)
    u.read()


def dump(name, u, rx, n=48):
    switch(u, rx)
    time.sleep_ms(600)
    d = u.read(n)
    if not d:
        print(name, "RX=GPIO" + str(rx), ": no data")
        return None
    print(name, "RX=GPIO" + str(rx), ":", len(d), "bytes")
    print("   " + " ".join("%02X" % b for b in d))
    return d


def main():
    uart0 = UART(0, baudrate=9600, rx=Pin(17))
    uart1 = UART(1, baudrate=9600, rx=Pin(21))
    dump("CO2", uart0, 17)
    dump("CH2O", uart0, 29)
    dump("PM", uart1, 21)


main()
