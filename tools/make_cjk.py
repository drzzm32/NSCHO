"""生成 12x12 中文字集（font/utf12.bin + font/utf12.tab）。

来源字体：fusion-pixel-12px（和 RP2040 空气质量终端用的是同一档，字形风格统一）。
打包格式沿用 RP2040 那边：**每行 w 个字节（列优先）、每 8 行一段**，
即 byte[w*(row//8) + col] 的 bit[row%8]；12x12 → 12 列 × 2 段 = 24 字节/字。
配套一张**升序码位表**（大端 uint16），因为子集不能再用 "码位 × 字宽" 直接算偏移。

⚠️ 字符集**显式声明**，不扫源码。RP2040 那次扫源码时正则不剥注释，把 docstring
   里的中文全抓进去了，字集从 12 字膨胀到 285 字、字体从 288 字节涨到 6840 字节。
   显式声明既准确，又顺便当成"界面文案清单"——**改界面用字必须同步改这里**。

用法： python tools/make_cjk.py [--list]
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
TTF = Path(r"E:\Works\NTP_PRO_II\tools\fusion-pixel-12px-monospaced-zh_hans.ms.bitmap.ttf")

# 界面用字**从 ui.py 读**，单一来源 —— 两边各写一份迟早会不一致。
# 这也是 RP2040 那次的教训：那边扫源码抓字集，把注释里的中文全抓进去了。
import sys as _sys
_sys.path.insert(0, str(ROOT))
import ui as _ui                              # noqa: E402
ZH_CHARS = _ui.ZH_CHARS

W = H = 12
SEGS = (H + 7) // 8      # 12 -> 2


def main() -> int:
    chars = sorted(set(ZH_CHARS), key=ord)
    if "--list" in sys.argv:
        print(f"{len(chars)} 字：{''.join(chars)}")
        return 0

    font = ImageFont.truetype(str(TTF), H)
    blob, table, blank = bytearray(), [], []
    for ch in chars:
        im = Image.new("L", (W, H), 0)
        ImageDraw.Draw(im).text((0, 0), ch, font=font, fill=255)
        px = im.load()
        g = bytearray(W * SEGS)
        ink = 0
        for seg in range(SEGS):
            for col in range(W):
                b = 0
                for r in range(8):
                    row = seg * 8 + r
                    if row < H and px[col, row] > 127:
                        b |= 1 << r
                        ink += 1
                g[W * seg + col] = b
        if not ink:
            blank.append(ch)
        table.append(ord(ch))
        blob += g

    out = ROOT / "font"
    (out / "utf12.bin").write_bytes(bytes(blob))
    (out / "utf12.tab").write_bytes(b"".join(struct.pack(">H", c) for c in table))

    print(f"字集（{ROOT.name} 的 ZH_CHARS）：{len(chars)} 字")
    print(f"   {''.join(chars)}")
    if blank:
        print(f"   ⚠️ 这些字渲染出来是空白（字体里没有？）：{''.join(blank)}")
    print(f"   font/utf12.bin  {len(blob)} 字节（每字 {W * SEGS} = {W} 列 × {SEGS} 段）")
    print(f"   font/utf12.tab  {len(table) * 2} 字节（升序码位，大端 uint16）")

    # 顺便在彩屏上调色，导一张实际大小的样张
    sys.path.insert(0, str(ROOT / "preview"))
    from ssd1351_sim import SSD1351       # noqa: E402
    p = SSD1351()
    p.clear(0x101820)
    p.fill(0, 0, 128, 14, 0x1E88E5)
    p.prt(3, 3, 0, 0xFFFFFF, 0x1E88E5, "12x12 CJK subset")
    for i, ch in enumerate(chars):
        cx = (i % 8) * 16
        cy = 20 + (i // 8) * 20
        # 用 bwp 直接画一个 12x12 字形（临时按 int(h/8) 会砍掉后 4 行，
        # 所以这里按 2 段手动调两次，只为了看字形，不代表最终驱动路径）
        idx = table.index(ord(ch))
        g = blob[idx * W * SEGS:(idx + 1) * W * SEGS]
        p.prt(cx, cy, 0, 0x808080, 0x101820, ch if False else " ")
        # 直接铺两段
        import ssd1351_sim as S
        buff = [0] * (W * 8 * 2)
        fore, back = S.rgb565(0xFFFFFF), S.rgb565(0x101820)
        for seg in range(SEGS):
            hh = min(8, H - seg * 8)
            for col in range(W):
                f = W * seg + col
                for row in range(8):
                    pp = int(W * row + col)
                    c = fore if (g[f] & (1 << row)) else back
                    buff[pp * 2] = (c >> 8) & 0xFF
                    buff[pp * 2 + 1] = c & 0xFF
            p.bmp(cx, cy + seg * 8, W, hh, bytes(buff))
    f = ROOT / "preview" / "out" / "cjk12_sample.png"
    f.parent.mkdir(parents=True, exist_ok=True)
    p.to_image(3).save(f)
    print(f"   样张 -> {f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
