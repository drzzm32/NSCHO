# 源码路径与版本记录

记录于 2026-10-25。这些目录都是**从别处拷贝**过来的（所有者 SID 不是本机用户，
所以 `git` 会报 "dubious ownership"），重编固件前先看这份记录，别乱动。

## 目录

| 路径 | 类型 | 版本 | 说明 |
|---|---|---|---|
| `E:\Works\esp-mpy` | **不是 git**（解压的 zip） | MicroPython **1.19.0** | 带 NSCLK 板级目录的 fork |
| `E:\Works\micropython-1.19` | **不是 git**（解压的 zip） | MicroPython **1.19.0** | 上游同版本，构建时的 `MICROPY_DIR` 指向它 |
| `E:\Works\micropython-lib` | git 仓库 | 未确认（ownership 报错） | 冻结模块用到 |
| `E:\Works\esp-idf` | git 仓库 | **ESP-IDF 4.4.0** | 和 MicroPython 1.19 是官方配套版本 |

版本是从源码里读的，不是猜的：
- `esp-mpy/py/mpconfig.h` → `MICROPY_VERSION 1.19.0`
- `esp-idf/components/esp_common/include/esp_idf_version.h` → `4.4.0`

**1.19.0 + IDF 4.4.0 是配套的**，这点很关键 —— 版本对上了，重编不需要先解决
版本兼容问题。

## git 的 "dubious ownership"

`micropython-lib` 和 `esp-idf` 是 git 仓库，但目录所有者是另一个机器的用户 SID
（`S-1-5-21-1725624843-...`），`git` 会拒绝操作。要看它们的历史得先加例外：

```powershell
git config --global --add safe.directory E:/Works/esp-idf
git config --global --add safe.directory E:/Works/micropython-lib
```

（`E:\Works\NSAGP` 也是同样情况 —— 那批目录应该是从同一台机器拷来的。）

## 构建产物（2022-09）

`E:\Works\esp-mpy\ports\esp32\build\`

| 文件 | 大小 | 日期 |
|---|---|---|
| `micropython.bin` | 1,172,976 B | 2022-09-10 11:02 |
| `bootloader\bootloader.bin` | 18,016 B | 2022-09-08 09:04 |
| `partition_table\partition-table.bin` | 3,072 B | 2022-09-08 09:03 |

设备上跑的就是这个。`build/genhdr` 里记录的原始 checkout 路径是
`E:\Works\micropython-1.19`，和上表一致。

## 重编需要的环境（当前**不具备**）

| 项 | 状态 |
|---|---|
| ESP-IDF 4.4.0 源码 | 有 ✓ |
| MicroPython 1.19.0 源码 | 有 ✓ |
| 工具链（`~/.espressif`） | **没有** ✗ —— `install.ps1` 要下约 1.5 GB |
| Python | **3.14.3** ✗ —— IDF 4.4 要求 3.7~3.10，差太远 |

所以重编的第一步不是改代码，而是：**找一个 Python 3.9/3.10**，跑
`esp-idf/install.ps1` 装工具链，再 `export.ps1` + `make BOARD=NSCLK` 验证
能不能原样复现出固件。这一步跑通之前，任何 C 代码改动都没有意义。

估计半天到一天，卡点主要是 Python 版本和工具链下载。
