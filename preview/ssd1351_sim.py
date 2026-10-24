"""主机端 SSD1351 模拟器 —— 忠实复现 NSCLK-ESP32/SSD1351.py 的行为。

为什么要它：128x128 的彩屏只能反复试，真机上迭代一次要拷文件、复位、等开机。
前面 CH559 和 RP2040 两个项目都是靠同类工具把界面调出来的。

⚠️ 核心原则：**模拟的是显存 + 寻址窗口 + 流式写入，不是"直接画像素"**。
   驱动里的每一处算术都照抄，因为真机上出问题的地方恰恰在这些算术里：
     * __rgb_565__ 是**截断**（r>>3、g>>2、b>>3），不做四舍五入 ——
       所以 0x808080 这类"整齐"的灰在屏上不是 0x808080，颜色会有可见偏色；
     * pos() 对坐标做 & 0x7F，x+w-1 越过 127 会**回绕**（不是裁剪）；
     * bwp() 每段复用一块"8 行高"的缓冲区，段数写的是 int(h/8) ——
       h=12（中文子集）时只画 8 行，这个 bug 要在两边一起改（见 check_sync.py）；
     * digi()/icon() 的 x、y 是**中心**；着色是 fore*(alpha/255) 的黑到前景渐变，
       back 只用来填 alpha==0 的像素；
     * digi() 的字符表只有 DIGI_MAP 那 15 个，表外字符取 offset=15*s（第 16 个字形）。

用法：
    python preview/ssd1351_sim.py            # 跑一遍自检，画一张测试图
    python preview/ssd1351_sim.py --art      # 顺便在终端打字符画
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent      # NSCLK-ESP32/
W, H = 128, 128


def rgb565(color: int) -> int:
    """和驱动里 __rgb_565__ 逐字一致：截断、不四舍五入。"""
    c = ((color & 0xFF0000) >> 16 & 0xFF) >> 3
    c <<= 6
    c |= ((color & 0x00FF00) >> 8 & 0xFF) >> 2
    c <<= 5
    c |= (color & 0x0000FF & 0xFF) >> 3
    return c


def rgb565_to_rgb(c: int) -> tuple:
    """565 -> 888，用位复制补齐低位（面板就是这么还原的）。"""
    r5 = (c >> 11) & 0x1F
    g6 = (c >> 5) & 0x3F
    b5 = c & 0x1F
    return ((r5 << 3) | (r5 >> 2), (g6 << 2) | (g6 >> 4), (b5 << 3) | (b5 >> 2))


class SSD1351:
    """接口与设备上的 SSD1351.py 一一对应，坐标/量化/缓冲复用全部照抄。"""

    def __init__(self, root: Path = ROOT):
        self.root = Path(root)
        self.ram = [0] * (W * H)          # 显存：128*128 个 RGB565
        self.xs = self.ys = self.xe = self.ye = 0
        self.cx = self.cy = 0
        f = self.root / "font"
        self.f6 = (f / "font6.bin").read_bytes()
        self.f8 = (f / "font8.bin").read_bytes()
        self.digi_blob = (f / "digi.bin").read_bytes()
        self.icon_blob = (f / "icon.bin").read_bytes()
        self.utf_blob = (f / "utf12.bin").read_bytes()
        self.utf_tab = (f / "utf12.tab").read_bytes()
        self.UTF_W = self.UTF_H = 12
        self.UTF_SIZE = self.UTF_W * 2      # 12 列 × 2 段
        # 和驱动里的映射表一致
        self.DIGI_MAP = {"0": 0, "1": 1, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6,
                         "7": 7, "8": 8, "9": 9, "-": 10, ".": 11, ":": 12,
                         "C": 13, "%": 14}
        self.ICON_MAP = {"battery": 0, "charge": 1, "light": 2,
                         "wifi_on": 3, "wifi_off": 4}
        self.DIGI_W, self.DIGI_H = 12, 18
        self.DIGI_S = self.DIGI_W * self.DIGI_H
        self.ICON_W, self.ICON_H = 24, 24
        self.ICON_S = self.ICON_W * self.ICON_H

    # ------------------------------------------------ 楼层：寻址窗口 + 流式写入
    def pos(self, x, y, w, h):
        """和驱动一样用 & 0x7F —— 越过 127 是**回绕**，不是裁剪。"""
        self.xs = int(x) & 0x7F
        self.ys = int(y) & 0x7F
        self.xe = int(self.xs + int(w) - 1) & 0x7F
        self.ye = int(self.ys + int(h) - 1) & 0x7F
        self.cx, self.cy = self.xs, self.ys
        self._w, self._h = int(w), int(h)
        self._n = 0

    def _put(self, c565):
        """往窗口里顺序写一个像素；按 SSD1351 的行为在窗口内换行、到底回卷。"""
        w, h = getattr(self, "_w", 1), getattr(self, "_h", 1)
        n = self._n
        self._n = n + 1
        if w <= 0 or h <= 0:
            return
        px = self.xs + (n % w)
        py = self.ys + ((n // w) % h)
        self.ram[(py & 0x7F) * W + (px & 0x7F)] = c565 & 0xFFFF

    def send(self, x, y, w, h, buffer):
        """buffer 是每像素 2 字节、高字节在前。驱动不检查长度，这里也照发。"""
        self.pos(x, y, w, h)
        n = len(buffer) // 2
        for i in range(n):
            self._put((buffer[i * 2] << 8) | buffer[i * 2 + 1])

    def fill(self, x, y, w, h, color):
        c = rgb565(color)
        self.pos(x, y, w, h)
        for _ in range(int(w) * int(h)):
            self._put(c)

    def fillc(self, x, y, w, h, color):
        self.fill(x - w / 2, y - h / 2, w, h, color)

    def clear(self, color):
        self.fill(0, 0, W, H, color)

    def bmp(self, x, y, w, h, buffer, center=False):
        if center:
            self.send(x - w / 2, y - h / 2, w, h, buffer)
        else:
            self.send(x, y, w, h, buffer)

    def bmpf(self, x, y, w, h, path):
        self.bmp(x, y, w, h, (self.root / path).read_bytes(), True)

    # ------------------------------------------------ 字模（1 位 -> 双色）
    def bwp(self, x, y, w, h, fore, back, buffer):
        if x > W - w:                       # 驱动的自动换行副作用
            x = 0
            y += h
        fore = rgb565(fore)
        back = rgb565(back)
        # 驱动每段只准备"8 行高"的缓冲并复用，段数写死 int(h/8)——
        # 这两点都照抄，因为 12 高的中文子集正是死在这里，改的时候要两边同时改。
        buff = [0] * int(w * 8 * 2)
        for seg in range(0, int((h + 7) / 8)):
            for col in range(0, int(w)):
                f = w * seg + col
                for row in range(0, 8):
                    if seg * 8 + row >= h:
                        break
                    p = int(w * row + col)
                    c = fore if (buffer[f] & (1 << row)) else back
                    buff[p * 2] = (c >> 8) & 0xFF
                    buff[p * 2 + 1] = c & 0xFF
            # 同驱动：只发这一段实际需要的像素，否则多余的会按窗口回卷覆盖前几行
            _sh = min(8, h - seg * 8)
            self.bmp(x, y + seg * 8, w, _sh, bytes(buff[:int(w * _sh * 2)]))

    def _utf_seek(self, code):
        """和 SSD1351.__utf_seek__ 一样：升序码位表里线性找，返回字节偏移。"""
        for i in range(len(self.utf_tab) // 2):
            if ((self.utf_tab[i * 2] << 8) | self.utf_tab[i * 2 + 1]) == code:
                return i * self.UTF_SIZE
        return -1

    def cjk(self, x, y, fore, back, code):
        off = self._utf_seek(code)
        if off < 0:
            return False
        self.bwp(x, y, self.UTF_W, self.UTF_H, fore, back,
                 self.utf_blob[off:off + self.UTF_SIZE])
        return True

    def _font(self, fid):
        return ((self.f6, 6, 8), (self.f8, 8, 8))[fid % 2]

    def char(self, x, y, fid, fore, back, ch):
        c = ord(ch)
        if c > 0xFF:
            return
        c -= ord(" ")
        f, f_w, f_h = self._font(fid)
        per = f_w * f_h // 8
        self.bwp(x, y, f_w, f_h, fore, back, f[c * per:(c + 1) * per])

    def prt(self, x, y, fid, fore, back, string):
        cnt, siz = 0, len(string)
        _f, f_w, f_h = self._font(fid)
        while cnt < siz:
            _gh = self.UTF_H if ord(string[cnt]) > 0xFF else f_h
            if y > H - _gh:                 # 驱动到这里会清屏并回到 (0,0)
                x = 0
                y = 0
                self.clear(back)
            ch = string[cnt]
            if ch == "\n":
                cnt, x, y = cnt + 1, 0, y + f_h
                continue
            if ch == "\x08":
                cnt += 1
                if x >= f_w:
                    x -= f_w
                else:
                    x, y = W - f_w, y - f_h
                self.char(x, y, fid, fore, back, " ")
                continue
            if ord(ch) > 0xFF:
                self.cjk(x, y, fore, back, ord(ch))
                x += self.UTF_W
                if x >= W - self.UTF_W:
                    x, y = 0, y + self.UTF_H
                cnt += 1
                continue
            self.char(x, y, fid, fore, back, ch)
            x += f_w
            if x >= W - f_w:
                x, y = 0, y + f_h
            cnt += 1

    def prtc(self, x, y, fid, fore, back, string):
        _f, f_w, f_h = self._font(fid)
        self.prt(x - len(string) * f_w / 2, y - f_h / 2, fid, fore, back, string)

    # ------------------------------------------------ 数码管 / 图标
    def _alpha_blit(self, x, y, w, h, fore, back, blob, off, alpha):
        """digi 和 icon 共用的着色：0 -> back，其余 -> fore*(alpha/255)，黑到前景。"""
        (fr, fg, fb) = ((fore >> 16) & 0xFF, (fore >> 8) & 0xFF, fore & 0xFF)
        back = rgb565(back)
        buff = [0] * (w * h * 2)
        for r in range(h):
            for c in range(w):
                p = r * w + c
                a = blob[off + alpha(p)] if off + alpha(p) < len(blob) else 0
                if a == 0:
                    v = back
                else:
                    f = a / 255
                    v = rgb565(round(fr * f) << 16 | round(fg * f) << 8 | round(fb * f))
                buff[p * 2] = (v >> 8) & 0xFF
                buff[p * 2 + 1] = v & 0xFF
        self.bmp(x, y, w, h, bytes(buff))

    def digi(self, x, y, fore, back, string):
        """x、y 是**中心**；逐字符画，字宽 12。字符表外取第 16 个字形。"""
        x -= len(string) * self.DIGI_W / 2
        y -= self.DIGI_H / 2
        for s in string:
            off = self.DIGI_MAP.get(s, len(self.DIGI_MAP)) * self.DIGI_S
            self._alpha_blit(x, y, self.DIGI_W, self.DIGI_H, fore, back,
                             self.digi_blob, off, lambda p: p)
            x += self.DIGI_W

    def icon(self, x, y, fore, back, name):
        """x、y 是**中心**；24x24 单张。"""
        x -= self.ICON_W / 2
        y -= self.ICON_H / 2
        off = self.ICON_MAP.get(str(name).lower(), len(self.ICON_MAP)) * self.ICON_S
        self._alpha_blit(x, y, self.ICON_W, self.ICON_H, fore, back,
                         self.icon_blob, off, lambda p: p)

    # ------------------------------------------------ 帧缓冲接口
    # 真机上 SSD1351 用 32KB 帧缓冲 + 一次 flush 发送（避免一帧 253 次 SPI 事务）。
    # 模拟器的 ram 本身就是帧缓冲，所以 draw/fill 已经是"写内存"，
    # 只要有一个 flush() 让 ui.py 的调用两边都能跑就行。
    def flush(self):
        return

    # ------------------------------------------------ 看结果
    def to_image(self, scale=1):
        im = Image.new("RGB", (W, H))
        px = im.load()
        for y in range(H):
            for x in range(W):
                px[x, y] = rgb565_to_rgb(self.ram[y * W + x])
        if scale > 1:
            im = im.resize((W * scale, H * scale), Image.NEAREST)
        return im

    def to_art(self):
        """终端字符画：按亮度取符号，够看出布局就行（彩屏的色相在终端里看不出来）。"""
        ramp = " .:-=+*#%@"
        out = []
        for y in range(0, H, 2):
            line = ""
            for x in range(0, W, 1):
                r, g, b = rgb565_to_rgb(self.ram[y * W + x])
                v = (r * 30 + g * 59 + b * 11) // 100
                line += ramp[min(9, v * 10 // 256)]
            out.append(line)
        return "\n".join(out)


# ============================================================ 自检
def selftest(p: SSD1351):
    """几项能立刻发现"模拟器没照抄驱动"的检查。"""
    ok = True

    def check(name, got, want):
        nonlocal ok
        if got != want:
            ok = False
            print(f"   [不一致] {name}: 得到 {got!r}，驱动算的是 {want!r}")
        else:
            print(f"   [ok] {name}")

    # 1) 5-6-5 截断（不是四舍五入）
    check("rgb565(0x808080)", hex(rgb565(0x808080)), "0x8410")
    check("rgb565(0xFFFFFF)", hex(rgb565(0xFFFFFF)), "0xffff")
    check("rgb565(0x000000)", hex(rgb565(0x000000)), "0x0")
    # 2) pos 的 & 0x7F 回绕
    p.pos(120, 8, 16, 8)
    check("pos(120,8,16,8) 的 xe 回绕", (p.xs, p.xe), (120, 7))
    # 3) fill 的像素数
    p.clear(0)
    p.fill(0, 0, 8, 4, 0xFFFFFF)
    n = sum(1 for c in p.ram if c == 0xFFFF)
    check("fill(0,0,8,4) 写了 32 个像素", n, 32)
    # 4) bwp 的段数（照抄驱动的 int(h/8)：12 高只画 8 行）
    p.clear(0)
    # 12x12 的字模是 12 列 × 2 段 = 24 字节，给 12 字节会 IndexError
    one = bytes([0xFF] * 24)
    p.bwp(0, 0, 12, 12, 0xFFFFFF, 0x000000, one)
    rows = sum(1 for y in range(12) if any(c == 0xFFFF for c in p.ram[y * W:y * W + 12]))
    check("bwp(h=12) 画满 12 行（分段修正后）", rows, 12)  # 全 0xFF 的测试数据 12 行都有墨
    return ok


def main():
    art = "--art" in sys.argv
    p = SSD1351()
    print("=== SSD1351 模拟器自检 ===")
    ok = selftest(p)
    print("   全部一致" if ok else "   有不一致，先修模拟器再用它判断界面")

    # 画一张"驱动能力测试图"：数码管 / 图标 / ASCII / 灰度
    p.clear(0x101820)
    p.fill(0, 0, 128, 14, 0x1E88E5)
    p.prt(3, 3, 0, 0xFFFFFF, 0x1E88E5, "SSD1351 128x128")
    p.digi(64, 40, 0xFFFFFF, 0x101820, "23.5C")
    p.digi(64, 66, 0x4CAF50, 0x101820, "48%")
    p.prt(4, 84, 1, 0xaaaaaa, 0x101820, "digi: 0-9 . - : C %")
    p.icon(24, 108, 0xFFFFFF, 0x101820, "battery")
    p.icon(56, 108, 0xFFFFFF, 0x101820, "wifi_on")
    p.prt(76, 102, 0, 0xFFC107, 0x101820, "icon 24x24")
    p.fill(76, 114, 40, 6, 0x4CAF50)

    out = ROOT / "preview" / "out"
    out.mkdir(parents=True, exist_ok=True)
    f = out / "sim_selftest.png"
    p.to_image(3).save(f)
    print(f"\n测试图 -> {f}")
    if art:
        print()
        print(p.to_art())


if __name__ == "__main__":
    main()
