"""运行日志 + 上电次数统计。

日志格式（每 2 分钟一条）：
    [0000 00:00] PM1: 10 ug/m3, PM2.5: 20 ug/m3, PM10: 30 ug/m3, CO2: 400 ppm, CH2O: 0.03 mg/m3
      ^^^^ ^^^^^ 上电次数（单独文件统计） + 上电后经过时间 hh:mm

存储布局（环形世代，每个文件正好存一天）
--------------------------------------
    log/boot.id      上电次数
    log/idx          当前写入的世代号 0..31
    log/g00.txt ...  32 个世代文件，每代 720 行（2 分钟一条 = 1 天）

写完第 32 代就绕回 g00 覆盖，所以固定保留最近约 **32 天**，总占用约
32 x 720 x 92 = 2.07 MB。写满一代才轮转一次 -> 每 24 小时一次 rename。

为什么要攒批落盘（这块板最需要注意的地方）
----------------------------------------
存储是 **W25Q128JVPIQ**（16 MB / 4 KB 扇区 / 手册标称最低 10 万次编程-擦除）。

MicroPython 的 RP2 端口用 **littlefs2**。它有磨损均衡，但**元数据对**（每个目录
固定的一对块）不参与均衡 —— "反复 open/append/close 同一个文件"仍然会把那一对块
写穿，和文件多大无关。

一次 append+close = 一次元数据提交（追加不改目录项，只提交文件自己的元数据对），
摊到那对 2 个块上。**磨损只取决于落盘次数，和记录周期无关**：

    落盘间隔      落盘次数/年    元数据块写入/年   10 万次寿命
    1 分钟        52.6 万        26.3 万          约 4.6 个月
    5 分钟        10.5 万        5.3 万           约 1.9 年
    15 分钟       3.5 万         1.75 万          约 5.7 年
    30 分钟       1.75 万        8760             约 11 年
    60 分钟       8760           4380             约 23 年   <- 当前配置

数据块是循环分配的，按当前写入量每块每年只擦几十次，不是瓶颈。
真正的限制只有元数据对不参与均衡这一点。

当前配置：**2 分钟记录一条、1 小时合并落盘**（每次 30 条约 2.7 KB）。
代价：掉电最多丢 1 小时内还没落盘的记录。

上电次数（log/boot.id）每次开机只写一次，写入量可忽略；写入用
"写临时文件 + rename" 保证原子性，rename 在 littlefs 上是原子的，掉电最多丢掉
这一次 +1，不会把计数写坏。
"""

import os
import time

LOG_DIR = "log"
BOOT_FILE = LOG_DIR + "/boot.id"
BOOT_TMP = LOG_DIR + "/boot.tmp"
IDX_FILE = LOG_DIR + "/idx"
GEN_FMT = LOG_DIR + "/g%02d.txt"
OLD_LOG = LOG_DIR + "/log.txt"        # 旧版本的单一日志文件，开机时并入当前代

LOG_PERIOD_S = 120         # 记录周期：2 分钟一条
LOG_FLUSH_MIN = 60         # 攒够这么多条（= 分钟）才落盘，见文件头寿命计算

LINES_PER_FILE = 720       # 每代 720 行 = 2 分钟一条的 1 天
GENERATIONS = 32           # 保留 32 代 = 约 32 天
LINE_BYTES = 92            # 估算用：最长一行 91 字符 + 换行
BYTES_PER_FILE = LINES_PER_FILE * LINE_BYTES
LOG_TOTAL = GENERATIONS * BYTES_PER_FILE

# 每次落盘攒多少行：LOG_FLUSH_MIN 分钟 x 60 秒 / LOG_PERIOD_S
_LINES_PER_FLUSH = max(1, LOG_FLUSH_MIN * 60 // LOG_PERIOD_S)

# 内部状态
_buf = []                  # 还没落盘的日志行
_next_s = 0                # 下一个该记录的整分钟（相对上电的秒数）
_t0 = 0                    # 上电时刻（ticks_ms）
_cur = -1                  # 当前写入的世代号，-1 表示还没确定


def _ensure_dir():
    try:
        os.mkdir(LOG_DIR)
    except OSError:
        pass                      # 已存在


def _sz(path):
    try:
        return os.stat(path)[6]
    except OSError:
        return 0


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
    try:
        os.rename(BOOT_TMP, BOOT_FILE)
    except OSError:
        # CPython 的 os.rename 不覆盖已存在文件（MicroPython 会）。
        # 这个分支只是为了让同一份代码能在电脑上跑测试，设备上走不到这里。
        try:
            os.remove(BOOT_FILE)
        except OSError:
            pass
        os.rename(BOOT_TMP, BOOT_FILE)


# ---------------------------------------------------------------- 世代索引
def _read_idx():
    try:
        f = open(IDX_FILE, "r")
        s = f.read()
        f.close()
        return int(s.strip() or 0) % GENERATIONS
    except (OSError, ValueError):
        return 0


def _write_idx(n):
    """轮转时才写一次（约 1 天 1 次），不做原子写 —— 掉电丢了最多从头绕。"""
    try:
        f = open(IDX_FILE, "w")
        f.write("%d\n" % (n % GENERATIONS))
        f.close()
    except OSError:
        pass


def _pick_start():
    """决定当前该写哪一代。索引有效就接着写，否则找 mtime 最新的一代。"""
    global _cur
    if _cur >= 0:
        return
    n = _read_idx()
    # 索引指向的那代有内容，或者上一代有内容（说明刚轮转完、新一代还是空的）
    if _sz(GEN_FMT % n) > 0 or _sz(GEN_FMT % ((n + GENERATIONS - 1) % GENERATIONS)) > 0:
        _cur = n
        return
    # 首次运行 / 掉电丢了索引：取 mtime 最新的那一代
    best, best_t = 0, -1
    for i in range(GENERATIONS):
        try:
            t = os.stat(GEN_FMT % i)[8]
        except OSError:
            continue
        if t > best_t:
            best, best_t = i, t
    _cur = best


def _rotate():
    """换到下一代。

    ⚠️ 必须先把目标代**删掉**：环形世代绕回来时那一代里还是 30 多天前的旧内容，
    如果只是切过去继续 append，文件会越过 LINES_PER_FILE 一路长下去
    （模拟测试里第 33 天就出现了 751 行的文件）。
    """
    global _cur
    _cur = (_cur + 1) % GENERATIONS
    try:
        os.remove(GEN_FMT % _cur)
    except OSError:
        pass
    _write_idx(_cur)


# ---------------------------------------------------------------- 开机
def begin():
    """开机调用一次：上电次数 +1 并返回新值；同时重置日志计时起点。"""
    global _t0, _next_s, _cur
    _ensure_dir()
    n = _read_boot() + 1
    _write_boot(n)
    _t0 = time.ticks_ms()
    _next_s = 0
    _cur = -1
    _pick_start()
    # 旧版本的单一 log.txt 并入当前代（只在升级后的第一次开机发生）
    if _sz(OLD_LOG) > 0:
        try:
            os.rename(OLD_LOG, GEN_FMT % _cur)
        except OSError:
            pass
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
    # ⚠️ 结尾必须带换行：多行是 "".join() 拼起来一次性写盘的，
    #    没有换行的话 720 行会被拼成一整行（实测时每文件只剩"1 行"就是这个原因）。
    return "[%04d %s] PM1: %d ug/m3, PM2.5: %d ug/m3, PM10: %d ug/m3, CO2: %d ppm, CH2O: %s mg/m3\n" % (
        boot_id % 10000, fmt_elapsed(sec),
        d.get("pm1", 0), d.get("pm25", 0), d.get("pm10", 0),
        d.get("co2", 0), ch2o)


# ---------------------------------------------------------------- 落盘
def _flush():
    """把缓冲区一次性写进当前世代文件。

    一次 open/close 就是一次元数据提交；写满一代（720 行）才轮转 ——
    轮转本身只是一次 rename，比写文件便宜。
    """
    global _buf
    if not _buf:
        return
    try:
        _pick_start()
        path = GEN_FMT % _cur
        batch = "".join(_buf)
        if _sz(path) + len(batch) > BYTES_PER_FILE:
            _rotate()
            path = GEN_FMT % _cur
        f = open(path, "a")
        f.write(batch)
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
    if added and len(_buf) >= _LINES_PER_FLUSH:
        _flush()


# ---------------------------------------------------------------- 自检
def stats():
    """返回 (总行数, 已用字节, 占用百分比)，调试/自检用。"""
    lines = 0
    used = 0
    for i in range(GENERATIONS):
        p = GEN_FMT % i
        n = _sz(p)
        if not n:
            continue
        used += n
        try:
            f = open(p, "r")
            for _ in f:
                lines += 1
            f.close()
        except OSError:
            pass
    pct = 0 if LOG_TOTAL == 0 else used * 100 // LOG_TOTAL
    return lines, used, pct


def space():
    """返回 (总字节, 可用字节, 已用百分比)，设备上直接调来确认剩余空间。

    RP2040 + 16MB flash 的机器整个芯片都给 littlefs，可用约 15MB；
    换回普通 2MB 的 Pico 时这里的数字会小一个数量级，GENERATIONS 要跟着降。
    """
    st = os.statvfs("/")
    bs, blocks, free = st[0], st[2], st[3]
    total = bs * blocks
    avail = bs * free
    used = 0 if total == 0 else 100 - avail * 100 // total
    return total, avail, used
