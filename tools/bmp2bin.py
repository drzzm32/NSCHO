"""BMP -> SSD1351 开机图（RGB565 大端、行优先）。

SSD1351.bmpf() 读的是**裸 RGB565 数据**：每像素 2 字节、高字节在前、逐行从上到下。
BMP 文件则是：带 54 字节头、每像素 3 字节 BGR、**行序自下而上**（高度为正时）。
两者格式不通，所以需要这个转换。

用法：
    python tools/bmp2bin.py bak/boot.bmp font/boot.bin
    python tools/bmp2bin.py input.bmp output.bin --w 80 --h 80

不加 --w/--h 时按 BMP 里的原始尺寸转换；加了就做双线性缩放（等比拉伸到目标框）。
"""

import argparse
import struct
import sys
from pathlib import Path

from PIL import Image


def bmp_to_rgb565(src: Path, dst: Path, w: int | None = None, h: int | None = None) -> tuple[int, int]:
    im = Image.open(src)

    # BMP 里的行序是自下而上的，Image.open 已经按 BMP 元数据翻正了，
    # 但用 struct 手读时要自己翻 —— 这里交给 PIL，省去踩坑。
    if im.mode != "RGB":
        # 带调色板的 BMP 也走这条路径统一成 RGB
        im = im.convert("RGB")

    if w and h and (im.width != w or im.height != h):
        im = im.resize((w, h), Image.LANCZOS)

    w, h = im.size
    px = im.load()

    out = bytearray(w * h * 2)
    i = 0
    for y in range(h):
        for x in range(w):
            r, g, b = px[x, y]
            # RGB565：高 5 位红、中 6 位绿、低 5 位蓝
            c = ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)
            out[i] = (c >> 8) & 0xFF        # 大端：高字节先发
            out[i + 1] = c & 0xFF
            i += 2

    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(bytes(out))
    return w, h


def main() -> int:
    ap = argparse.ArgumentParser(description="BMP -> SSD1351 RGB565 裸数据")
    ap.add_argument("src", type=Path)
    ap.add_argument("dst", type=Path)
    ap.add_argument("--w", type=int, default=None, help="目标宽（默认用原图）")
    ap.add_argument("--h", type=int, default=None, help="目标高（默认用原图）")
    a = ap.parse_args()

    if not a.src.exists():
        print(f"源文件不存在: {a.src}", file=sys.stderr)
        return 1

    w, h = bmp_to_rgb565(a.src, a.dst, a.w, a.h)
    size = a.dst.stat().st_size
    expect = w * h * 2
    print(f"{a.src.name} -> {a.dst}")
    print(f"  {w}x{h} RGB565 大端 = {size} 字节" + ("" if size == expect else f"（应为 {expect}）"))
    return 0 if size == expect else 1


if __name__ == "__main__":
    raise SystemExit(main())
