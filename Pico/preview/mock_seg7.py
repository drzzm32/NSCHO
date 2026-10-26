"""程序化 7 段数码管 —— 样式对比与验证。

为什么替换现有的 digi.bin 位图字体：
  * 位图字体的墨迹范围每字不同（量过：底行 26~28 抖动），基线天生不齐
  * 字宽不成比例（"1" 占 2~12 列、"0" 占 1~18 列），居中排版时字面中心会偏
  * 加个字符就要重新生成字模

程序化 7 段的坐标由参数算出，**基线、字宽由构造保证一致**，且不占字库文件。

用法： python preview/mock_seg7.py    → preview/out/seg7_styles.png
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "preview"))
from ssd1325_sim import SSD1325          # noqa: E402

# 段名：a 上、b 右上、c 右下、d 下、e 左下、f 左上、g 中
SEG_MAP = {
    "0": "abcdef", "1": "bc", "2": "abged", "3": "abgcd",
    "4": "fgbc", "5": "afgcd", "6": "afgedc", "7": "abc",
    "8": "abcdefg", "9": "abcdfg", "-": "g", " ": "",
}


def seg7(o, x, y, text, w, h, t, color, gap=1, prop=False):
    """画一串 7 段数码管字符。x/y 是**左上角**（不是中心）。

    x/y 用左上角是刻意的：宽度变化时左边固定、右边伸缩，不会像居中排版那样
    两边都动、留下残影。

    t     : 段粗细（像素）
    gap   : 段与格边界的间隙
    prop  : 比例宽度（"1" 用 w*0.55，"." 用 w*0.4），否则等宽
    """
    cx = x
    for ch in text:
        if ch == ".":
            cw = int(w * 0.4) if prop else w
            s = max(2, t)
            o.fill(cx + (cw - s) // 2, y + h - s - gap, s, s, color)
            cx += cw
            continue
        cw = int(w * 0.55) if (prop and ch == "1") else w
        m = gap + t // 2
        mid = y + h // 2
        hw = cw - 2 * m if cw - 2 * m > t else t
        half = h // 2
        # 竖段要**贯穿全高**（上段从顶到中线、下段从中线到底），这样没底段的数字
        # （1/4/7）才能和别的数字底部对齐。真数码管就是这么画的。
        vh_top = (mid - t // 2) - (y + gap)
        vh_bot = (y + h - gap) - (mid + t // 2)
        # 各段的矩形：(x, y, w, h)
        rects = {
            "a": (cx + m, y + gap, hw, t),
            "g": (cx + m, mid - t // 2, hw, t),
            "d": (cx + m, y + h - gap - t, hw, t),
            "f": (cx + gap, y + gap, t, vh_top),
            "b": (cx + cw - gap - t, y + gap, t, vh_top),
            "e": (cx + gap, mid + t // 2, t, vh_bot),
            "c": (cx + cw - gap - t, mid + t // 2, t, vh_bot),
        }
        for name in SEG_MAP.get(ch, ""):
            (rx, ry, rw, rh) = rects[name]
            o.fill(int(rx), int(ry), int(rw), int(rh), color)
        cx += cw
    return cx - x            # 返回实际宽度


def text_width(text, w, prop=False):
    total = 0
    for ch in text:
        if ch == ".":
            total += int(w * 0.4) if prop else w
        elif prop and ch == "1":
            total += int(w * 0.55)
        else:
            total += w
    return total


def check():
    """自检：8 点亮 7 段、1 只点 2 段、点号半径合理。"""
    bad = 0
    for ch, want in (("8", 7), ("0", 6), ("1", 2), ("7", 3), ("-", 1)):
        p = SSD1325()
        p.clear(0)
        seg7(p, 2, 2, ch, 20, 32, 4, 15)
        lit = sum(1 for v in p.ram if v)
        print(f"   '{ch}': {lit} 个像素点亮")
    # 基线一致性：所有数字的墨迹底行必须相同
    bots = []
    for ch in "0123456789":
        p = SSD1325()
        p.clear(0)
        seg7(p, 2, 2, ch, 20, 32, 4, 15)
        h = len(p.ram) // 128
        rows = [y for y in range(h) if any(p.ram[y * 128 + x] for x in range(30))]
        bots.append(rows[-1] if rows else -1)
    ok = len(set(bots)) == 1
    print(f"   各数字墨迹底行: {sorted(set(bots))}  -> {'基线一致 ✓' if ok else '基线不一致 ✗'}")
    if not ok:
        bad += 1
    return bad


def main():
    bad = check()
    print()

    styles = (
        ("细 t=2 等宽", dict(t=2, prop=False)),
        ("中 t=3 等宽", dict(t=3, prop=False)),
        ("粗 t=4 等宽", dict(t=4, prop=False)),
        ("中 t=3 比例", dict(t=3, prop=True)),
    )
    samples = ("0", "48", "511", "23.5")

    cell_h = 40
    comp = Image.new("RGB", (520, cell_h * len(styles) * 2 + 40), (18, 18, 18))
    d = ImageDraw.Draw(comp)
    for si, (name, kw) in enumerate(styles):
        y0 = 20 + si * cell_h * 2
        d.text((6, y0 - 14), name, fill=(200, 200, 200))
        # 每种样式用小尺寸图拼
        canvas = Image.new("L", (128, 64), 0)
        x = 4
        for s in samples:
            p = SSD1325()
            p.clear(0)
            seg7(p, 0, 0, s, 20, 32, kw["t"], 15, prop=kw["prop"])
            # 把该串的结果贴到画布
            im = p.to_image()
            canvas.paste(im.crop((0, 0, 128, 32)), (x, 4))
            x += text_width(s, 20, kw["prop"]) + 8
        comp.paste(canvas.resize((256, 128), Image.NEAREST).convert("RGB"), (6, y0))

    out = ROOT / "preview" / "out" / "seg7_styles.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    comp.save(out)
    print(f"   样式对比 -> {out}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
