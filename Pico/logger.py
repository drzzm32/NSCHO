"""运行日志 + 上电次数统计。

日志格式（每分钟一条，写进 log/log.txt）：
    [0000 00:00] PM1: 10 ug/m3, PM2.5: 20 ug/m3, PM10: 30 ug/m3, CO2: 400 ppm, CH2O: 0.03 mg/m3
      ^^^^ ^^^^^ 上电次数（单独文件统计） + 上电后经过时间 hh:mm

为什么要攒批落盘（这块板最需要注意的地方）
----------------------------------------
MicroPython 的 RP2 端口用 **littlefs2**。它有磨损均衡，但**元数据对**（每个目录
固定的一对块）不参与均衡 —— 也就是说"反复 open/append/close 同一个文件"仍然会把
那一对块写穿，文件内容多大都无关。

一次 append+close = 一次元数据提交（追加不改目录项，只提交文件自己的元数据对），
摊到那对 2 个块上：

    1 次/分钟   -> 每年 26.3 万次/块 -> 按 10 万次寿命算约 **11 年**
    1 次/30 分钟 -> 每年 1.75 万次/块 -> 约 **23 年**
    1 次/小时   -> 每年 8760 次/块    -> 约 **114 年**

（数据块本身是循环分配的，按上面的写入量算每块每年只擦 50 次以内，不是瓶颈。）
真正的限制是**元数据对不参与磨损均衡**这一点。

所以这里把每分钟的记录先攒在 RAM 里（几十条也就几 KB），每 LOG_FLUSH_MIN 分钟
合并写一次。代价是掉电最多丢 LOG_FLUSH_MIN 分钟内还没落盘的记录 —— 对空气质量
这种慢变量完全可以接受。

上电次数（log/boot.id）是每次开机只写一次，写入量可以忽略；写入用
"写临时文件 + rename" 保证原子性，rename 在 littlefs 上是原子的，掉电最多丢掉
这一次 +1，不会把计数写坏。

日志文件上限 LOG_LIMIT 字节，超了轮转成 log.0.txt（只保留一代，最多 2 个文件）。
"""

import os
import time

LOG_DIR = "log"
BOOT_FILE = LOG_DIR + "/boot.id"
BOOT_TMP = LOG_DIR + "/boot.tmp"
LOG_FILE = LOG_DIR + "/log.txt"
LOG_OLD = LOG_DIR + "/log.0.txt"

LOG_PERIOD_S = 60          # 记录周期：1 分钟一条
LOG_FLUSH_MIN = 30         # 攒够这么多条（= 分钟）才落盘，见文件头寿命计算
LOG_LIMIT = 400 * 1024     # 单个日志文件上限；超了轮转到 log.0.txt
                           # 一行 91 字符，400KB 约存 4500 行 = 3 天；
                           # 加上轮转的 log.0.txt 一共约 6 天历史

# 内部状态
_buf = []                  # 还没落盘的日志行
_next_s = 0                # 下一个该记录的整分钟（相对上电的秒数）
_t0 = 0                    # 上电时刻（ticks_ms）


def _ensure_dir():
    try:
        os.mkdir(LOG_DIR)
    except OSError:
        pass                      # 已存在


# ---------------------------------------------------------------- 上电次数
def _read_boot():
    try:
        f = open(BOOT_FILE, "r")
        s = f.read()
        f.close()
        return int(s.strip() or 0)
    except (OSError, ValueError):
        return 0


def _write_boot(n):
    """原子写：先写 tmp 再 rename。rename 在 littlefs 上是原子的。"""
    f = open(BOOT_TMP, "w")
    f.write("%d\n" % n)
    f.close()
    os.rename(BOOT_TMP, BOOT_FILE)


def begin():
    """开机调用一次：上电次数 +1 并返回新值；同时重置日志计时起点。"""
    global _t0, _next_s
    _ensure_dir()
    n = _read_boot() + 1
    _write_boot(n)
    _t0 = time.ticks_ms()
    _next_s = 0
    return n


# ---------------------------------------------------------------- 格式化
def fmt_elapsed(sec):
    """秒 -> hh:mm（超过 99 小时就继续累加，不截断）。"""
    m = sec // 60
    return "%02d:%02d" % (m // 60, m % 60)


def fmt_line(boot_id, sec, d):
    """拼一行日志。d 是 ui.draw 用的那个 dict。"""
    hcho = d.get("hcho")
    if hcho is None:
        ch2o = "--"
    else:
        ch2o = "%.2f" % hcho
    return "[%04d %s] PM1: %d ug/m3, PM2.5: %d ug/m3, PM10: %d ug/m3, CO2: %d ppm, CH2O: %s mg/m3" % (
        boot_id % 10000, fmt_elapsed(sec),
        d.get("pm1", 0), d.get("pm25", 0), d.get("pm10", 0),
        d.get("co2", 0), ch2o)


# ---------------------------------------------------------------- 落盘
def _rotate():
    """log.txt 超上限时轮转：删掉旧的一代，当前改名成 log.0.txt。"""
    try:
        os.remove(LOG_OLD)
    except OSError:
        pass
    try:
        os.rename(LOG_FILE, LOG_OLD)
    except OSError:
        pass


def _flush():
    """把缓冲区一次性写进文件 —— 一次 open/close 就是一次元数据提交。"""
    global _buf
    if not _buf:
        return
    try:
        try:
            sz = os.stat(LOG_FILE)[6]
        except OSError:
            sz = 0
        if sz > LOG_LIMIT:
            _rotate()
        f = open(LOG_FILE, "a")
        f.write("".join(_buf))
        f.close()
        _buf = []
    except OSError:
        # 写失败（flash 满/只读）时保留缓冲区，下次再试，不要把记录丢掉
        pass


def flush_now():
    """强制落盘（准备掉电/复位前调用有意义，正常运行不需要）。"""
    _flush()


# ---------------------------------------------------------------- 周期调用
def tick(now_ms, d, boot_id):
    """在主循环里调用。到整分钟就往缓冲区加一条，攒够 LOG_FLUSH_MIN 条才落盘。

    now_ms 传 time.ticks_ms() 的当前值（用 ticks_diff 算间隔，能扛住回绕）。
    """
    global _next_s
    el = time.ticks_diff(now_ms, _t0) // 1000
    added = False
    # while 而不是 if：主循环偶尔被串口阻塞时会一次跨过多个整分钟
    while el >= _next_s:
        _buf.append(fmt_line(boot_id, _next_s, d))
        _next_s += LOG_PERIOD_S
        added = True
    if added and len(_buf) >= LOG_FLUSH_MIN:
        _flush()


def stats():
    """返回 (日志条数, 文件大小, 轮转文件大小)，调试/自检用。"""
    def _sz(p):
        try:
            return os.stat(p)[6]
        except OSError:
            return 0
    n = 0
    try:
        f = open(LOG_FILE, "r")
        for _ in f:
            n += 1
        f.close()
    except OSError:
        pass
    return n, _sz(LOG_FILE), _sz(LOG_OLD)
