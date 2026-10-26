"""把 ui.py 的各个状态渲染成 PNG —— 这就是"把界面拆成 ui.py"换来的东西：
不用拷进设备、不用复位等开机，在电脑上直接出图。

覆盖：六个等级档（优/良/轻/中/重/严）、PM 轮换的三个位置、甲醛接上传感器之后的样子、
以及**开机画面**（之前只写了没验过）。

用法（在 Pico 目录下）：
    python preview/render_ui.py
输出：
    preview/out/ui_all_states.png   一张总图
    preview/out/ui_0..N.png         逐张放大 3 倍
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "preview"))
sys.path.insert(0, str(ROOT))

from ssd1325_sim import SSD1325        # noqa: E402
import ui                              # noqa: E402

ICO = str(ROOT / "icon")
OUT = ROOT / "preview" / "out"

# 读数按国标分档挑的：35/75/115/150/250 是 PM2.5 24h 均值的二级/三级档
CASES = (
    ("优 · PM2.5=35", dict(pm1=12, pm25=35, pm10=48, co2=580), 0),
    ("优 · 轮到 PM1.0", dict(pm1=12, pm25=35, pm10=48, co2=580), 1),
    ("优 · 轮到 PM10", dict(pm1=12, pm25=35, pm10=48, co2=580), 2),
    ("良 · PM2.5=68", dict(pm1=30, pm25=68, pm10=95, co2=760), 0),
    ("轻 · PM2.5=98", dict(pm1=45, pm25=98, pm10=130, co2=980), 0),
    ("中 · PM2.5=132", dict(pm1=52, pm25=132, pm10=170, co2=1420), 0),
    ("重 · PM2.5=210", dict(pm1=80, pm25=210, pm10=260, co2=2100), 0),
    ("严 · PM2.5=320", dict(pm1=120, pm25=320, pm10=400, co2=3500), 0),
    ("甲醛接上传感器后", dict(pm1=12, pm25=35, pm10=48, co2=580, hcho="0.06"), 0),
)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    frames = []
    for name, d, which in CASES:
        p = SSD1325()
        ui.draw(p, d, which, prefix=ICO)
        frames.append((name, p.to_image()))
    p = SSD1325()
    ui.draw_boot(p, "BOOTING")
    frames.append(("开机画面", p.to_image()))

    sc = 4
    comp = Image.new("L", (128 * sc + 12, (64 * sc + 16) * len(frames) + 8), 40)
    for n, (_name, im) in enumerate(frames):
        comp.paste(im.resize((128 * sc, 64 * sc), Image.NEAREST), (6, 6 + n * (64 * sc + 16)))
    f = OUT / "ui_all_states.png"
    comp.save(f)

    for n, (_name, im) in enumerate(frames):
        im.resize((128 * 3, 64 * 3), Image.NEAREST).save(OUT / f"ui_{n}.png")

    print(f"{len(frames)} 帧 -> {f.name}")
    for n, (name, _im) in enumerate(frames):
        print(f"   ui_{n}.png  {name}")


if __name__ == "__main__":
    main()
