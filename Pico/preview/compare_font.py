"""12x12 子集 vs 现在的 16x16 —— 先把这 12 个字摆出来比一比。

左边是设备现在用的 utf.bin（16x16、按码位直接索引、2 MB），
右边是新生成的 font/utf12.bin（12x12 子集、12 字、288 字节、要查表）。
**两组都按真实像素大小 1:1 画一遍**，再放大 6 倍画一遍 —— 12x12 到底够不够看，
得在真实尺寸下判断，光看放大图会骗人。

用法： python preview/compare_font.py
"""

from __future__ import annotations

import re
import struct
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import ui                                   # noqa: E402

OUT = ROOT / "preview" / "out"


def glyph_from_blob(blob: bytes, off: int, w: int, h: int) -> Image.Image:
    """把 1 位点阵按设备布局解出来：byte[w*(row//8)+col] 的 bit[row%8]。"""
    im = Image.new("L", (w, h), 0)
    px = im.load()
    for row in range(h):
        for col in range(w):
            f = w * (row // 8) + col
            if off + f < len(blob) and (blob[off + f] >> (row % 8)) & 1:
                px[col, row] = 255
    return im


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    chars = sorted(set(ui.ZH_CHARS), key=ord)
    old = (ROOT / "font" / "utf.bin").read_bytes()
    new = (ROOT / "font" / "utf12.bin").read_bytes()
    tab = (ROOT / "font" / "utf12.tab").read_bytes()
    codes = [struct.unpack(">H", tab[i:i + 2])[0] for i in range(0, len(tab), 2)]
    idx = {c: n for n, c in enumerate(codes)}

    Z = 6                                   # 放大倍数
    CELL = (16 + 12) * Z + 40               # 每行：16x16 + 间距 + 12x12
    im = Image.new("L", (CELL + 20, (16 * Z + 10) * len(chars) + 44), 30)
    d = ImageDraw.Draw(im)
    d.text((8, 6), "左：现在 utf.bin 16x16 (2 MB)      右：新 utf12.bin 12x12 (288 B)",
           fill=235)
    for n, ch in enumerate(chars):
        y = 24 + n * (16 * Z + 10)
        g16 = glyph_from_blob(old, ord(ch) * 32, 16, 16)
        n12 = idx.get(ord(ch))
        g12 = glyph_from_blob(new, n12 * 24, 12, 12) if n12 is not None else None
        im.paste(g16.resize((16 * Z, 16 * Z), Image.NEAREST), (8, y))
        if g12 is not None:
            im.paste(g12.resize((12 * Z, 12 * Z), Image.NEAREST), (16 * Z + 32, y))
        d.text((8 + 16 * Z + 8, y + 16 * Z // 2 - 4),
               f"{ch} U+{ord(ch):04X}", fill=220)
    f = OUT / "font_compare.png"
    im.save(f)
    print(f"对照图 -> {f}")
    print(f"  12 字（ui.ZH_CHARS）：{ui.ZH_CHARS}")

    # 再出一张"真实尺寸"的，别让放大图骗人
    im1 = Image.new("L", (200, 24), 0)
    d1 = ImageDraw.Draw(im1)
    x = 4
    for ch in chars:
        n12 = idx.get(ord(ch))
        if n12 is None:
            continue
        im1.paste(glyph_from_blob(new, n12 * 24, 12, 12), (x, 6))
        x += 13
    d1.text((4, 0), "12x12 真实尺寸（1:1）", fill=200)
    x = 4
    im2 = Image.new("L", (200, 24), 0)
    d2 = ImageDraw.Draw(im2)
    for ch in chars[:14]:
        im2.paste(glyph_from_blob(old, ord(ch) * 32, 16, 16), (x, 4))
        x += 17
    d2.text((4, 0), "16x16 真实尺寸（1:1）", fill=200)
    im3 = Image.new("L", (200, 52), 0)
    im3.paste(im1, (0, 0))
    im3.paste(im2, (0, 26))
    im3.resize((600, 156), Image.NEAREST).save(OUT / "font_compare_1to1.png")
    print("真实尺寸对照 -> preview/out/font_compare_1to1.png")


if __name__ == "__main__":
    main()
