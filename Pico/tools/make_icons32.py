"""生成 Pico 状态角标：64x64 源图 -> 32x32 字模，外加程序化绘制的"严"图标。

为什么要预生成 32x32
--------------------
真机上 badge() 原来是从 64x64 里**隔点取样**（每 2 像素取 1 个）。这套图标是
线条型素材，隔点会把细笔画整根抽掉 —— 肺的细支气管、三角的边框都在这一步消失，
屏上看着就是"一团碎片"。预先做成 32x32 后，屏上直接整块 bmp，既不丢细节也省一次
逐像素重打包。

降采样用 **max 池化**（2x2 取最大值）而不是平均：
  * 平均会把 1 像素宽的笔画稀释成 1/4 亮度，在 4 位灰度屏上几乎看不见
  * max 保留笔画，代价是整体偏粗 —— 但角标只有 32px，宁可粗也不可断

"严" 档原来和 "重" 共用 9998（两张图完全一样，屏上区分不出来），
这里用代码画一个骷髅补上。

用法：
    python tools/make_icons32.py            # 读 tools/icon_src64，写 icon/
    python tools/make_icons32.py --preview  # 另外输出预览图到 preview/out/
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "tools" / "icon_src64"
DST = ROOT / "icon"
PREVIEW = ROOT / "preview" / "out"

SRC_SIZE = 64
DST_SIZE = 32

# 分档 -> 图标 id（语义从"呼吸顺畅"递进到"严重污染"）
# 角标按**档位顺序编号**：0 = 最好（优），5 = 最差（严）。
# 文件名就是档位序号，ui.py 的 GRADES 直接按下标取图，不再维护
# "素材 id -> 语义" 的映射表（原来 1029/3001/3100/9998 这种 id 看不出含义）。
ICONS = (
    # (序号, 等级, 画法,     64x64 源图 id)
    (0, "优", "flower", None),
    (1, "良", "pool",   "3001"),   # 叶子
    (2, "轻", "pool",   "3002"),   # 气流
    (3, "中", "pool",   "1029"),   # 口罩
    (4, "重", "pool",   "9998"),   # 警告三角
    (5, "严", "skull",  None),     # 骷髅
)


# ---------------------------------------------------------------- 4 位灰度读写
def read64(path: Path) -> list[list[int]]:
    """读 64x64 4 位灰度：每字节 2 像素、高半字节是左边的像素、行优先。"""
    data = path.read_bytes()
    need = SRC_SIZE * SRC_SIZE // 2
    if len(data) < need:
        raise ValueError(f"{path.name}: 只有 {len(data)} 字节，至少要 {need}")
    grid = [[0] * SRC_SIZE for _ in range(SRC_SIZE)]
    for y in range(SRC_SIZE):
        for x in range(SRC_SIZE):
            b = data[y * (SRC_SIZE // 2) + (x >> 1)]
            grid[y][x] = (b >> 4) if (x & 1) == 0 else (b & 0x0F)
    return grid


def write32(grid: list[list[int]], path: Path) -> int:
    out = bytearray(DST_SIZE * DST_SIZE // 2)
    for y in range(DST_SIZE):
        for x in range(DST_SIZE):
            v = grid[y][x] & 0x0F
            j = y * (DST_SIZE // 2) + (x >> 1)
            if x & 1:
                out[j] = (out[j] & 0xF0) | v
            else:
                out[j] = (out[j] & 0x0F) | (v << 4)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(out))
    return len(out)


# ---------------------------------------------------------------- 降采样
def pool_max(grid: list[list[int]]) -> list[list[int]]:
    """2x2 max 池化：保留细笔画。"""
    out = [[0] * DST_SIZE for _ in range(DST_SIZE)]
    for y in range(DST_SIZE):
        for x in range(DST_SIZE):
            a = grid[y * 2][x * 2]
            b = grid[y * 2][x * 2 + 1]
            c = grid[y * 2 + 1][x * 2]
            d = grid[y * 2 + 1][x * 2 + 1]
            out[y][x] = max(a, b, c, d)
    return out


# ---------------------------------------------------------------- 骷髅
def draw_flower() -> list[list[int]]:
    """程序化画 32x32 花朵：五片互不相连的花瓣 + 挖空花心 + 短茎。

    选花朵而不是肺，是因为"优"这一档要表达"空气好、能放心呼吸"，
    花朵的语义比内脏器官直观，而且和旁边"良=叶子"同属植物图形，视觉连贯。

    参数是按"花瓣之间留天然空隙"选的：相邻花瓣中心距 = 2*8.2*sin(36) = 9.6，
    花瓣直径 8.4，所以每两片之间空 1.2 像素 —— 不需要再另外挖缝。
    挖缝那版试过，5 片会被切成交叉形，反而更像 clover。
    """
    g = [[0] * DST_SIZE for _ in range(DST_SIZE)]
    INK = 15
    BG = 0

    cx, cy = 15.5, 13.0
    for k in range(5):
        a = math.radians(90 + k * 72)
        px = cx + 8.2 * math.cos(a)
        py = cy - 8.2 * math.sin(a)
        for y in range(DST_SIZE):
            for x in range(DST_SIZE):
                if (x - px) ** 2 + (y - py) ** 2 <= 4.2 ** 2:
                    g[y][x] = INK

    # 花心挖空，和花瓣之间留出一圈缝
    for y in range(DST_SIZE):
        for x in range(DST_SIZE):
            if (x - cx) ** 2 + (y - cy) ** 2 <= 2.8 ** 2:
                g[y][x] = BG

    # 短茎（花朵下方，露到画面底部）
    for y in range(25, DST_SIZE):
        for x in (15, 16):
            g[y][x] = INK

    return g


def draw_skull() -> list[list[int]]:
    """程序化画一个 32x32 骷髅：头骨 + 两个眼窝 + 鼻腔 + 牙齿。"""
    g = [[0] * DST_SIZE for _ in range(DST_SIZE)]
    INK = 15
    BG = 0

    cx = 15.5
    # 头骨：上半是圆，下半是方下巴
    for y in range(DST_SIZE):
        for x in range(DST_SIZE):
            dx = x - cx
            if y < 22:
                if dx * dx + (y - 13) * (y - 13) <= 12.5 * 12.5:
                    g[y][x] = INK
            else:
                # 下颌：两侧收窄
                half = 9 - (y - 22) // 3
                if -half <= dx <= half and y <= 27:
                    g[y][x] = INK

    # 眼窝：两个圆挖空
    for (ex, ey, r) in ((10.5, 14.0, 3.6), (20.5, 14.0, 3.6)):
        for y in range(DST_SIZE):
            for x in range(DST_SIZE):
                if (x - ex) ** 2 + (y - ey) ** 2 <= r * r:
                    g[y][x] = BG

    # 鼻腔：倒三角
    for y in range(17, 22):
        half = (y - 17) // 2
        for x in range(int(cx) - half, int(cx) + half + 1):
            if 0 <= x < DST_SIZE:
                g[y][x] = BG

    # 牙齿：下颌上挖出 2 条竖缝
    for x in (13, 18):
        for y in range(23, 28):
            g[y][x] = BG

    return g


# ---------------------------------------------------------------- 入口
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", action="store_true")
    a = ap.parse_args()

    DST.mkdir(parents=True, exist_ok=True)
    made = []

    for idx, grade, how, src_id in ICONS:
        if how == "flower":
            grid = draw_flower()
            note = "程序化绘制（花朵）"
        elif how == "skull":
            grid = draw_skull()
            note = "程序化绘制（骷髅）"
        elif how == "pool":
            src = SRC / f"{src_id}.bin"
            if not src.exists():
                print(f"  跳过 {idx}（{grade}）：源图 {src_id}.bin 缺失")
                continue
            grid = pool_max(read64(src))
            note = f"64->32 max 池化（源图 {src_id}）"
        else:
            continue
        n = write32(grid, DST / f"{idx}.bin")
        made.append((grade, idx, grid, n))
        print(f"  {idx}  {grade}  {idx}.bin  {n} 字节  ({note})")

    if a.preview:
        PREVIEW.mkdir(parents=True, exist_ok=True)
        try:
            from PIL import Image, ImageDraw
        except ImportError:
            print("  没装 Pillow，跳过预览")
            return 0
        sc = 5
        w = DST_SIZE * sc
        comp = Image.new("RGB", (w * len(made) + 8 * (len(made) + 1), w + 30), (18, 18, 18))
        d = ImageDraw.Draw(comp)
        for i, (grade, icon_id, grid, _) in enumerate(made):
            im = Image.new("L", (DST_SIZE, DST_SIZE), 0)
            px = im.load()
            for y in range(DST_SIZE):
                for x in range(DST_SIZE):
                    px[x, y] = int(grid[y][x] * 255 / 15)
            comp.paste(im.convert("RGB").resize((w, w), Image.NEAREST), (8 + i * (w + 8), 26))
            d.text((8 + i * (w + 8) + 2, 8), str(icon_id), fill=(230, 230, 230))
        out = PREVIEW / "icons32.png"
        comp.save(out)
        print(f"  预览 -> {out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
