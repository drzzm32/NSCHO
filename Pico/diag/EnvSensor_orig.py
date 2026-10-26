"""EnvSensor 原版 —— 加超时和甲醛之前的实现，用于对照测试。

和现在的 EnvSensor.py 的区别：
  * parse_frame 是 while True 死等帧（**没有超时**）
  * 没有 get_ch2o
  * 没有 import time

用途：如果换回这一版 + main_nohcho.py 显示正常，就说明问题出在
超时改造或 get_ch2o 的引入上。
"""

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


def parse_frame(uart, frame_length, checksum_length=1, data_indices=None):
    """
    通用的帧解析函数。

    :param uart: UART 串口实例。
    :param frame_length: 数据帧长度。
    :param checksum_length: 校验和字节数，1 或 2。
    :param data_indices: 要提取的字节索引，列表形式 [(high_byte, low_byte), ...]。
    :return: 数据元组，按顺序包含解析结果。
    """
    buffer = bytearray()  # 数据缓冲区
    while True:
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
            # 如果没有找到完整帧，继续等待
            continue


def get_co2(uart):
    """
    从串口读取 CO2 数据。
    """
    return parse_frame(
        uart,
        frame_length=16,
        checksum_length=1,
        data_indices=[(6, 7)]  # 只提取 CO2 数据
    )[0]


def get_pmx(uart):
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
        ]
    )
