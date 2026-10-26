"""自己画空气质量图标，补上现有天气素材缺的那几档。

为什么要自己画：设备上现成的 233 个图标是**天气桌面摆件**的素材（龙卷风、月相、
雨雪），用来表达空气质量不对路。而"差"的那一端其实已经有合适的了
（1021 口罩 → 1029 防毒面罩 → 9998/9999 警告三角，是一条"防护升级"的链），
缺的只是"好"这一端：清新、健康的意思。网上找 AQI 图标集的授权五花八门，
不如直接画 —— 要什么画什么、可复现、没有授权问题。

输出格式和设备完全一致：64x64 的 4 位灰度点阵，每行 32 字节，高半字节是左边像素，
共 2048 字节，写到 icon/<id>.bin。id 用 3000+ 的号段，避开原有的 100..9999。

用法：
    python tools/make_icons.py            # 生成到 icon/ 并渲一张总览图
    python tools/make_icons.py --list     # 只看会生成哪些
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent      # Pico/
ICON = ROOT / "icon"
OUT = ROOT / "preview" / "out"
S = 64                                              # 图标边长
SS = 4                                              # 超采样倍数（画大再缩，边缘才干净）


def _canvas():
    im = Image.new("L", (S * SS, S * SS), 0)
    return im, ImageDraw.Draw(im)


def _finish(im):
    """缩到 64x64、量化成 16 级灰度、再转成设备的半字节格式。"""
    # 画的时候用超采样，缩的时候用 LANCZOS 得到抗锯齿的中间结果，
    # 正好喂给 4 位灰度的量化 —— 这样圆滑边缘能落到中间灰度上。
    im = im.resize((S, S), Image.LANCZOS)
    buf = bytearray(S * S // 2)
    px = im.load()
    for row in range(S):
        for c in range(S):
            v = (px[c, row] * 15 + 127) // 255          # 0..255 -> 0..15
            i = row * (S // 2) + (c >> 1)
            if c & 1:
                buf[i] = (buf[i] & 0xF0) | v
            else:
                buf[i] = (buf[i] & 0x0F) | (v << 4)
    return bytes(buf)


def leaf(filled=255):
    """一片叶子：45 度斜置的椭圆当叶身 + 叶柄 + 中脉。

    ✗ 走过的弯路：先用"椭圆 + 多边形切右上角"想做出叶尖，切出来成了**禁止标志**
    （圆形加一道斜杠）。斜置椭圆 + 叶柄才读得出是叶子。
    旋转在单独一层上做，然后用 ImageChops.lighter 取最大值合并 —— 这样不用做蒙版。
    """
    from PIL import ImageChops
    import math
    im, d = _canvas()
    k = SS
    layer = Image.new("L", (S * SS, S * SS), 0)
    ImageDraw.Draw(layer).ellipse([21 * k, 2 * k, 43 * k, 56 * k], fill=filled)
    layer = layer.rotate(-45, resample=Image.BICUBIC, center=(32 * k, 32 * k))
    im = ImageChops.lighter(im, layer)
    d = ImageDraw.Draw(im)
    d.line([(14 * k, 54 * k), (24 * k, 44 * k)], fill=filled, width=5 * k)   # 叶柄
    d.line([(16 * k, 52 * k), (44 * k, 20 * k)], fill=0, width=2 * k)        # 中脉
    return _finish(im)


def breeze():
    """'良'：三道气流线（空气流通，比叶子更中性）。"""
    im, d = _canvas()
    k = SS
    for i, (y, w) in enumerate(((18, 34), (32, 42), (46, 26))):
        d.line([((64 - w) // 2 * k, y * k, ), ((64 + w) // 2 * k, y * k)], fill=255, width=4 * k)
        d.arc([(64 + w) // 2 * k - 12 * k, (y - 6) * k, (64 + w) // 2 * k + 12 * k, (y + 6) * k],
              270, 90, fill=255, width=4 * k)
    return _finish(im)


def lungs():
    """肺：气管 + 左右支气管 + 两叶。

    ✗ 第一版气管只有 20px 高、两叶又大又圆，缩小到 64x64 后气管几乎看不见，
    出来是"两个白团加一小竖"。这版把气管拉到 y=30、补上支气管分叉，形状才立得住。
    """
    im, d = _canvas()
    k = SS
    d.line([(32 * k, 3 * k), (32 * k, 30 * k)], fill=255, width=5 * k)      # 气管
    d.line([(32 * k, 30 * k), (18 * k, 42 * k)], fill=255, width=4 * k)     # 左支气管
    d.line([(32 * k, 30 * k), (46 * k, 42 * k)], fill=255, width=4 * k)     # 右支气管
    d.ellipse([4 * k, 30 * k, 30 * k, 62 * k], fill=255)
    d.ellipse([34 * k, 30 * k, 60 * k, 62 * k], fill=255)
    d.polygon([(28 * k, 34 * k), (10 * k, 60 * k), (28 * k, 60 * k)], fill=255)
    d.polygon([(36 * k, 34 * k), (54 * k, 60 * k), (36 * k, 60 * k)], fill=255)
    return _finish(im)


ICONS = (
    (3001, "优-叶子", leaf(255)),
    (3002, "良-气流", breeze()),
    (3004, "呼吸-肺", lungs()),
)


def sheet():
    OUT.mkdir(parents=True, exist_ok=True)
    cols, cell = 4, 96
    im = Image.new("L", (cols * (cell + 8) + 8, cell + 40), 26)
    d = ImageDraw.Draw(im)
    for n, (idx, name, _b) in enumerate(ICONS):
        p = ROOT / "icon" / f"{idx}.bin"
        if not p.exists():
            continue
        raw = p.read_bytes()
        tile = Image.new("L", (S, S), 0)
        px = tile.load()
        for row in range(S):
            for c in range(S):
                b = raw[row * (S // 2) + (c >> 1)]
                px[c, row] = ((b >> 4) if (c & 1) == 0 else (b & 0x0F)) * 17
        im.paste(tile.resize((cell, cell), Image.NEAREST), (8 + n * (cell + 8), 8))
        d.text((8 + n * (cell + 8) + 4, cell + 14), f"{idx} {name}", fill=230)
    f = OUT / "icons_new.png"
    im.save(f)
    print(f"新图标总览 -> {f}")


def main():
    if "--list" in sys.argv:
        for idx, name, _b in ICONS:
            print(f"   {idx}  {name}")
        return
    ICON.mkdir(parents=True, exist_ok=True)
    for idx, name, buf in ICONS:
        p = ICON / f"{idx}.bin"
        p.write_bytes(buf + b"\n")               # 和设备上现有的图标一样带个尾巴字节
        print(f"   写出 {p.name}  {len(buf)} 字节  ({name})")
    sheet()


if __name__ == "__main__":
    main()
