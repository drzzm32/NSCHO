"""三版 UI 方案，各渲一张，供挑选。

共性（用户已定）：
  * 顶部一行小字状态栏（手机那种）：室内 · 运行 hh:mm:ss · 姿态正常
  * 主区：12x18 数码管大字温度，颜色按区间变；湿度跟在旁边
  * 姿态区：水平仪圆盘 + 十字准星 + 小球，球朝**下坡**滚（物理水平仪式）
  * 底部：俯仰 / 横滚 数值
变体：A 上下分栏、B 左右分栏、C 卡片式。

注意：这里只用驱动真实的 API 画（fill 画圆环/十字，digi 画大字，prt 画中文），
不直接改像素 —— 否则预览就失去意义。圆和十字是用 1~2 像素高的横条拼的，
因为驱动没有画线/圆的原语。
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "preview"))
from ssd1351_sim import SSD1351          # noqa: E402

W = H = 128
OUT = ROOT / "preview" / "out"

# ------------------------------------------------------------------ 配色
BG        = 0x0B0F14      # 整体背景：很深的蓝黑
BAR       = 0x123047      # 状态栏底
BAR_TXT   = 0x8FA8BC      # 状态栏字
SEP       = 0x1E3A50      # 分隔线
LBL       = 0x7A8FA3      # 标签（暗）
VAL       = 0xFFFFFF      # 数值（白）
CARD      = 0x151E28      # 卡片底
CARD2     = 0x1B2634      # 卡片底（第二层）
TRACK     = 0x24384D      # 圆环轨道 / 十字
BALL      = 0xFFD54F      # 小球
BALL_OK   = 0x66BB6A      # 小球：水平时变绿
OK        = 0x66BB6A
WARN      = 0xFFB300


def temp_color(t):
    """沿用原代码的色阶（整数温度）。"""
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


# ------------------------------------------------------------------ 绘图原语（只用 fill）
def ring(p, cx, cy, r, color, thick=1):
    """用逐行的水平横条拼圆环（驱动没有画线原语）。"""
    for dy in range(r, -r - 1, -1):
        # 这一段圆环在这一行的左右边界
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


def level(p, cx, cy, r, pitch, roll, labels=True):
    """水平仪：外环 + 内环 + 十字 + 小球。球朝下坡滚。"""
    ring(p, cx, cy, r, TRACK, 1)
    ring(p, cx, cy, max(4, r // 2), TRACK, 1)
    hline(p, cx - r, cx + r, cy, TRACK, 1)
    vline(p, cx, cy - r, cy + r, TRACK, 1)
    # 俯仰/横滚 -> 小球偏移（限幅在半径内，45 度满偏）
    import math
    k = min(1.0, abs(roll) / 45.0)
    bx = cx + int(math.copysign(r * 0.78 * k, roll))
    k = min(1.0, abs(pitch) / 45.0)
    by = cy + int(math.copysign(r * 0.78 * k, pitch))
    ok = abs(pitch) < 1.5 and abs(roll) < 1.5
    disc(p, bx, by, 4, BALL_OK if ok else BALL)
    disc(p, bx, by, 2, 0xFFFFFF)


def status_bar(p, uptime, state, state_col):
    p.fill(0, 0, W, 12, BAR)
    # 中文 12px/字、ASCII 6x8 是 6px/字，所以 "室内"(24px) 放到 3..26，
    # uptime(7 字 = 42px) 从 30 开始，状态词从 76 开始（最多 4 字 = 48px -> 到 123）
    p.prt(3, 3, 0, BAR_TXT, BAR, "室内")
    p.prt(30, 3, 0, BAR_TXT, BAR, uptime)
    p.prt(76, 3, 0, state_col, BAR, state)
    p.fill(0, 12, W, 1, SEP)


def layout_a(t=23.5, r=48.2, pitch=-9.3, roll=12.4):
    """A 上下分栏：上半温湿度、下半水平仪。"""
    p = SSD1351()
    p.clear(BG)
    status_bar(p, "1:02:33", "姿态正常", OK)
    tc = temp_color(int(t))
    p.prt(4, 16, 0, LBL, BG, "温度")            # 2 字 = 24px -> 4..27
    p.digi(38, 33, tc, BG, "%4.1f" % t)        # 4 字 = 48px，中心 38 -> 14..62
    p.prt(4, 46, 0, LBL, BG, "湿度")
    p.digi(32, 62, humi_color(int(r)), BG, "%2d" % r)   # 2 字 = 24，中心 32 -> 20..44
    p.prt(48, 57, 0, LBL, BG, "%")
    p.fill(0, 74, W, 1, SEP)
    p.prt(4, 77, 0, LBL, BG, "倾角")            # 4..27
    level(p, 64, 100, 18, pitch, roll)          # 46..82 x, 82..118 y
    p.prt(2, 96, 0, LBL, BG, "%+5.1f" % pitch)  # 5 字 = 30 -> 2..32
    p.prt(96, 96, 0, LBL, BG, "%+5.1f" % roll)  # 96..126
    return p


def layout_b(t=23.5, r=48.2, pitch=-9.3, roll=12.4):
    """B 左右分栏：左边温湿度竖排、右边水平仪。"""
    p = SSD1351()
    p.clear(BG)
    status_bar(p, "1:02:33", "正常", OK)
    tc = temp_color(int(t))
    p.prt(3, 18, 0, LBL, BG, "温度")
    p.digi(32, 40, tc, BG, "%4.1f" % t)        # 中心 32 -> 8..56
    p.prt(3, 56, 0, LBL, BG, "湿度")
    p.digi(26, 76, humi_color(int(r)), BG, "%2d" % r)   # 中心 26 -> 14..38
    p.prt(42, 71, 0, LBL, BG, "%")
    vline(p, 62, 16, 124, SEP)
    level(p, 96, 60, 24, pitch, roll)           # 72..120 x, 36..84 y
    # ⚠️ 底部只能放 6x8 的 ASCII：12 高的中文放在 y=120 会让 prt() 判定越界
    #（y > 128-12 = 116）触发清屏，把整屏擦掉。这是驱动的真实行为，不是模拟器的毛病。
    p.prt(66, 92, 0, LBL, BG, "俯仰")
    p.prt(94, 92, 0, VAL, BG, "%+5.1f" % pitch)
    p.prt(66, 104, 0, LBL, BG, "横滚")
    p.prt(94, 104, 0, VAL, BG, "%+5.1f" % roll)
    # 最底下一行只能放纯 ASCII（prt() 逐字判断越界，混进 12 高的中文会在中途清屏）
    p.prt(66, 118, 0, SEP, BG, "ascii only")
    return p


def layout_c(t=23.5, r=48.2, pitch=-9.3, roll=12.4):
    """C 卡片式：两块圆角感卡片（靠底色分层，不画边框）。"""
    p = SSD1351()
    p.clear(BG)
    status_bar(p, "1:02:33", "姿态正常", OK)
    # 温度卡
    p.fill(4, 16, 120, 46, CARD)
    p.prt(8, 20, 0, LBL, CARD, "温度")
    p.digi(44, 38, temp_color(int(t)), BG, "%4.1f" % t)   # 中心 44 -> 20..68
    p.prt(78, 20, 0, LBL, CARD, "湿度")
    p.digi(98, 44, humi_color(int(r)), BG, "%2d" % r)     # 中心 98 -> 86..110
    p.prt(114, 39, 0, LBL, CARD, "%")
    # 姿态卡
    p.fill(4, 66, 120, 58, CARD2)
    p.prt(8, 70, 0, LBL, CARD2, "倾角")
    level(p, 42, 96, 16, pitch, roll)          # 26..58 x, 80..112 y
    p.prt(66, 78, 0, LBL, CARD2, "俯仰")
    p.prt(94, 78, 0, VAL, CARD2, "%+5.1f" % pitch)
    p.prt(66, 100, 0, LBL, CARD2, "横滚")
    p.prt(94, 100, 0, VAL, CARD2, "%+5.1f" % roll)
    return p


VARIANTS = (("A", layout_a), ("B", layout_b), ("C", layout_c))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    frames = []
    for name, fn in VARIANTS:
        p = fn()
        ink = sum(1 for c in p.ram if c != 0)
        nz = sum(1 for c in p.ram if c != __import__("ssd1351_sim").rgb565(BG))
        print(f"   方案 {name}: 非黑像素 {ink}, 与背景不同的像素 {nz}")
        frames.append((name, p.to_image()))
        p.to_image(3).save(OUT / f"ui_{name.lower()}.png")
    sc, pad = 3, 8
    comp = Image.new("RGB", (128 * sc * 3 + pad * 4, 128 * sc + pad * 2 + 18), (30, 30, 30))
    from PIL import ImageDraw
    d = ImageDraw.Draw(comp)
    for i, (name, im) in enumerate(frames):
        x = pad + i * (128 * sc + pad)
        d.text((x, 4), name, fill=(220, 220, 220))
        comp.paste(im.resize((128 * sc, 128 * sc), Image.NEAREST), (x, pad + 12))
    f = OUT / "ui_variants.png"
    comp.save(f)
    print(f"   三版方案 -> {f}")


if __name__ == "__main__":
    main()
