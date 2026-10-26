"""界面层：只管怎么画，不碰硬件。

为什么单独拆一个文件（而不是全塞进 main.py）：
  1. **主机上能直接预览** —— 这个模块不 import machine / SSD1325，只接收一个
     "看起来像 SSD1325 模块"的对象（真机传 SSD1325 模块，主机传 preview 里的
     模拟器），所以界面可以在电脑上反复调，不用拷进设备、复位、等开机看效果；
  2. 真机每 500ms 重画一次，绘制逻辑集中在一处才好改。

⚠️ 四条用血换来的规矩（CH559 那套界面最后定下来的）：
  1. 文字颜色的**背景半字节必须等于所在区域的底色**：灰带(bg=6)上用 0x6F、
     CO2 行(bg=1)上用 0x1F、暗字用 0x15 —— 否则会在灰底上抠出一圈黑框。
  2. 数码管大数字 20x32 要**独占** 32 行，标签得让位（放状态带里），
     否则会压住标签。
     是个像小数点的字形，补空格会多出一个孤零零的圆点。
  4. 状态带右侧的等级字只放**一个字**：16x16 中文在 x=112 时只剩 16px，
     两个字会越过 128 的右边界，而 prt() 越界会自动换行到下一行（驱动行为）。
"""

W, H = 128, 64

# ---- 灰度分层（4 位屏最值钱的地方就是它，比画边框划算）----
C_BAND = 6      # 状态带底色
C_CO2 = 1       # CO2 行的底色（比主区亮一点，把两块分开）
C_HI = 0x0F     # 主区数值：纯白（背景 0 = 主区底色）
C_LBL = 0x08    # 主区标签：暗灰
C_DIM = 0x05    # 更暗的次要信息

# ---- PM2.5 分档：GB 3095 二级标准 24h 均值 35 / 75 / 115 / 150 / 250 ----
# 每档 (上限, 等级单字, 角标 id)。角标都取"空气质量/警示"那组图。
GRADES = (
    # 图标按"防护等级逐级升高"递进：这套图里没有专门的"空气好"图标，
    # 但有口罩/防毒面罩/警告这一组，语义上正好对应分档。
    #   好的一端（3004 肺 / 3001 叶子 / 3002 气流）是自己画的 —— 现成那套是天气
    #   摆件素材，没有"空气好"的图形；差的一端正好有口罩/防毒面罩/警告，语义是通的。
    (35,  "优", 3004),      # 自己画的：肺（呼吸健康）
    (75,  "良", 3001),      # 自己画的：叶子
    (115, "轻", 1021),      # 现成素材：口罩
    (150, "中", 1029),      # 现成素材：防毒面罩
    (250, "重", 9998),      # 现成素材：警告三角
)
GRADE_LAST = ("严", 9999)

# ---- 界面里用到的全部中文，**显式列出来**（tools/make_cjk.py 照这个生成子集）
# 为什么显式列、不扫源码：扫字符串字面量会把注释/docstring 里的中文也抓进去，
# 我第一版就这么干了，结果字集从 12 字膨胀到 285 字、字体从 288 字节变成 6840 字节。
# 显式声明既准确、又顺便当成"界面文案清单"。
ZH_CHARS = "优良轻中重严空气质量甲醛"

# 主区轮换的三个 PM 值
PM_ITEMS = (("PM2.5", "pm25"), ("PM1.0", "pm1"), ("PM10", "pm10"))


# 甲醛限值：GB/T 18883《室内空气质量标准》规定 1 小时均值 0.08 mg/m3
HCHO_LIMIT = 0.08


def hcho_text(v):
    """甲醛数值格式化，返回 (显示文本, 是否超标)。

    * 传感器还没接 → 传 None → 显示 "--"；
    * 其余按 mg/m3 **两位小数**：'0.06' 正好 4 格，和预留的宽度一致。
      ⚠️ 用三位小数（'0.065'）会到 5 格，从 x=102 起算就到 x=132、**越过 128 右边界**，
      而 prt() 越界会自动换行到下一行（驱动行为）—— 所以这里限两位。
    """
    if v is None:
        return "--", False
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "--", False
    return "%.2f" % f, f > HCHO_LIMIT


def grade_of(pm25):
    """按 PM2.5 返回 (等级单字, 角标 id) —— 阈值是国标 24h 均值档。"""
    for lim, ch, ico in GRADES:
        if pm25 <= lim:
            return ch, ico
    return GRADE_LAST


def badge(o, x, y, icon_id, size=32, src=64, prefix="icon"):
    """从 64x64 图标文件里**隔点取样**出 size x size 的角标。

    为什么这么啰嗦：bmp() 一次只发整块缓冲，真机上要做角标就只能自己读文件、
    按 "src/2 字节一行、高半字节是左像素" 把像素取出来重打包。隔点会丢细节、
    锯齿明显 —— 这是真机能做到的画质（想更好就得预先生成 32x32 的图标文件）。
    """
    path = "%s/%d.bin" % (prefix, icon_id)
    try:
        f = open(path, "rb")
        data = f.read(src * src // 2)
        f.close()
    except OSError:
        return
    if len(data) < src * src // 2:
        return
    step = src // size
    buf = bytearray(size * size // 2)
    for row in range(size):
        for c in range(size):
            sr, sc = row * step, c * step
            b = data[sr * (src // 2) + (sc >> 1)]
            v = (b >> 4) if (sc & 1) == 0 else (b & 0x0F)
            j = row * (size // 2) + (c >> 1)
            if c & 1:
                buf[j] = (buf[j] & 0xF0) | v
            else:
                buf[j] = (buf[j] & 0x0F) | (v << 4)
    o.bmp(x + size // 2, y + size // 2, size, size, buf, True)


# 上一帧画过的内容缓存。只重画变化的部分 —— 整屏刷新在 20MHz PIO 上要约 1.6ms，
# 而稳定运行时绝大多数帧只有 PM 数值变，其余元素根本不用碰。
_last = {}


def reset():
    """外部清屏后必须调用，让下一帧全量重画（否则缓存状态和屏幕不一致）。"""
    _last.clear()


def draw(o, d, which, prefix="icon"):
    """画一帧。按内容增量重画，只有变化的区域才会写屏。

    o      : 屏幕对象（真机是 SSD1325 模块，主机是预览模拟器）
    d      : dict，含 pm1 / pm25 / pm10 / co2 / hcho
             （hcho 可以是 float、字符串，或 None 表示传感器还没接）
    which  : 主区轮换到第几个 PM 值（0=PM2.5 / 1=PM1.0 / 2=PM10）
    prefix : 图标目录前缀（真机是 "icon"，主机是绝对路径）
    """
    name, key = PM_ITEMS[which]
    ch, ico = grade_of(d["pm25"])
    htxt, hbad = hcho_text(d.get("hcho"))
    co2 = d["co2"]
    val = d[key]

    # ---- 状态带：只有轮换或等级变化才重画（灰底 + 标签 + 中文等级）
    if _last.get("band") != (which, ch):
        o.fill(0, 0, W, 16, C_BAND)
        o.prt(3, 4, 0, 0x6F, name)              # 6x8 标签，背景=6 与灰带一致
        o.prt(112, 2, 2, 0x6F, ch)              # 12x12 中文等级，背景=6
        _last["band"] = (which, ch)

    # ---- 主区大数字：值变了才重画（digi7 是 4 位定宽，宽度不随数值变）
    if _last.get("main") != (which, val):
        o.fill(0, 16, 86, 26, 0)      # x 0..85，不碰 x>=86 的角标（否则擦掉角标左边）
        o.digi7(40, 19, "%4d" % val)
        _last["main"] = (which, val)

    # ---- 角标：等级或图标目录变化才重画
    if _last.get("icon") != (ico, prefix):
        badge(o, 86, 16, ico, 32, 64, prefix)
        _last["icon"] = (ico, prefix)

    # ---- 底部条：底纹和静态标签只画一次
    if not _last.get("bar"):
        o.fill(4, 48, 120, 16, C_CO2)
        o.prt(7, 52, 0, 0x15, "CO2")            # 6x8 标签：fg=5 暗、bg=1
        o.prt(64, 50, 2, 0x1F, "甲醛")          # 静态中文标签
        _last["bar"] = True

    # CO2 数值：值变了才重画（x=31 留一格，避免和 CO2 标签粘在一起）
    if _last.get("co2") != co2:
        o.prt(31, 52, 0, 0x1F, "%4d" % co2)
        _last["co2"] = co2

    # 甲醛数值：内容或超标状态变了才重画
    if _last.get("hcho") != (htxt, hbad):
        if hbad:
            # 超标 → 反白（fg=1 暗字、bg=15 亮底）。color 编码是 fg | bg<<4。
            o.fill(96, 50, 26, 12, 0x0F)
            o.prt(97, 52, 0, 0xF1, htxt)
        else:
            # 从反白状态恢复时必须把白底擦回底纹色，否则白块会留在屏上
            o.fill(96, 50, 26, 12, C_CO2)
            o.prt(97, 52, 0, 0x1F, htxt)
        _last["hcho"] = (htxt, hbad)


LOGO_W = 48
LOGO_H = 40
_logo_data = None


def _logo(prefix="icon"):
    """惰性读 logo 字模（4 位灰度，66x56 = 1848 字节）。"""
    global _logo_data
    if _logo_data is None:
        _logo_data = open(prefix + "/logo.bin", mode="rb").read()
    return _logo_data


def draw_boot(o, msg="BOOTING"):
    """开机画面：居中显示 logo（icon/logo.bin，48x40 4 位灰度，居中）。

    logo 占满大半个屏，所以不再画文字；msg 参数保留，供以后需要时切回文字版。
    """
    o.clear(0)
    o.bmp((W - LOGO_W) // 2, (H - LOGO_H) // 2, LOGO_W, LOGO_H, _logo())


