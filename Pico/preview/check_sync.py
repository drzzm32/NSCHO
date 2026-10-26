"""核对 SSD1325.py（真机）和 preview/ssd1325_sim.py（模拟器）的核心算法是否还一致。

**为什么需要它**：这两个文件是同一套算法的两份实现。把中文字库从 16x16 换成 12x12
时，驱动的 `bin()` 里有三处隐含假设"高度是 8 的倍数"，我改了模拟器、漏改了驱动里的
一行（段高写死 8）—— 结果**预览干净、真机却溢出，而且是"文字顶部结构重复一遍"**
（第二段只写了 4 行却发 8 行，后 4 行是缓冲里的残留）。只靠人眼看比对注定会漏，
所以留一个自动核对。

**做法**：不做整份函数体的 diff（那样永远有 `self.`/分号/换行的噪声），
只核对**出过事的那几个结构不变量** —— 它们一旦两边不一致，屏上就会出可见的错。

用法： python preview/check_sync.py    （一致返回 0，不一致返回 1）
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DRIVER = ROOT / "SSD1325.py"
SIM = ROOT / "preview" / "ssd1325_sim.py"

# (说明, 正则, 为什么它是关键)
INVARIANTS = (
    ("bin: 段数向上取整", r"int\(\(h \+ 7\) / 8\)",
     "写成 int(h/8) 时 h=12 只画 1 段，12x12 的字后 4 行永远丢失"),
    ("bin: 最后一段的行要在 h 处截断", r"seg \* 8 \+ row >= h",
     "不截断就会多画行、溢出到邻近区域"),
    ("bin: 每段发的行数要按实际段高", r"min\(8, h - seg \* 8\)",
     "写死 8 时最后一段会发出缓冲里的残留 → 画面上'顶部结构重复一遍'并溢出"),
    ("bin: 像素位置按 w*row+col 折半", r"int\(\(w \* row \+ col\) / 2\)",
     "布局约定，两边不一致会整块错位"),
    ("prt: 越界判断按实际字形高度", r"UTF_H if .*ord\(",
     "用 ASCII 字库的 f_h 判断时，12x12 的中文会被误判越界、触发清屏"),
)

# 真机那边这些名字和模拟器不同，比对前统一
ALIASES = (
    (r"\bOLED_WIDTH\b", "W"),
    (r"\bOLED_HEIGHT\b", "H"),
    (r"\bself\.", ""),
    (r"\boff_remap\b", "OFF_REMAP"),
    (r"\bUTF_W\b", "UTFW"),
)


def body(path: Path, name: str) -> str:
    t = path.read_text(encoding="utf-8")
    m = re.search(rf"(?m)^\s*def {name}\(", t)
    if not m:
        sys.exit(f"✗ {path.name} 里找不到 def {name}(")
    rest = t[m.end():]
    m2 = re.search(r"(?m)^\s*(def |# ===)", rest)
    seg = rest[:m2.start()] if m2 else rest
    out = []
    for ln in seg.splitlines():
        x = ln.split("#")[0].strip()
        if x:
            out.append(x)
    s = "\n".join(out)
    for pat, rep in ALIASES:
        s = re.sub(pat, rep, s)
    return s


def main() -> int:
    bad = 0
    for name in ("bin", "prt", "fill", "send"):
        d, s = body(DRIVER, name), body(SIM, name)
        for what, pat, why in INVARIANTS:
            if not what.startswith(name + ":"):
                continue
            hit = (bool(re.search(pat, d)), bool(re.search(pat, s)))
            mark = "✅" if hit[0] == hit[1] else "✗"
            print(f"   {mark} {what:28} 驱动={'有' if hit[0] else '无'} "
                  f"模拟器={'有' if hit[1] else '无'}")
            if hit[0] != hit[1]:
                bad += 1
                print(f"        ⚠️ 两边不一致 —— {why}")
    print()
    if bad:
        print(f"✗ {bad} 项不一致：真机和预览的行为会不一样，先修成一致再往下做")
        return 1
    print("✅ 关键结构两边一致 —— 预览里看到的就是真机上会看到的")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
