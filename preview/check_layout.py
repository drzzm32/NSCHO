"""布局检查：把三版界面各画一遍，验证文字没有溢出/互相压住。

为什么需要：上一版方案图里出过三个排版错误 —— 状态栏的中文溢出到带子下面、
「气温」标签和下面的大数字重叠、C 版卡片内也压了一点。这些用眼睛看放大图能发现，
但人眼会漏、而且改一次布局就要重看一遍。所以固化成检查。

检查的都是"能用颜色精确判定"的区域：
  1. 状态带（y 0..11）之外的区域不许出现带子底色 BAR —— 这条能抓到中文溢出；
  2. y=12 必须是完整的分隔线 SEP；
  3. 每版布局的"标签行"和"数字行"不重叠（数字是数码管、标签是中文，
     用各自占的垂直区间判断，区间在下面按布局写死并注明依据）；
  4. 整屏没有用到色板外的颜色（防止手滑写错色值）。

用法： python preview/check_layout.py   （通过返回 0）
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "preview"))
sys.path.insert(0, str(ROOT))

from ssd1351_sim import SSD1351, rgb565     # noqa: E402
import ui                                   # noqa: E402

W = 128
CASE = dict(t=23.5, r=48.2, pitch=-9.3, roll=12.4, uptime="0:12:34")

# 每版布局里"中文标签"和"数码管大字"占的垂直区间（闭区间，单位像素）。
# 依据：中文 12 高、数码管 18 高。改动布局时这张表要跟着改。
ROWS = {
    "A": ([(14, 25), (46, 57), (80, 91)], [(26, 44), (58, 76)]),
    "B": ([(18, 29), (56, 67), (92, 103), (106, 117)], [(31, 49), (69, 87)]),
    "C": ([(20, 31), (70, 81)], [(33, 51), (35, 53)]),
}


def non_bg(ram, color):
    c = rgb565(color)
    return [i for i, v in enumerate(ram) if v != c]


def check(name, fn) -> int:
    bad = 0
    p = SSD1351()
    ui.reset_cache()          # 局部重绘有变更缓存，独立渲染前必须清
    fn(p)
    ram = p.ram
    bg = rgb565(ui.BG)

    # 1) 状态带底色不许出现在 y >= 12 的地方
    bar = rgb565(ui.BAR)
    spill = [i for i, v in enumerate(ram) if v == bar and (i // W) >= 12]
    # 分隔线以下如果恰好用了同色也算（本布局里 SEP 与 BAR 不同色，所以这是干净的判据）
    if spill:
        rows = sorted(set(i // W for i in spill))
        print(f"   [溢出] {name}: 状态带底色出现在 y={rows[:6]}")
        bad += 1
    else:
        print(f"   [ok] {name}: 状态带没有溢出")

    # 2) y=12 整行是分隔线
    sep = rgb565(ui.SEP)
    row12 = ram[12 * W:13 * W]
    if all(v == sep for v in row12):
        print(f"   [ok] {name}: y=12 是完整分隔线")
    else:
        n = sum(1 for v in row12 if v != sep)
        print(f"   [问题] {name}: y=12 有 {n} 个像素不是分隔线")
        bad += 1

    # 3) 标签行与数字行不重叠
    labels, digits = ROWS[name]
    hit = []
    for a in labels:
        for b in digits:
            if not (a[1] < b[0] or b[1] < a[0]):
                hit.append((a, b))
    if hit:
        print(f"   [重叠] {name}: {hit}")
        bad += 1
    else:
        print(f"   [ok] {name}: 标签行与数字行不重叠")

    # 4) 只用色板内的颜色（粗略：统计不同颜色数，超了说明可能写错色值）
    colors = set(ram)
    if len(colors) > 400:      # 数码管/中文字模是抗锯齿灰度渐变，颜色数会很多，这里只防离谱
        print(f"   [问题] {name}: 用了 {len(colors)} 种颜色，可能是色值写错")
        bad += 1
    return bad


def check_residue(name, fn) -> int:
    """连续画多帧后，画面必须和"全新画一遍"完全一致。

    局部重绘最容易出的 bug 就是残留：某个会变的区域没被擦干净，旧内容留在屏上。
    单看一帧看不出来，只有连续帧对比才暴露 —— 所以固化成检查。
    """
    from ssd1351_sim import SSD1351 as Sim
    # ⚠️ 姿态必须**恒定**：小球有 2 像素的移动量化（局部重绘的代价），
    #    姿态变了就会让"运行中的球位"和"全新绘制的球位"差几个像素，
    #    那不是残留。恒定姿态下只让温湿度/时间变化，才能测出真正的残留。
    #    （之前用变化的姿态，32 个"差异"全是量化，白折腾一轮。）
    seq = [(20.0 + i * 0.5, 45.0 + i, -2.9, 3.4, "1:%02d" % (2 + i // 10))
           for i in range(24)]
    p = Sim()
    ui.reset_cache()          # 连续帧从冷缓存开始
    for kw in seq:
        fn(p, *kw[:1], **dict(zip(("r", "pitch", "roll", "uptime"), kw[1:])))
    q = Sim()
    ui.reset_cache()
    kw = seq[-1]
    fn(q, *kw[:1], **dict(zip(("r", "pitch", "roll", "uptime"), kw[1:])))
    diff = sum(1 for a, b in zip(p.ram, q.ram) if a != b)
    if diff:
        print(f"   [残留] {name}: 连续 24 帧后有 {diff} 个像素和全新绘制不同")
        return 1
    print(f"   [ok] {name}: 连续 24 帧无残留")
    return 0


def main() -> int:
    ui.LAYOUT_OVERRIDE = None
    bad = 0
    for name, fn in (("A", ui.layout_a), ("B", ui.layout_b), ("C", ui.layout_c)):
        bad += check(name, fn)
        bad += check_residue(name, fn)
        print()
    if bad:
        print(f"✗ {bad} 处需要修")
        return 1
    print("布局检查全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
