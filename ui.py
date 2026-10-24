"""界面层：只管怎么画，不碰硬件。

为什么单独拆一个文件：这个模块不 import machine / SSD1351，只接收一个"看起来像
SSD1351 模块"的对象（真机传驱动，电脑传 preview/ssd1351_sim.py）。
所以界面不用拷进设备、不用复位等开机，就能在主机上反复调 —— 三版方案图就是
直接调这里的函数渲出来的，不是另画一份示意图。

⚠️ 三条从驱动行为里总结出来的硬约束（真机上违反会立刻看得见）：
  1. **底部 12 像素只能放 6x8 的 ASCII**。prt() 的越界判断是 y > 128 - 字高，
     一旦成立就清屏回到 (0,0)；12 高的中文放在 y=120 满足 120 > 116，会把整屏擦掉。
     而且它是**逐字**判断的，混排字符串里中途遇到中文也会清屏。
  2. **中文字宽 12px、ASCII 6x8 是 6px**，排坐标时不能混着按 6px 算，
     否则标签和数字会重叠（第一版方案图就是这么错的）。
  3. digi() 的 x、y 是整串的**中心**；icon() 的 x、y 是图标的中心。

改界面用字必须同步改下面的 ZH_CHARS —— 中文是子集，没在表里的字画不出来。
"""

W = H = 128

# ---------------------------------------------------------------- 配色
BG      = 0x0B0F14     # 整体背景：很深的蓝黑
BAR     = 0x123047     # 状态栏底
BAR_TXT = 0x8FA8BC     # 状态栏字
SEP     = 0x1E3A50     # 分隔线
LBL     = 0x7A8FA3     # 标签（暗）
VAL     = 0xFFFFFF     # 数值（白）
CARD    = 0x151E28     # 卡片底
CARD2   = 0x1B2634     # 卡片底（第二层）
TRACK   = 0x24384D     # 圆环轨道 / 十字
# 状态点一个完整呼吸的时长（亮一半、灭一半）。
# ⚠️ main.py 的 DRAW_MS 是 160ms，本周期 500ms 意味着每个相位只有约
#    1.5 帧 —— 真机上会看起来不太均匀。想要更顺就让周期长一点（比如
#    1000）或把 DRAW_MS 调小；但 DRAW_MS 太小会让 SPI 占满、传感器取样变慢。
BLINK_MS = 500
BALL    = 0xFFD54F     # 小球（未水平）
BALL_OK = 0x66BB6A     # 小球（已水平）
OK      = 0x66BB6A
WARN    = 0xFFB300

# ---------------------------------------------------------------- 界面用到的全部中文
# 「气温」而不是「温度」：12x12 下「温」「湿」两个字都有氵和日、右边只差几笔，
# 真机 1.6mm 高度基本分不出来；「气」和「湿」差别大，一眼就能区分。
ZH_CHARS = (
    "气温湿度"        # 两个主读数的标签
    "俯仰横滚"        # 姿态角
    "倾角"            # 姿态区标题
    "供电"            # 左下角的电源信息（电池位实际是直流供电）
    "正常微斜倾"      # 状态词（正常 / 微斜 / 倾斜）
)


def temp_color(t):
    """温度色阶，沿用原 main.py 的思路（整数温度）。"""
    if t <= 0:
        return 0x2196F3
    if t <= 16:
        return 0x4CAF50
    if t <= 26:
        return 0xFFC107
    if t <= 31:
        return 0xFF5722
    return 0xF44336


def humi_color(r):
    if r <= 33:
        return 0x03A9F4
    if r <= 66:
        return 0x8BC34A
    return 0xFF9800


def level_state(pitch, roll):
    """水平状态：返回 (状态词, 颜色)。

    三态按"偏离静止水平面的角度"分：<1.5 度算正常、<5 度微斜、再大就是倾斜。
    原来写的是 偏高/偏低，那是从"温度高低"那边顺手拿的词，对姿态没有意义。
    """
    if abs(pitch) < 1.5 and abs(roll) < 1.5:
        return "正常", OK
    if abs(pitch) < 5 and abs(roll) < 5:
        return "微斜", WARN
    return "倾斜", 0xFF7043


# ---------------------------------------------------------------- 绘图原语（只有 fill 可用）
def ring(p, cx, cy, r, color, thick=1):
    """逐行横条拼圆环 —— 驱动没有画线/画圆的原语。"""
    for dy in range(r, -r - 1, -1):
        span = int((r * r - dy * dy) ** 0.5)
        inner = max(0, span - thick + 1)
        p.fill(cx - span, cy + dy, span - inner + 1, 1, color)
        p.fill(cx + inner, cy + dy, span - inner + 1, 1, color)


def hline(p, x0, x1, y, color, t=1):
    p.fill(min(x0, x1), y, abs(x1 - x0) + 1, t, color)


def vline(p, x, y0, y1, color, t=1):
    p.fill(x, min(y0, y1), t, abs(y1 - y0) + 1, color)


def disc(p, cx, cy, r, color):
    for dy in range(-r, r + 1):
        span = int((r * r - dy * dy) ** 0.5)
        p.fill(cx - span, cy + dy, span * 2 + 1, 1, color)


# 上一次画小球的位置（模块级，跨帧保留）。
# 局部重绘的关键：**球没怎么动就不重画**。水平仪一画就是上百次 fill
# （每次 fill 都是一次独立 SPI 事务），而姿态经过低通滤波后变化很慢，
# 静止时几乎不需要重画。代价是球的移动会有最多 BALL_STEP 像素的量化。
BALL_STEP = 2
_last_ball = [None, None]


# 每个会变的元素记下"上次画的是什么"，内容没变就**不重画**。
# 为什么这是必须的：每帧无条件重画 = 先铺背景再画字，屏幕上就会出现"刷黑再出现"
# 的闪烁。温湿度一秒才更新一次、时间一分钟一次，绝大部分帧其实什么都不用改。
_paint_cache = {}


def _changed(key, value):
    """内容变了返回 True 并记录；没变返回 False。"""
    if _paint_cache.get(key) == value:
        return False
    _paint_cache[key] = value
    return True


def reset_cache():
    """强制下一帧全部重画（切布局、开机后第一次绘制用）。"""
    _paint_cache.clear()
    _last_ball[0] = None
    _last_ball[1] = None


def level(p, cx, cy, r, pitch, roll, force=False):
    """小球水平仪：外环 + 内环 + 十字 + 小球。

    球朝**下坡**滚（物理水平仪那样）：设备往右倾，球往右跑。满 45 度贴内圈。
    只有小球移动超过 BALL_STEP 像素（或 force=True）时才真正重画整块 ——
    重画时要连背景一起填，才能把上一帧的球擦掉。
    """
    k = min(1.0, abs(roll) / 45.0)
    bx = cx + int((1 if roll >= 0 else -1) * r * 0.78 * k)
    k = min(1.0, abs(pitch) / 45.0)
    by = cy + int((1 if pitch >= 0 else -1) * r * 0.78 * k)

    lx, ly = _last_ball[0], _last_ball[1]
    if (not force) and (lx is not None) and (abs(bx - lx) < BALL_STEP) and (abs(by - ly) < BALL_STEP):
        return
    _last_ball[0] = bx
    _last_ball[1] = by

    # 整块重画：先铺背景（擦掉旧球），再画环/十字，最后画球
    p.fill(cx - r - 1, cy - r - 1, 2 * r + 3, 2 * r + 3, BG)
    ring(p, cx, cy, r, TRACK, 1)
    ring(p, cx, cy, max(4, r // 2), TRACK, 1)
    hline(p, cx - r, cx + r, cy, TRACK, 1)
    vline(p, cx, cy - r, cy + r, TRACK, 1)
    ok = abs(pitch) < 1.5 and abs(roll) < 1.5
    disc(p, bx, by, 4, BALL_OK if ok else BALL)
    disc(p, bx, by, 2, 0xFFFFFF)


def prt_cjk(p, x, y, fore, back, s):
    """按固定 12px 步进画中文，**不走 prt() 的自动换行**。

    为什么需要：prt() 每画完一个字都检查 `x >= 128 - 字宽`，成立就折到下一行。
    贴右边缘的中文串必然踩到 —— 状态词放在 x=104 时，画完第一个字 x=116 就满足
    换行条件，第二个字被折到 y=12、露出状态带下面。逐字调 cjk() 就没有这个问题。
    """
    for ch in s:
        p.cjk(x, y, fore, back, ord(ch))
        x += 12


def prt_r(p, x_right, y, fid, fore, back, s):
    """右对齐到 x_right（不含），按实际字宽算起点。

    为什么要它：数码/时间这类数字串宽度随内容变（"+12.4" 和 "-9.3" 差一个字），
    写死 x 就会忽左忽右。右边对齐视觉上才稳。
    """
    f_w = 6 if fid == 0 else 8
    p.prt(x_right - len(s) * f_w, y, fid, fore, back, s)


def status_bar(p, uptime, state, state_col, dot_on=True):
    """顶部状态栏：左边闪烁状态点、中间时间（居中）、右边姿态状态。

    只在内容变化时重画对应的小区域 —— 整条重铺会让时间/状态每帧"闪"一次。
    中文 12 高只能画在 y=0；ASCII(6x8) 8 高，放 y=2 垂直居中。
    """
    if _changed("bar_bg", True):
        p.fill(0, 0, W, 12, BAR)
        p.fill(0, 12, W, 1, SEP)
    if _changed("dot", (dot_on, state_col)):
        p.fill(4, 3, 7, 7, BAR)                 # 先擦掉上一个点
        disc(p, 7, 6, 3, state_col if dot_on else SEP)
    if _changed("time", uptime):
        p.fill(34, 2, 60, 8, BAR)               # 时间区按固定宽度擦
        p.prt(W // 2 - len(uptime) * 6 // 2, 2, 0, BAR_TXT, BAR, uptime)
    if _changed("state", (state, state_col)):
        p.fill(96, 0, 32, 12, BAR)              # 右侧状态词区
        prt_cjk(p, W - len(state) * 12, 0, state_col, BAR, state)


def fmt_uptime(ms):
    """运行时长 -> h:mm（不显示秒：状态点的闪烁已经能表达"在跑"）"""
    s = ms // 1000
    hh, mm = s // 3600, (s // 60) % 60
    return "%d:%02d" % (hh, mm)


def fmt_temp(t):
    """温度 -> 数码管字符串。

    ⚠️ **不能补前导空格**：digi() 的字符表 DIGI_MAP 里没有空格，落表外会取第 16 个
    字形（一个实心方块），画面上就是数字前面多一块。所以这里只做 "%.1f"，
    宽度变化让 digi 自己按中心居中即可。
    """
    return "%.1f" % t


# ---------------------------------------------------------------- 方案 A：上下分栏（默认）
def layout_a(p, t=23.5, r=48.2, pitch=-9.3, roll=12.4, uptime="0:00", blink=True):
    reset_cache()          # 整屏重刷布局，缓存必须清掉
    p.clear(BG)
    st, stc = level_state(pitch, roll)
    status_bar(p, uptime, st, stc, blink)
    # 上半：气温 + 湿度
    # 行距按实际字高排：中文标签 12 高、数码管 18 高，中间留 1~2 像素缝
    p.prt(4, 14, 0, LBL, BG, "气温")              # 14..25
    p.digi(38, 35, temp_color(int(t)), BG, fmt_temp(t))   # 26..44
    p.prt(4, 46, 0, LBL, BG, "湿度")              # 46..57
    p.digi(32, 67, humi_color(int(r)), BG, "%d" % int(r)) # 58..76
    p.prt(48, 62, 0, LBL, BG, "%")                # % 与小字对齐
    # 下半：水平仪
    p.fill(0, 78, W, 1, SEP)
    p.prt(4, 80, 0, LBL, BG, "倾角")              # 80..91
    level(p, 64, 104, 16, pitch, roll, force=True)   # A 版整屏刷新，必须强制重画            # 88..120
    p.prt(2, 100, 0, LBL, BG, "%+5.1f" % pitch)   # 8 高 ASCII，居中于圆环左侧
    p.prt(96, 100, 0, LBL, BG, "%+5.1f" % roll)


# ---------------------------------------------------------------- 方案 B：左右分栏
def layout_b(p, t=23.5, r=48.2, pitch=-9.3, roll=12.4, uptime="0:00", blink=True,
             volt=None, cur=None):
    """B 左右分栏。

    ⚠️ 这里**没有整块铺背景**，也没有 clear()。每个会变的元素自己判断"值变了没"，
    变了才擦自己那块再画 —— 否则每帧刷黑再重写，屏幕上就是闪烁。
    静态元素（标签、分隔线）靠 _changed 只画一次。
    """
    st, stc = level_state(pitch, roll)
    status_bar(p, uptime, st, stc, blink)

    # 静态：左右分隔线 + 标签（只画一次）
    if _changed("sep", True):
        # 先铺背景（从 y=13 起，别盖住 y=12 的分隔线），再画分隔线，最后画标签
        p.fill(0, 13, 62, 115, BG)              # 左栏
        p.fill(63, 13, 65, 115, BG)             # 右栏
        p.fill(62, 13, 1, 115, SEP)             # 中间竖线
        p.fill(0, 12, W, 1, SEP)                # 横线（放在背景之后，避免被盖掉）
        p.prt(3, 18, 0, LBL, BG, "气温")
        p.prt(3, 56, 0, LBL, BG, "湿度")
        p.prt(42, 73, 0, LBL, BG, "%")
        # ⚠️ **按字形中心对齐**（不是基线）：中文墨迹占第 1~11 行（中心 6.0），
        #    6x8 ASCII 数字占 0~6 行（中心 3.0），所以 ASCII 要比中文起始行晚 3 行。
        #    （按基线对齐要晚 5 行，那样数字会明显偏下；按中心才对。）
        p.prt(66, 92, 0, LBL, BG, "俯仰")
        p.prt(66, 106, 0, LBL, BG, "横滚")

    # 供电信息字符串。volt 单位 V、cur 单位 mA；读不到就显示 "--"
    vs = "--.-V" if volt is None else ("%.2fV" % volt)
    cs = "---mA" if cur is None else ("%dmA" % int(cur))

    # 温度（数码管）：值或颜色变了才重画
    tc = temp_color(int(t))
    ts = fmt_temp(t)
    if _changed("temp", (ts, tc)):
        p.fill(4, 30, 58, 22, BG)     # 从 y=30 起，别盖住 18..29 的「气温」标签
        p.digi(32, 40, tc, BG, ts)

    # 湿度
    hc = humi_color(int(r))
    hs = "%d" % int(r)
    if _changed("humi", (hs, hc)):
        p.fill(6, 68, 50, 22, BG)     # 从 y=68 起，别盖住 56..67 的「湿度」标签
        p.digi(26, 78, hc, BG, hs)

    # 水平仪：内部自己判断小球移动
    level(p, 96, 58, 24, pitch, roll)

    # 供电信息（这块板子的"电池位"实际是直流供电，所以显示输入电压/电流）
    if _changed("pwr_lbl", True):
        p.prt(3, 92, 0, LBL, BG, "供电")
    if _changed("volt", vs):
        p.fill(3, 106, 44, 8, BG)
        p.prt(3, 106, 0, VAL, BG, vs)
    if _changed("cur", cs):
        p.fill(3, 116, 44, 8, BG)
        p.prt(3, 116, 0, LBL, BG, cs)

    # 俯仰 / 横滚数值（右对齐，长度会变，按固定宽度擦）
    ps = "%+.1f" % pitch
    if _changed("pitch", ps):
        p.fill(90, 95, 38, 8, BG)
        prt_r(p, 126, 95, 0, VAL, BG, ps)
    rs = "%+.1f" % roll
    if _changed("roll", rs):
        p.fill(90, 109, 38, 8, BG)
        prt_r(p, 126, 109, 0, VAL, BG, rs)


def layout_c(p, t=23.5, r=48.2, pitch=-9.3, roll=12.4, uptime="0:00", blink=True):
    reset_cache()          # 整屏重刷布局，缓存必须清掉
    p.clear(BG)
    st, stc = level_state(pitch, roll)
    status_bar(p, uptime, st, stc, blink)
    p.fill(4, 16, 120, 46, CARD)
    p.prt(8, 20, 0, LBL, CARD, "气温")
    p.digi(44, 42, temp_color(int(t)), BG, fmt_temp(t))   # 33..51，避开上面的标签
    p.prt(78, 20, 0, LBL, CARD, "湿度")
    p.digi(98, 44, humi_color(int(r)), BG, "%d" % int(r))
    p.prt(114, 39, 0, LBL, CARD, "%")
    p.fill(4, 66, 120, 58, CARD2)
    p.prt(8, 70, 0, LBL, CARD2, "倾角")
    level(p, 42, 96, 16, pitch, roll, force=True)   # C 版整屏刷新，必须强制重画
    p.prt(66, 78, 0, LBL, CARD2, "俯仰")
    p.prt(94, 78, 0, VAL, CARD2, "%+5.1f" % pitch)
    p.prt(66, 100, 0, LBL, CARD2, "横滚")
    p.prt(94, 100, 0, VAL, CARD2, "%+5.1f" % roll)


# 换方案只改这一行（三个函数签名一致，方便对比）
LAYOUT = layout_b
LAYOUT_NAME = "B 左右分栏"


def draw(p, t, r, pitch, roll, uptime, volt=None, cur=None):
    """画一帧。

    t / r        : 温度、湿度
    pitch / roll : 姿态角（度）
    uptime       : 运行时长。设备传**毫秒整数**（用 ticks_ms 差值），
                   预览传现成字符串（"1:02:33"）都行 —— 省得预览那边还要伪造毫秒。
    """
    if isinstance(uptime, str):
        txt, blink = uptime, True          # 预览传现成字符串：点常亮，方便看清布局
    else:
        txt = fmt_uptime(uptime)
        blink = (uptime // (BLINK_MS // 2)) % 2 == 0   # 亮 BLINK_MS/2、灭 BLINK_MS/2
    try:
        LAYOUT(p, t, r, pitch, roll, txt, blink, volt=volt, cur=cur)
    except TypeError:
        # A/C 版没有供电参数，退回原签名
        LAYOUT(p, t, r, pitch, roll, txt, blink)
