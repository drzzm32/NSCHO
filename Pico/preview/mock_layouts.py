"""渲染素材总览（图标表 / 数码管字样）和两个 UI 方案。

用法：
    python preview/mock_layouts.py            # 全部渲染到 preview/out/
    python preview/mock_layouts.py --art a    # 顺便在终端打方案 A 的字符画
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ssd1325_sim import SSD1325, ROOT, W, H     # noqa: E402

OUT = ROOT / "preview" / "out"

# 界面上用的配色（4 位灰度 0..15）。扁平化的关键就是用**背景灰度**做分层，
# 不画边框 —— 这也是 CH559 那套界面最后定下来的做法。
C_BAND = 6      # 状态带底色
C_TXT = 0x0F    # 主数值：纯白
C_LBL = 0x08    # 标签：暗灰
C_DIM = 0x05    # 次要信息：更暗
C_TRACK = 3     # 条形图轨道
C_FILL = 0x0F   # 条形图填充


# ============================================================ 素材总览
def icon_sheet():
    ids = sorted(int(p.stem.split("-")[0]) for p in (ROOT / "icon").glob("*.bin")
                 if not p.stem.endswith("-fill"))
    ids = sorted(set(ids))
    cols, cell = 16, 40
    rows = (len(ids) + cols - 1) // cols
    sheet = Image.new("L", (cols * (cell + 4) + 4, rows * (cell + 14) + 4), 24)
    d = ImageDraw.Draw(sheet)
    for n, idx in enumerate(ids):
        cx, cy = 4 + (n % cols) * (cell + 4), 4 + (n // cols) * (cell + 14)
        p = SSD1325()
        p.icon(32, 32, idx)                            # 先在 64x64 画布居中
        ico = p.to_image().crop((0, 0, 64, 64)).resize((cell, cell), Image.LANCZOS)
        sheet.paste(ico, (cx, cy))
        d.text((cx + 2, cy + cell + 1), str(idx), fill=200)
    f = OUT / "icons_sheet.png"
    sheet.save(f)
    print(f"图标总览 {len(ids)} 个 -> {f}   （{cols} 列，每格 {cell}px）")
    ids.sort()
    print("  ID 列表: " + " ".join(str(i) for i in ids))


def digi_sample():
    im = Image.new("L", (300, 90), 0)
    d = ImageDraw.Draw(im)
    for k, (s, siz, y) in enumerate((("035", 1, 34), ("PM2.5", 0, 62), ("12:48", 1, 34))):
        p = SSD1325()
        p.digi(150 if k < 2 else 150, y, s, siz)
        im.paste(p.to_image(), (0, 0), p.to_image())
    im2 = Image.new("L", (260, 80), 0)
    for k, (s, siz) in enumerate((("035", 1), ("12:48", 0), ("-12.5", 0))):
        p = SSD1325()
        p.digi(64 + (k % 2) * 130, 22 + (k // 2) * 40, s, siz)
        tile = p.to_image()
        im2.paste(tile, ((k % 2) * 130, (k // 2) * 40), tile)
    f = OUT / "digi_sample.png"
    im2.resize((520, 160), Image.NEAREST).save(f)
    print(f"数码管字样（大号 20x32 / 小号 12x18）-> {f}")


# ============================================================ 方案 A：图标半屏
def badge(p, x, y, icon_id, size=32):
    """把 64x64 图标**隔点取样**成 size x size 再画。

    为什么不用平滑缩放：bmp() 一次只发整块缓冲，固件里要做角标就得自己取子矩形、
    重新按"每行 size/2 字节、高半字节是左像素"打包。这里照这个思路做，
    画质就是真机能做到的（隔点丢细节、锯齿明显 —— 这是真实的代价）。
    """
    q = SSD1325()
    q.icon(32, 32, icon_id)
    dst = q.to_image().resize((size, size), Image.NEAREST)
    buf = bytearray(size * size // 2)
    px = dst.load()
    for row in range(size):
        for c in range(size):
            v = px[c, row] // 17
            i = row * (size // 2) + (c >> 1)
            if c & 1:
                buf[i] = (buf[i] & 0xF0) | v
            else:
                buf[i] = (buf[i] & 0x0F) | (v << 4)
    p.bmp(int(x + size / 2), int(y + size / 2), size, size, buf, True)


def layout_a(pm1=12, pm25=35, pm10=48, co2=580, icon_id=1002):
    """A：右半屏 64x64 图标 + 左半屏 64px 文字。

    取舍：图标最大、一眼看到，但文字只剩 64px（6x8 约 10 字/行），三段就占满一行。
    """
    p = SSD1325()
    p.clear()
    p.icon(96, 32, icon_id)                     # 右半屏：中心 (96,32)
    p.fill(0, 0, 64, 11, C_BAND)                # 左半屏顶部一条灰带当标题底
    p.prt(2, 1, 0, 0x6F, "PM2.5")               # 6x8，灰带上的字用 bg=6 保持底一致
    p.prt(2, 13, 0, C_TXT, "%3d" % pm25)
    p.prt(22, 13, 0, C_DIM, "ug/m3")
    p.prt(2, 28, 0, C_LBL, "PM1.0")
    p.prt(2, 36, 0, C_TXT, "%3d" % pm1)
    p.prt(2, 47, 0, C_LBL, "PM10")
    p.prt(2, 55, 0, C_TXT, "%3d" % pm10)
    return p


# ============================================================ 方案 B：全屏大数字
def layout_b(pm1=12, pm25=35, pm10=48, co2=580, icon_id=None):
    """B：不放图标，整屏给数码管大数字 + 中文标签。

    取舍：可读性最好、远看也清楚；代价是没有任何图形信息。
    """
    p = SSD1325()
    p.clear()
    p.fill(0, 0, W, 16, C_BAND)                 # 状态带整条灰底（扁平化分层）
    p.prt(3, 0, 2, 0x6F, "空气质量")             # 16x16 中文，4 字 = 64px
    p.prt(112, 0, 2, 0x6F, "良")
    p.digi(36, 32, "%3d" % pm25, 1)             # 大号 20x32，" 35" = 60px
    p.prt(2, 20, 0, C_LBL, "PM2.5")
    p.prt(72, 20, 0, C_LBL, "ug/m3")
    p.prt(2, 48, 0, C_LBL, "PM1.0")
    p.prt(42, 48, 0, C_TXT, "%3d" % pm1)
    p.prt(67, 48, 0, C_LBL, "PM10")
    p.prt(107, 48, 0, C_TXT, "%3d" % pm10)
    p.prt(2, 56, 0, C_LBL, "CO2")
    p.prt(32, 56, 0, C_TXT, "%4d" % co2)
    p.prt(62, 56, 0, C_DIM, "ppm")
    return p


def layout_c(pm1=12, pm25=35, pm10=48, co2=580, icon_id=1002):
    """C：大数字为主 + 右上角 32x32 状态角标（隔点取样的图标）。

    取舍：兼顾"远看能读"和"有图形信息"。角标隔点取样会丢细节（锯齿明显），
    但比整屏让给图标划算得多。这也是我倾向的方案。
    """
    p = SSD1325()
    p.clear()
    p.fill(0, 0, W, 16, C_BAND)
    p.prt(3, 0, 2, 0x6F, "空气质量")
    p.prt(112, 0, 2, 0x6F, "良")
    p.digi(34, 32, "%3d" % pm25, 1)
    p.prt(2, 20, 0, C_LBL, "PM2.5")
    p.prt(2, 34, 0, C_DIM, "ug/m3")
    badge(p, 80, 16, icon_id, 32)               # 右上角 32x32 角标：x 80..111, y 16..47
    p.prt(2, 48, 0, C_LBL, "PM1.0")
    p.prt(42, 48, 0, C_TXT, "%3d" % pm1)
    p.prt(67, 48, 0, C_LBL, "PM10")
    p.prt(107, 48, 0, C_TXT, "%3d" % pm10)
    p.prt(2, 56, 0, C_LBL, "CO2")
    p.prt(32, 56, 0, C_TXT, "%4d" % co2)
    p.prt(62, 56, 0, C_DIM, "ppm")
    return p


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    art = None
    if "--art" in sys.argv:
        i = sys.argv.index("--art")
        if i + 1 < len(sys.argv):
            art = sys.argv[i + 1]

    icon_sheet()
    digi_sample()

    for name, fn in (("a", layout_a), ("b", layout_b), ("c", layout_c)):
        p = fn()
        f = OUT / f"layout_{name}.png"
        p.to_image(4).save(f)
        print(f"方案 {name.upper()} -> {f}")
        if art == name:
            print()
            print(p.to_art())

    # 拼一张对比图（放大 3 倍，方便直接看）
    imgs = [Image.open(OUT / f"layout_{n}.png") for n in ("a", "b", "c")]
    cw = max(i.width for i in imgs)
    comp = Image.new("L", (cw + 8, sum(i.height + 8 for i in imgs) + 8), 40)
    y = 8
    for i in imgs:
        comp.paste(i, (8, y))
        y += i.height + 8
    f = OUT / "layouts.png"
    comp.save(f)
    print(f"方案对比 -> {f}")


if __name__ == "__main__":
    main()
