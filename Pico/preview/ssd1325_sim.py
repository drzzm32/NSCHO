"""主机端 SSD1325 模拟器 —— 忠实复现 Pico/SSD1325.py 的行为。

为什么要模拟：128x64 的 4 位灰度屏只能靠反复试，真机上迭代一次要拷文件、复位、
等开机。CH559 那个项目就是靠一个同类预览工具把界面调出来的。

⚠️ 关键：这里模拟的是**面板 GRAM + 地址窗口 + 流式写入**，不是"直接画像素"。
   SSD1325.py 的每一个字节数算术都照抄，因为真机上出问题的地方恰恰在这些算术里：
     * 列地址粒度是 **2 个像素**（addr 里 xs = int(x/2)、xe = xs + int((w-1)/2)）
       —— 请求宽度不是 2 的倍数时，窗口会向右多出 1 个像素；
     * 一个字节里**高半字节是左边那个像素**（OFF_REMAP = [4, 0]）；
     * send() 只发 **4 * int(siz/4) 个字节**（按 4 字节打包发，尾巴丢掉）；
       fill() 只发 **4 * int(w*h/8) 个字节** —— 这两个截断都是真实的；
     * bin() 的布局是 byte[w*seg + col] 的 bit[row%8]，pos = (w*row+col)//2，
       所以 w 必须是偶数；而且**每个 8 行段是单独一次 bmp()**，
       还有"x > 128 - w 就自动换到 (0, y+h)"的副作用；
     * prtc() 居中用的是 len(str) * f_w —— 字符串里混了中文（16 宽）会偏。
   只画几何位置的模拟器会把上面这些全漏掉（CH559 就漏过一次真机花屏）。

用法：
    python preview/ssd1325_sim.py            # 渲染当前 main.py 的界面（基线）
    python preview/ssd1325_sim.py --art      # 顺便在终端打字符画
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent      # Pico/
W, H = 128, 64
COLB = W // 2                                      # 每行字节数（一个字节 2 个像素）


class SSD1325:
    """接口与设备上的 SSD1325.py 一一对应，坐标/字节数算术照抄。"""

    def __init__(self, root: Path = ROOT):
        self.root = Path(root)
        self.ram = bytearray(COLB * H)             # 面板 GRAM
        self.xs = self.ys = self.xe = self.ye = 0  # 当前地址窗口
        self.cx = self.cy = 0                      # 流式写入游标
        self.buf = [0] * (16 * 8 // 2)             # OLED_BUF：16x8 的临时缓冲

        f = self.root / "font"
        self.f6 = (f / "font6.bin").read_bytes()
        self.f8 = (f / "font8.bin").read_bytes()
        self.f16 = (f / "font16.bin").read_bytes()
        # 中文字模改成 12x12 子集 + 码位表（和 SSD1325.py 保持一致）
        self.utf = (f / "utf12.bin").read_bytes()
        self.utf_tab = (f / "utf12.tab").read_bytes()
        self.UTF_W = self.UTF_H = 12
        self.UTF_SIZE = self.UTF_W * 2             # 24 字节/字（12 列 × 2 段）

    # ------------------------------------------------ 底层：地址窗口 + 流式数据
    def addr(self, x, y, w, h):
        self.xs = int(x / 2)
        self.ys = int(y)
        self.xe = self.xs + int((w - 1) / 2)
        self.ye = int(y + h - 1)
        self.cx, self.cy = self.xs, self.ys

    def dat(self, b):
        """写一个字节（高半字节=左像素），列优先前进、出窗口就换行、出窗口就回卷。"""
        if 0 <= self.cy < H and 0 <= self.cx < COLB:
            self.ram[self.cy * COLB + self.cx] = b & 0xFF
        self.cx += 1
        if self.cx > self.xe:
            self.cx = self.xs
            self.cy += 1
            if self.cy > self.ye:
                self.cy = self.ys

    def send(self, x, y, w, h, buffer):
        siz = int(w * h / 2)
        self.addr(x, y, w, h)
        if siz <= len(buffer):
            # 真机是 4 字节打包一次发的，所以只发 4*int(siz/4) 个字节，尾巴丢掉
            for i in range(0, int(siz / 4)):
                for k in range(4):
                    self.dat(buffer[i * 4 + k])

    # ------------------------------------------------ 矩形 / 位图 / 字模
    def fill(self, x, y, w, h, color, acc=False):
        c = color & 0xF
        c = c << 4 | c
        if acc:
            self.addr(x, y, w, h)
            for i in range(int(w * h / 2)):
                self.dat(c)
        else:
            self.addr(x, y, w, h)
            # 真机只发 4*int(w*h/8) 个字节
            for i in range(int(w * h / 8)):
                for k in range(4):
                    self.dat(c)

    def clear(self, color=0x0):
        self.fill(0, 0, W, H, color, True)

    def bmp(self, x, y, w, h, buffer, center=False):
        if center:
            self.send(x - w / 2, y - h / 2, w, h, buffer)
        else:
            self.send(x, y, w, h, buffer)

    def bin(self, x, y, w, h, color, buffer):
        """1 位点阵按 fg|bg<<4 画。w 必须偶数；x 超出右边界会自动换行。"""
        if x > W - w:
            x = 0
            y += h
        off_remap = (4, 0)
        for seg in range(int((h + 7) / 8)):      # 向上取整：h=12 时是 2 段，不是 1
            # 每个 8 行段单独走一次 bmp，和真机一样（OLED_BUF 复用）
            for col in range(w):
                off = col % 2
                f = w * seg + col
                for row in range(8):
                    if seg * 8 + row >= h:      # 同驱动：最后一截不满 8 行就停
                        break
                    pos = int((w * row + col) / 2)
                    self.buf[pos] &= ~(0xF << off_remap[off])
                    bit = (buffer[f] & (1 << row)) if f < len(buffer) else 0
                    v = (color & 0xF) if bit else (color >> 4)
                    self.buf[pos] |= (v & 0xF) << off_remap[off]
            self.bmp(x, y + seg * 8, w, min(8, h - seg * 8), self.buf)

    # ------------------------------------------------ 字符
    def _font(self, fid):
        return ((self.f6, 6, 8), (self.f8, 8, 8), (self.f16, 16, 16))[fid % 3]

    def char(self, x, y, fid, color, c):
        n = (ord(c) & 0xFF) - ord(" ")
        f, fw, fh = self._font(fid)
        per = fw * fh // 8
        self.bin(x, y, fw, fh, color, f[n * per:(n + 1) * per])

    def prt(self, x, y, fid, color, s):
        cnt, size = 0, len(s)
        _f, fw, fh = self._font(fid)
        while cnt < size:
            # 和 SSD1325.prt() 一样：按**这一轮实际画的字**的高度判断（中文是 UTF_H）
            _gh = self.UTF_H if ord(s[cnt]) > 0xFF else fh
            if y > H - _gh:                         # 真机到这里会清屏并回到 (0,0)
                x, y = 0, 0
                self.clear(color >> 4)
            code = 0 if ord(s[cnt]) <= 0xFF else ord(s[cnt])
            if code == 0:
                if s[cnt] == "\n":
                    cnt, x, y = cnt + 1, 0, y + fh
                    continue
                if s[cnt] == "\x08":
                    cnt += 1
                    if x >= fw:
                        x -= fw
                    else:
                        x, y = W - fw, y - fh
                    self.char(x, y, fid, color, " ")
                    continue
                self.char(x, y, fid, color, s[cnt])
                x += fw
                if x >= W - fw:
                    x, y = 0, y + fh
                cnt += 1
            else:
                off = self._utf_seek(code)
                if off >= 0:
                    self.bin(x, y, self.UTF_W, self.UTF_H, color,
                             self.utf[off:off + self.UTF_SIZE])
                x += self.UTF_W
                if x >= W - self.UTF_W:
                    x, y = 0, y + self.UTF_H
                cnt += 1

    def prtc(self, x, y, fid, color, s):
        _f, fw, _fh = self._font(fid)
        self.prt(x - len(s) * fw / 2, y - self._font(fid)[2] / 2, fid, color, s)

    # ------------------------------------------------ 图标 / 数码管
    def icon(self, x, y, idx, fill=False):
        if 100 <= idx <= 999:
            p = self.root / "icon" / f"{idx}{'-fill' if fill else ''}.bin"
        elif 1000 <= idx <= 9999:
            p = self.root / "icon" / f"{idx}.bin"
        else:
            return
        if p.exists():
            self.bmp(x, y, 64, 64, p.read_bytes(), True)

    DIGI7_W = 20
    DIGI7_H = 26
    DIGI7_G = DIGI7_W * DIGI7_H // 2
    DIGI7_CHARS = "0123456789- "

    def digi7(self, x, y, string):
        if not hasattr(self, "_d7"):
            self._d7 = (self.root / "font" / "dseg7.bin").read_bytes()
        n = len(string)
        px = (int(x) - n * self.DIGI7_W // 2) & ~1
        for i in range(n):
            k = self.DIGI7_CHARS.find(string[i])
            if k < 0: k = 10
            off = k * self.DIGI7_G
            self.bmp(px, y, self.DIGI7_W, self.DIGI7_H, self._d7[off:off + self.DIGI7_G])
            px += self.DIGI7_W

    def _utf_seek(self, code):
        """和 SSD1325.__utf_seek__ 一样：升序码位表里线性找。"""
        for i in range(len(self.utf_tab) // 2):
            if ((self.utf_tab[i * 2] << 8) | self.utf_tab[i * 2 + 1]) == code:
                return i * self.UTF_SIZE
        return -1

    # ------------------------------------------------ 看结果
    def to_image(self, scale=1):
        im = Image.new("L", (W, H), 0)
        px = im.load()
        for row in range(H):
            for cx in range(COLB):
                b = self.ram[row * COLB + cx]
                px[cx * 2, row] = (b >> 4) * 17        # 高半字节 = 左边那个像素
                px[cx * 2 + 1, row] = (b & 0x0F) * 17
        if scale > 1:
            im = im.resize((W * scale, H * scale), Image.NEAREST)
        return im

    def to_art(self):
        """终端字符画：用不同的符号表示灰度（0-15）。"""
        ramp = " .:-=+*#%@"
        out = []
        for row in range(H):
            line = ""
            for cx in range(COLB):
                b = self.ram[row * COLB + cx]
                for v in (b >> 4, b & 0x0F):
                    line += ramp[min(9, v * 10 // 16)]
            out.append(line)
        return "\n".join(out)


# ============================================================ 当前界面（基线）
def draw_baseline(p, pm1=12, pm25=35, pm10=48, co2=580):
    """完全照抄设备上 main.py 现在的画法，用来和真机对比。"""
    p.clear()
    p.prtc(64, 8, 0, 0x08, "EnvSensor")
    p.prt(8, 16, 1, 0x0F, "PM1.0:%3dug/m3" % pm1)
    p.prt(8, 28, 1, 0x0F, "PM2.5:%3dug/m3" % pm25)
    p.prt(8, 40, 1, 0x0F, "PM10: %3dug/m3" % pm10)
    p.prt(8, 52, 1, 0x0F, "CO2: %4dppm" % co2)


def main():
    art = "--art" in sys.argv
    scale = 4 if "--big" in sys.argv or art else 1
    p = SSD1325()
    draw_baseline(p)
    out = ROOT / "preview" / "out"
    out.mkdir(parents=True, exist_ok=True)
    f = out / "baseline_current.png"
    p.to_image(scale if scale > 1 else 3).save(f)
    print(f"当前界面（基线）-> {f}")
    print(f"  画布 {W}x{H}，GRAM {len(p.ram)} 字节")
    print(f"  用到的素材: font8 ({len(p.f8)}B) / utf ({len(p.utf)}B)")
    if art:
        print()
        print(p.to_art())


if __name__ == "__main__":
    main()
