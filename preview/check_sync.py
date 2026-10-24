"""核对 SSD1351.py（真机）和 preview/ssd1351_sim.py（模拟器）的核心算法是否一致。

**为什么需要它**：这两个文件是同一套算法的两份实现。RP2040 那个项目就因为"只改了
模拟器、漏了驱动"出过事 —— 预览干净、真机溢出且文字顶部结构重复。

**做法**：不做整份函数 diff（永远有 self./分号/换行的噪声），只核对**出过事的结构
不变量**，以及一条能直接量出来的行为：12x12 的字形到底画了几行。

用法： python preview/check_sync.py      （一致返回 0，不一致返回 1）
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "preview"))

DRIVER = ROOT / "SSD1351.py"
SIM = ROOT / "preview" / "ssd1351_sim.py"

INVARIANTS = (
    ("bwp: 段数向上取整", r"range\(0, int\(\(h \+ 7\) / 8\)\)",
     "写成 int(h/8) 时 h=12 只画 1 段，12x12 的字后 4 行丢失"),
    ("bwp: 最后一段在 h 处截断", r"seg \* 8 \+ row >= h",
     "不截断会多画行、溢出到邻近区域"),
    ("bwp: 每段发 min(8, h-seg*8) 行", r"min\(8, h - seg \* 8\)",
     "写死 8 时最后一段会发出缓冲残留 → 顶部结构重复"),
    ("bwp: 按段实际像素数截断缓冲", r"buff\[:int\(w \* _?sh \* 2\)\]"
     # 变量名在驱动里是 sh、早期草稿是 _sh，两种都认,
     "整块发 8 行缓冲时，最后一段多余的像素会按窗口回卷覆盖前几行 —— "
     "画面上是「12 高的字下半截显示成中间几行」"),
    ("prt: 越界判断按实际字形高度", r"UTF_H if .*__chk_utf__|UTF_H if ord\(",
     "用 ASCII 的 f_h 判断时 12x12 中文会被误判越界、触发清屏"),
    ("5-6-5 量化是截断", r">> 3",
     "改成四舍五入的话真机偏色和预览不一致"),
    ("pos: 坐标 & 0x7F 回绕", r"& 0x7F",
     "越界不是裁剪是回绕"),
)

ALIASES = (
    (r"\bOLED_WIDTH\b", "W"),
    (r"\bOLED_HEIGHT\b", "H"),
    (r"\bself\.", ""),
)


def body(path: Path, name: str) -> str:
    t = path.read_text(encoding="utf-8")
    m = re.search(rf"(?m)^\s*def {name}\(", t)
    if not m:
        sys.exit(f"✗ {path.name} 里找不到 def {name}(")
    rest = t[m.end():]
    m2 = re.search(r"(?m)^\s*(def |# ===)", rest)
    seg = rest[:m2.start()] if m2 else rest
    keep = []
    for ln in seg.splitlines():
        x = ln.split("#")[0].strip()
        if x:
            keep.append(x)
    s = "\n".join(keep)
    for pat, rep in ALIASES:
        s = re.sub(pat, rep, s)
    return s


def main() -> int:
    bad = 0
    print("=== 结构不变量 ===")
    for what, pat, why in INVARIANTS:
        target = "pos" if what.startswith("pos") else (
            "bwp" if what.startswith("bwp") else (
                "prt" if what.startswith("prt") else "__rgb_565__"))
        fn = "__rgb_565__" if target == "__rgb_565__" else target
        d_has = bool(re.search(pat, body(DRIVER, fn), re.M))
        s_has = bool(re.search(pat, body(SIM, "rgb565" if fn == "__rgb_565__" else fn), re.M))
        mark = "一致" if d_has == s_has else "不一致"
        print(f"   [{mark}] {what:30} 驱动={'有' if d_has else '无'} "
              f"模拟器={'有' if s_has else '无'}")
        if d_has != s_has:
            bad += 1
            print(f"            ⚠️ {why}")

    # 注意：**不能**用"每行都有墨"当判据 —— 汉字的点阵本来就有空行
    #（比如「温」的第 0/6/10 行是空的，这是字形结构，不是漏画）。
    # 真正该验的是"墨迹不越过 12 行的格子"，也就是 y>=12 必须是干净的背景。
    print("\n=== 行为：12x12 的字有没有越过格子 ===")
    from ssd1351_sim import SSD1351
    p = SSD1351()
    BG = 0x101820
    p.clear(BG)
    p.prt(0, 0, 0, 0xFFFFFF, BG, "温湿度俯仰横滚")
    bg565 = p.ram[0]
    ink_rows = [y for y in range(0, 20)
                if any(p.ram[y * 128 + x] != bg565 for x in range(96))]
    over = [y for y in ink_rows if y >= 12]
    print(f"   有墨的行: {ink_rows}")
    print(f"   越界行(>=12): {over if over else '无'}")
    ok12 = not over
    print(f"   [{'一致' if ok12 else '不一致'}] 墨迹应当全部落在 0..11 这 12 行内")
    if not ok12:
        bad += 1

    print()
    if bad:
        print(f"✗ {bad} 项不一致：真机和预览会不一样，先修成一致再往下做")
        return 1
    print("✅ 驱动与模拟器一致 —— 预览里看到的就是真机上会看到的")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
