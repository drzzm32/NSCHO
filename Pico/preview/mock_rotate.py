"""按"PM 值轮换 + CO2 单独一行"的定稿思路渲染连拍图。

设计（128x64）：
    y=0..15   状态带 bg=6：左边**轮换的标签**（PM2.5 / PM1.0 / PM10），右边中文等级
    y=16..47  主区 bg=0：**轮换的大数字**（数码管 20x32，正好铺满 32 行）
              右上角 32x32 状态角标（隔点取样，见 mock_layouts.badge）
    y=48..63  CO2 单独一行 bg=1：不参与轮换

⚠️ 两条用血换来的规矩（CH559 那套界面最后定下来的）：
   1. 大数字要**独占** 32 行，标签必须让位（放状态带里），否则 20x32 会压住它；
   2. 文字颜色的**背景半字节必须等于所在区域的底色**：
      灰带(bg=6)上用 0x6F、CO2 行(bg=1)上用 0x1F、暗字用 0x15 —— 否则会抠出黑框。
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ssd1325_sim import SSD1325, ROOT                          # noqa: E402
from mock_layouts import badge                                 # noqa: E402

OUT = ROOT / "preview" / "out"

C_BAND = 6      # 状态带底色
C_CO2 = 1       # CO2 行的底色（比主区亮一点，把两块分开）
C_HI = 0x0F     # 主区数值：纯白，背景 0
C_LBL = 0x08    # 主区标签：暗灰
C_DIM = 0x05    # 更暗的次要信息


def frame(pm1, pm25, pm10, co2, which, icon_id=1002, grade="良"):
    """which: 0=PM2.5 / 1=PM1.0 / 2=PM10 —— 主区轮换到哪一个。"""
    val = (pm25, pm1, pm10)[which]
    name = ("PM2.5", "PM1.0", "PM10")[which]
    p = SSD1325()
    p.clear()
    # ---- 状态带：整条灰底做分层（扁平化，不画边框）；标签放这里，给大数字让出整块主区
    p.fill(0, 0, 128, 16, C_BAND)
    p.prt(3, 4, 0, 0x6F, name)                  # 6x8 标签，背景=6 与灰带一致
    p.prt(112, 0, 2, 0x6F, grade)               # 16x16 中文等级，背景=6
    # ---- 主区：大数字独占 32 行（y 16..47），右边留 32px 给角标
    p.digi(42, 32, "%3d" % val, 1)              # 大号 20x32：3 字 = 60px，中心 x=42 → x 12..72
    p.prt(76, 20, 0, C_DIM, "ug/")              # 单位拆两行塞进角标左边
    p.prt(76, 28, 0, C_DIM, "m3")
    badge(p, 80, 16, icon_id, 32)               # 右上角 32x32 角标：x 80..111, y 16..47
    # ---- CO2 单独一行：固定不轮换，底色 1，文字背景跟着用 1
    p.fill(4, 48, 124, 16, C_CO2)
    p.prt(7, 52, 0, 0x15, "CO2")                # fg=5 暗、bg=1
    p.prt(37, 52, 0, 0x1F, "%4d" % co2)         # fg=15 亮、bg=1
    p.prt(69, 52, 0, 0x15, "ppm")
    return p


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    vals = dict(pm1=12, pm25=35, pm10=48, co2=580)
    imgs = [frame(which=w, **vals).to_image() for w in range(3)]
    # 再补一帧污染态：换等级字、换角标（说明轮换之外的状态表达）
    imgs.append(frame(which=0, pm1=41, pm25=118, pm10=160, co2=1420,
                      grade="中度", icon_id=9998).to_image())

    sc, pad = 4, 6
    comp = Image.new("L", (128 * sc + pad * 2, (64 * sc + 16) * len(imgs) + pad), 40)
    for n, im in enumerate(imgs):
        comp.paste(im.resize((128 * sc, 64 * sc), Image.NEAREST), (pad, pad + n * (64 * sc + 16)))
    f = OUT / "rotate_states.png"
    comp.save(f)
    for n, im in enumerate(imgs):
        im.resize((128 * 3, 64 * 3), Image.NEAREST).save(OUT / f"rotate_{n}.png")
    print(f"轮换连拍（PM2.5 / PM1.0 / PM10 / 污染态）-> {f}")
    print("单帧: preview/out/rotate_0..3.png")


if __name__ == "__main__":
    main()
