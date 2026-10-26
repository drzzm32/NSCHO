import time, rp2
from rp2 import PIO;
from machine import Pin;

OLED_WIDTH = 128;
OLED_HEIGHT = 64;

# ================================ PIO & IO START ================================
@rp2.asm_pio(out_init = (PIO.OUT_HIGH, ) * 8, sideset_init = (PIO.OUT_HIGH, ) * 3)
def __bus_dat__():  #   WR CS DC
    pull()          .side(0b101);
    out(pins, 8)    .side(0b001);
    nop()           .side(0b101);
    out(pins, 8)    .side(0b001);
    nop()           .side(0b101);
    out(pins, 8)    .side(0b001);
    nop()           .side(0b101);
    out(pins, 8)    .side(0b001);
    nop()           .side(0b101);
    nop()           .side(0b111);

smd = rp2.StateMachine(0, __bus_dat__, freq = 20_000_000, sideset_base = Pin(8), out_base = Pin(0));

@rp2.asm_pio(out_init = (PIO.OUT_HIGH, ) * 8, sideset_init = (PIO.OUT_HIGH, ) * 3)
def __bus_cmd__():  #   WR CS DC
    pull()          .side(0b100);
    out(pins, 8)    .side(0b000);
    nop()           .side(0b100);
    nop()           .side(0b111);

smc = rp2.StateMachine(1, __bus_cmd__, freq = 20_000_000, sideset_base = Pin(8), out_base = Pin(0));

RD = Pin(11, Pin.OUT, value = 1);
RST = Pin(13, Pin.OUT, value = 1);
# ================================ PIO & IO END ================================

# ================================ FONT START ================================
FONT_MAX_WIDTH = 16;
file = open("font/font6.bin", mode = "rb");
FONT_6 = file.read();
file.close();
file = open("font/font8.bin", mode = "rb");
FONT_8 = file.read();
file.close();
file = open("font/font16.bin", mode = "rb");
FONT_16 = file.read();
file.close();

def __font__(fid):
    fmap = {
        0: ( FONT_6, 6, 8 ),
        1: ( FONT_8, 8, 8 ),
        2: ( FONT_16, 16, 16 )
    };
    return fmap[fid % len(fmap)];

# 中文字模：12x12 的**子集**，由 tools/make_cjk.py 从 fusion-pixel-12px 生成，
# 只含 ui.ZH_CHARS 里那 12 个字（优良轻中重严空气质量甲醛）。
# ⚠️ 原来是 2 MB 的 utf.bin、**按码位直接索引**（offset = code * 32）。
#    子集省了 7000 倍空间（288 字节），代价是多一次查表 —— 表里只有 12 个字，
#    线性扫比二分还好写，而且不用在内存里另外建索引。
#    每字 24 字节：12 列 × 2 段（bin() 的布局是 byte[w*(row//8)+col]，12 是偶数，合法）。
UTF_W = 12; UTF_H = 12;
UTF_SIZE = UTF_W * 2;                       # = 24（不是 w*h/8，那个算出来是 18）
UTF = open("font/utf12.bin", mode = "rb");
UTF_TAB = open("font/utf12.tab", mode = "rb").read();

def __utf_seek__(code):
    """在升序码位表里找这个字，返回字节偏移；没有就返回 -1（当缺字处理）。"""
    for i in range(int(len(UTF_TAB) / 2)):
        if ((UTF_TAB[i * 2] << 8) | UTF_TAB[i * 2 + 1]) == code:
            return i * UTF_SIZE;
    return -1;

def __utf_read__(offset):
    UTF.seek(offset);
    return UTF.read(UTF_SIZE);

# ================================ FONT END ================================

OLED_BUF = [ 0x00 ] * int(FONT_MAX_WIDTH * 8 / 2);

def dat(value):
    if (smc.active()):
        smc.active(0);
    if (not smd.active()):
        smd.active(1);
        
    smd.put(value);

def cmd(value):
    if (smd.active()):
        smd.active(0);
    if (not smc.active()):
        smc.active(1);
        
    smc.put(value, 24);

def addr(x, y, w, h):
    xs = int(x / 2);
    ys = int(y);
    xe = int(xs + (w - 1) / 2);
    ye = int(ys + h - 1);
    cmd(0x15); cmd(xs); cmd(xe);
    cmd(0x75); cmd(ys); cmd(ye);

def send(x, y, w, h, buffer):
    siz = int(w * h / 2);
    addr(x, y, w, h);
    if (siz <= len(buffer)):
        for i in range(0, int(siz / 4)):
            dat(buffer[i * 4] << 24 | buffer[i * 4 + 1] << 16 | buffer[i * 4 + 2] << 8 | buffer[i * 4 + 3]);

def copy(dx, dy, sx, sy, w, h):
    sx = int(sx / 2);
    ex = sx + int((w - 1) / 2);
    ey = sy + h - 1;
    dx = int(dx / 2);
    cmd(0x25);
    cmd(sx); cmd(sy); cmd(ex); cmd(ey);
    cmd(dx); cmd(dy);

def fill(x, y, w, h, color, acc = False):
    c = color & 0xF;
    c = c << 4 | c;
    if (acc):
        xs = int(x / 2);
        ys = y;
        xe = xs + int((w - 1) / 2);
        ye = ys + h - 1;
        cmd(0x24);
        cmd(xs); cmd(ys);
        cmd(xe); cmd(ye);
        cmd(c);
    else:
        addr(x, y, w, h);
        for i in range(0, int(w * h / 2 / 4)):
            dat(c << 24 | c << 16 | c << 8 | c);

def clear(color = 0x0):
    fill(0, 0, 128, 64, color, True);

def reset():
    RST.value(0);
    time.sleep_ms(10);
    RST.value(1);

def init():
    reset();

    cmd(0xAE);
    
    cmd(0xB3); cmd(0x91);
    cmd(0xA8); cmd(0x3F);
    
    cmd(0xA1); cmd(0x00);
    cmd(0xA0); cmd(0x52);
    cmd(0xA2); cmd(0x4C);
    
    cmd(0xAD); cmd(0x02);
    
    cmd(0x81); cmd(0x7F);
    cmd(0x86);
    
    cmd(0xB8);
    cmd(0x01); cmd(0x11); cmd(0x22); cmd(0x32);
    cmd(0x43); cmd(0x54); cmd(0x65); cmd(0x76);
    
    cmd(0xB2); cmd(0x46);
    cmd(0xB1); cmd(0x22);
    cmd(0xBC); cmd(0x10);
    cmd(0xB4); cmd(0x07); 
    cmd(0xB0); cmd(0x28);
    cmd(0xBE); cmd(0x02);
    cmd(0xBF); cmd(0x0E);
    cmd(0xA4);
    
    clear();
    
    cmd(0xAF);

def bmp(x, y, w, h, buffer, center = False):
    if (center):
        send(x - w / 2, y - h / 2, w, h, buffer);
    else:
        send(x, y, w, h, buffer);

OFF_REMAP = [4, 0];
def bin(x, y, w, h, color, buffer):
    if (x > OLED_WIDTH - w):
        x = 0;
        y += h;
    # ⚠️ 段数要**向上取整**：原来写 int(h/8)，h=12（中文子集）时算出 1，
    #    于是每个 12x12 的字只画了上面 8 行、后 4 行永远丢失 —— 字看起来是残缺的。
    #    布局是 byte[w*seg + col] 的 bit[row%8]，所以段内 row 仍然从 0 数起。
    for seg in range(0, int((h + 7) / 8)):
        for col in range(0, int(w)):
            off = col % 2;
            f = w * seg + col;
            for row in range(0, 8):
                # ⚠️ 最后一截不满 8 行时要在 h 处停：12 高的字分 2 段共 16 行，
                #    不截断就会往下多画 4 行（y=14..17），**溢出到状态带外面**。
                if (seg * 8 + row >= h):
                    break;
                pos = int((w * row + col) / 2);
                OLED_BUF[pos] &= ~(0xF << OFF_REMAP[off]);
                OLED_BUF[pos] |= (color & 0xF if buffer[f] & (1 << row) else color >> 4) << OFF_REMAP[off];
        # ⚠️ 段高不能写死 8：h=12 时第二段只写了 4 行，却发 8 行出去，
        #    后 4 行是 OLED_BUF 里**上一段没被覆盖的残留**（= 字形的第 4~7 行），
        #    画面上就是"顶部结构重复一遍"，并且多占 4 行、溢出到状态带外面。
        #    真机上就是这么坏的（模拟器里写的是 min(8, h-seg*8)，两边不一致 ——
        #    教训：模拟器和驱动必须逐字同步，我这次就是只改了一边）。
        bmp(x, y + seg * 8, w, min(8, h - seg * 8), OLED_BUF);
    
def __c2b__(c):
    return ord(c) & 0xFF;

def char(x, y, fid, color, c):
    c = __c2b__(c);
    c -= __c2b__(' ');
    (f, f_w, f_h) = __font__(fid);
    bin(x, y, f_w, f_h, color, f[int(c * f_w * f_h / 8) : int((c + 1) * f_w * f_h / 8)]);

def __chk_utf__(c):
    val = ord(c);
    return 0 if (val <= 0xFF) else val;

def prt(x, y, fid, color, str):
    cnt = 0; siz = len(str);
    (f, f_w, f_h) = __font__(fid);

    while cnt < siz:
        # ⚠️ 越界判断要用**这一轮实际会画的那个字**的高度：字符串里混中文时，
        #    中文占的是 UTF_H（现在 12），而 f_h 是 ASCII 字库的高度（fid=2 时 16）。
        #    原来一律用 f_h，于是 12x12 的中文只要 y > 64-16 = 48 就被误判越界、
        #    触发"清屏回 (0,0)"——**真机上同样会发生**，不是模拟器的毛病。
        #    （这个 bug 就是把中文字库从 16x16 换成 12x12 之后暴露出来的。）
        _gh = UTF_H if (ord(str[cnt]) > 0xFF) else f_h;
        if (y > OLED_HEIGHT - _gh):
            x = 0;
            y = 0;
            clear(color >> 4);

        code = __chk_utf__(str[cnt]);
        if (code == 0):
            if (str[cnt] == '\n'):
                cnt += 1;
                x = 0;
                y += f_h;
                continue;
            elif (str[cnt] == '\x08'):
                cnt += 1;
                if (x >= f_w):
                    x -= f_w;
                else:
                    x = OLED_WIDTH - f_w;
                    y -= f_h;
                char(x, y, fid, color, ' ');
                continue;
            else:
                char(x, y, fid, color, str[cnt]);
                x += f_w;
                if (x >= OLED_WIDTH - f_w):
                    x = 0;
                    y += f_h;
                cnt += 1;
        else:
            off = __utf_seek__(code);           # 子集要查表，不再是 code * UTF_SIZE
            if (off >= 0):
                bin(x, y, UTF_W, UTF_H, color, __utf_read__(off));
            x += UTF_W;
            if (x >= OLED_WIDTH - UTF_W):
                x = 0;
                y += UTF_H;
            cnt += 1;

def prtc(x, y, fid, color, str):
    (f, f_w, f_h) = __font__(fid);
    end = len(str);
    prt(x - end * f_w / 2, y - f_h / 2, fid, color, str);
    
def icon(x, y, id, fill = False):
    if (id >= 100 and id <= 999):
        p = "icon/" + str(id) + ("-fill.bin" if (fill) else ".bin");
        ico = open(p, mode = "rb");
        buf = ico.read();
        bmp(x, y, 64, 64, buf, True);
        ico.close()
    elif (id >= 1000 and id <= 9999):
        p = "icon/" + str(id) + ".bin";
        ico = open(p, mode = "rb");
        buf = ico.read();
        bmp(x, y, 64, 64, buf, True);
        ico.close()
        
# ============================ 7 段数码管（DSEG7 子集）============================
# 和 digi() 的区别：
#   * 字形来自 font/dseg7.bin（20x26，4 位灰度，含未点亮段的暗轮廓）
#   * **左对齐按固定 20px 推进**，x 是整串的中心，y 是**顶部**
#   * 空格字模就是"只有暗段 8"，所以 "%4d" % value 能得到固定的 4 位字段，
#     不足的位显示暗段 8（真数码管固定位数的观感）
#   * 不支持小数点：主区只显示整数
DIGI7_W = const(20);
DIGI7_H = const(26);
DIGI7_G = const(DIGI7_W * DIGI7_H // 2);        # 260 字节/字
DIGI7_CHARS = "0123456789- ";
DIGI7 = open("font/dseg7.bin", mode = "rb");

def digi7(x, y, string):
    """画 7 段数码管数字。x 是**中心**，y 是**顶部**。

    x 强制偶数：SSD1325 的列地址粒度是 2 像素，奇数 x 会错位。
    """
    n = len(string);
    px = (int(x) - n * DIGI7_W // 2) & ~1;
    for i in range(n):
        k = DIGI7_CHARS.find(string[i]);
        if (k < 0):
            k = 10;                              # 未知字符用 "-" 的位
        DIGI7.seek(k * DIGI7_G);
        bmp(px, y, DIGI7_W, DIGI7_H, DIGI7.read(DIGI7_G));
        px += DIGI7_W;

