import time
from machine import UART

def find_subsequence(data, subsequence):
    """
    在 bytearray 中查找子序列的位置。
    :param data: 要搜索的 bytearray。
    :param subsequence: 要查找的子序列（bytes）。
    :return: 子序列的起始索引，如果未找到则返回 -1。
    """
    length = len(subsequence)
    for i in range(len(data) - length + 1):
        if data[i:i+length] == subsequence:
            return i
    return -1

def find_frame(data, length):
    """
    在数据流中查找帧头，提取完整帧。
    """
    frame_header = b'\x42\x4D'  # 帧头
    start = find_subsequence(data, frame_header)
    if start != -1 and len(data[start:]) >= length:
        return data[start:start + length]
    return None

def parse_frame(uart, frame_length, checksum_length=1, data_indices=None,
                timeout_ms=1000):
    """
    通用的帧解析函数。
    
    :param uart: UART 串口实例。
    :param frame_length: 数据帧长度。
    :param checksum_length: 校验和字节数，1 或 2。
    :param data_indices: 要提取的字节索引，列表形式 [(high_byte, low_byte), ...]。
    :param timeout_ms: 超时毫秒数。**必须有超时** —— 原来是 while True 死等帧，
        传感器没接上（或者切换引脚切错了）会把整个主循环卡死，屏幕上其它
        读数也一起停更，而且看不出原因。
    :return: 数据元组；超时返回 None。
    """
    buffer = bytearray()  # 数据缓冲区
    t0 = time.ticks_ms()
    while time.ticks_diff(time.ticks_ms(), t0) < timeout_ms:
        # 读取串口数据
        buffer.extend(uart.read(frame_length * 2) or b'')  # 读取数据，缓冲更大范围防止截断
        # 查找帧头并提取完整帧
        frame = find_frame(buffer, frame_length)
        if frame:
            # 移除已处理的部分
            buffer = buffer[find_subsequence(buffer, frame) + frame_length:]
            
            # 校验帧
            payload = frame[:-checksum_length]  # 数据内容
            checksum = frame[-checksum_length:]  # 校验和
            if checksum_length == 1:
                calculated_checksum = sum(payload) & 0xFF
                received_checksum = checksum[0]
            elif checksum_length == 2:
                calculated_checksum = sum(payload) & 0xFFFF
                received_checksum = (checksum[0] << 8) | checksum[1]
            else:
                raise ValueError("Unsupported checksum length")

            if calculated_checksum != received_checksum:
                buffer.clear()
                continue

            # 提取数据
            result = []
            for high, low in data_indices:
                value = (frame[high] << 8) | frame[low]
                result.append(value)
            return tuple(result)
        else:
            # 没找到完整帧，下一轮继续（while 条件会检查超时）
            continue

    return None               # 超时

def get_co2(uart, timeout_ms=1000):
    """
    从串口读取 CO2 数据。
    """
    r = parse_frame(
        uart,
        frame_length=16,
        checksum_length=1,
        data_indices=[(6, 7)],  # 只提取 CO2 数据
        timeout_ms=timeout_ms
    )
    return None if r is None else r[0]

def get_pmx(uart, timeout_ms=1000):
    """
    从串口读取 PMx 数据。
    """
    return parse_frame(
        uart,
        frame_length=32,
        checksum_length=2,
        data_indices=[
            (4, 5),  # PM1
            (6, 7),  # PM2.5
            (8, 9)   # PM10
        ],
        timeout_ms=timeout_ms
    )


def get_ch2o(uart, timeout_ms=800):
    """读一帧甲醛数据，返回**ppb**（协议的原始单位）；超时返回 None。

    帧格式（见 ch2o-info/）：9 字节，
        0  起始位      0xFF
        1  气体名称    CH2O = 0x17
        2  单位        ppb  = 0x04
        3  小数位数    无
        4  浓度 高字节
        5  浓度 低字节
        6  满量程 高字节
        7  满量程 低字节
        8  校验值      (取反(b1+..+b7)) + 1
    ppb -> mg/m³ 要乘 30.03/24.45/1000 ≈ 0.001228（分子量 30.03，24.45 是常温摩尔体积），
    换算放在 main.py 里做，这一层只负责按协议取数。

    ⚠️ 加了超时：原来的 get_co2/get_pmx 是 while True 等帧，传感器没接上会
    **卡死整个主循环**。切换引脚的时候这种风险更高（切错引脚就永远收不到帧）。
    """
    buf = bytearray()
    t0 = time.ticks_ms()
    while time.ticks_diff(time.ticks_ms(), t0) < timeout_ms:
        chunk = uart.read(9 * 2)
        if chunk:
            buf.extend(chunk)
        # 在缓冲里找 0xFF 0x17 开头的 9 字节帧
        i = 0
        while i + 9 <= len(buf):
            if buf[i] == 0xFF and buf[i + 1] == 0x17:
                frame = buf[i:i + 9]
                # 校验：字节 1..7 求和取反加一
                total = 0
                for k in range(1, 8):
                    total += frame[k]
                if ((~total) + 1) & 0xFF == frame[8]:
                    return (frame[4] << 8) | frame[5]
                # 校验不过就滑一个字节继续找
            i += 1
        time.sleep_ms(10)
    return None
