# 固件（MicroPython for NSCLK / ESP32-S2）

Micropython 源码位置：`E:\Works\esp-mpy`，板级目录 `ports/esp32/boards/NSCLK`。
2022-09 的构建产物在 `ports/esp32/build/`。

**各目录的版本与来源见 [PATHS.md](PATHS.md)** —— MicroPython 1.19.0 + ESP-IDF 4.4.0（配套版本）。

**当前设备上跑的是 2022-09-10 的固件，功能完整** —— 除非要加原生绘制函数（见下），
否则不需要重新烧录。

## 芯片与总线（从源码确认）

| 项 | 值 |
|---|---|
| MCU | **ESP32-S2FH4**（4 MB flash，**无 PSRAM**） |
| 堆 | 约 103 KB（MicroPython 拿剩余内部 DRAM，属正常） |
| 屏幕总线 | **不是 SPI、不是 PIO** —— 8 位并口，在 C 里逐位敲 |
| 数据线 | GPIO 8~15 |
| 写选通 | GPIO 6 |

`cmodule/ll.c` 里的 `__bus_wr` 直接写 GPIO 寄存器 + nop 延时，实测约
**0.3 µs/字节**（32 KB 一帧约 10 ms）。`bus_write` 支持整块 bytes（C 里循环）。

## 烧录

芯片是 esp32s2，**走 USB 原生 CDC**（不是 UART0）。Windows 上就是平时
看 `[boot]` 输出的那个 COM 口。

```powershell
python -m esptool --chip esp32s2 --port COMx erase_flash
python -m esptool --chip esp32s2 --port COMx write_flash -z `
    0x1000  bootloader\bootloader.bin `
    0x8000  partition_table\partition-table.bin `
    0x10000 micropython.bin
```

偏移是 ESP32-S2 标准布局。官方部署文档 `ports/esp32/boards/deploy_s2.md`
里写的"从 0x1000 烧一个 .bin"指的是**合并后的整片镜像**，不是 `micropython.bin`
（后者只是应用部分）。

连不上时手动进下载模式：按住 **BOOT**（GPIO0）→ 点一下 **RST** → 松开 BOOT。

## 想加的原生绘制函数（可选优化，需要重编固件）

现状：`ui.py` 用局部重绘把静止时的总线事务降到 0，闪烁已解决。若要更彻底，
可以走"32 KB 整屏帧缓冲 + 一次总线发送"，但 **Python 往缓冲里逐字节写太慢**
（65536 次索引赋值，几十毫秒），所以需要 C 层帮忙：

```c
// 建议加到 cmodule/ll.c
// nsclk_ll.fill_565(buf, stride, x0, y0, x1, y1, color)
// nsclk_ll.blit_565(buf, stride, x, y, w, h, src)
```

有了它们，一帧 = 若干次 C 调用 + 1 次 32 KB 发送，绘制成本降一个数量级。

## 重编固件的风险

- 构建产物是 **2022-09** 的，当时用的是独立 checkout 的 **MicroPython 1.19**
  （`build/genhdr` 里的路径是 `E:\Works\micropython-1.19`）
- 按 1.19 原样重编需要的 ESP-IDF 版本较老；升到新版 MicroPython 则是**大跨度升级**
  （IDF 5.x、API 变化），风险和工作量都大得多
- **建议**：先按 1.19 原样重编、只加那两个 C 函数，验证通过后再考虑升版本
