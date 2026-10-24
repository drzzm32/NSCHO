from machine import Pin;
from nsclk_ll import bus_write, bus_writes;
import time;


# SSD1351 Constant
SSD1351_CMD_SETCOLUMN = const(0x15);
SSD1351_CMD_SETROW = const(0x75);
SSD1351_CMD_WRITERAM = const(0x5C);
SSD1351_CMD_READRAM = const(0x5D);
SSD1351_CMD_SETREMAP = const(0xA0);
SSD1351_CMD_STARTLINE = const(0xA1);
SSD1351_CMD_DISPLAYOFFSET = const(0xA2);
SSD1351_CMD_DISPLAYALLOFF = const(0xA4);
SSD1351_CMD_DISPLAYALLON = const(0xA5);
SSD1351_CMD_NORMALDISPLAY = const(0xA6);
SSD1351_CMD_INVERTDISPLAY = const(0xA7);
SSD1351_CMD_FUNCTIONSELECT = const(0xAB);
SSD1351_CMD_DISPLAYOFF = const(0xAE);
SSD1351_CMD_DISPLAYON = const(0xAF);
SSD1351_CMD_PRECHARGE = const(0xB1);
SSD1351_CMD_DISPLAYENHANCE = const(0xB2);
SSD1351_CMD_CLOCKDIV = const(0xB3);
SSD1351_CMD_SETVSL = const(0xB4);
SSD1351_CMD_SETGPIO = const(0xB5);
SSD1351_CMD_PRECHARGE2 = const(0xB6);
SSD1351_CMD_SETGRAY = const(0xB8);
SSD1351_CMD_USELUT = const(0xB9);
SSD1351_CMD_PRECHARGELEVEL = const(0xBB);
SSD1351_CMD_VCOMH = const(0xBE);
SSD1351_CMD_CONTRASTABC = const(0xC1);
SSD1351_CMD_CONTRASTMASTER = const(0xC7);
SSD1351_CMD_MUXRATIO = const(0xCA);
SSD1351_CMD_COMMANDLOCK = const(0xFD);
SSD1351_CMD_HORIZSCROLL = const(0x96);
SSD1351_CMD_STOPSCROLL = const(0x9E);
SSD1351_CMD_STARTSCROLL = const(0x9F);

SSD1351_REMAP_VI = const(0x01);
SSD1351_REMAP_VF = const(0x02);
SSD1351_REMAP_CR = const(0x04);
SSD1351_REMAP_SD = const(0x10);
SSD1351_REMAP_OE = const(0x20);
SSD1351_COLOR_8 = const(0x00);
SSD1351_COLOR_16 = const(0x40);
SSD1351_COLOR_18 = const(0x80);


# SSD1351 Init Sequence
SSD1351_INIT_SEQ = [
    SSD1351_CMD_COMMANDLOCK, 1, 0x12,
    SSD1351_CMD_COMMANDLOCK, 1, 0xB1,
    SSD1351_CMD_DISPLAYOFF, 0,
    SSD1351_CMD_CLOCKDIV, 1, 0xF1,
    SSD1351_CMD_MUXRATIO, 1, 127,
    SSD1351_CMD_DISPLAYOFFSET, 1, 0x00,
    SSD1351_CMD_STARTLINE, 1, 0x00,
    SSD1351_CMD_SETREMAP, 1, 0x74,

    SSD1351_CMD_SETCOLUMN, 2, 0x00, 0x7F,
    SSD1351_CMD_SETROW, 2, 0x00, 0x7F,

    SSD1351_CMD_SETGPIO, 1, 0x00,
    SSD1351_CMD_FUNCTIONSELECT, 1, 0x01,

    SSD1351_CMD_SETVSL, 3, 0xA0, 0xB5, 0x55,
    SSD1351_CMD_CONTRASTABC, 3, 0xC8, 0x80, 0xC8,
    SSD1351_CMD_CONTRASTMASTER, 1, 0x0F,

    SSD1351_CMD_SETGRAY, 63,
    0x2,  0x3,  0x4,  0x5,  0x6,  0x7,  0x8,  0x9,
    0xA,  0xB,  0xC,  0xD,  0xE,  0xF,  0x10, 0x11,
    0x12, 0x13, 0x15, 0x17, 0x19, 0x1B, 0x1D, 0x1F,
    0x21, 0x23, 0x25, 0x27, 0x2A, 0x2D, 0x30, 0x33,
    0x36, 0x39, 0x3C, 0x3F, 0x42, 0x45, 0x48, 0x4C,
    0x50, 0x54, 0x58, 0x5C, 0x60, 0x64, 0x68, 0x6C,
    0x70, 0x74, 0x78, 0x7D, 0x82, 0x87, 0x8C, 0x91,
    0x96, 0x9B, 0xA0, 0xA5, 0xAA, 0xAF, 0xB4,

    SSD1351_CMD_PRECHARGE, 1, 0x32,
    SSD1351_CMD_PRECHARGELEVEL, 1, 0x17,
    SSD1351_CMD_DISPLAYENHANCE, 3, 0xA4, 0x00, 0x00,
    SSD1351_CMD_PRECHARGE2, 1, 0x01,

    SSD1351_CMD_VCOMH, 1, 0x05,
    SSD1351_CMD_NORMALDISPLAY, 0,

    SSD1351_CMD_DISPLAYON, 0
];


# Pin configuration
RST = Pin(3, Pin.OUT, value = 1);
DC = Pin(4, Pin.OUT, value = 1);
CS = Pin(5, Pin.OUT, value = 1);
WR = Pin(6, Pin.OUT, value = 1);
RD = Pin(7, Pin.OUT, value = 1);
DATA = [];
for i in range(0, 8):
    DATA.append(Pin(8 + i, Pin.OUT, value = 0));
    pass;


# OLED Constant
OLED_PORTRAIT = const(0);
OLED_PORTRAIT_ANTI = const(1);
OLED_LANDSCAPE = const(2);
OLED_LANDSCAPE_ANTI = const(3);

OLED_WIDTH = const(128);
OLED_HEIGHT = const(128);


# Font Definition
FONT_MAX_WIDTH = 16;
file = open("font/font6.bin", mode="rb");
FONT_6 = file.read();
file.close();
file = open("font/font8.bin", mode="rb");
FONT_8 = file.read();
file.close();

def __font__(fid):
    fmap = {
        0: (FONT_6, 6, 8),
        1: (FONT_8, 8, 8)
    };
    return fmap[fid % len(fmap)];


# Icons Definition
DIGI_MAP = {
    '0': 0, '1': 1, '2': 2, '3': 3, '4': 4,
    '5': 5, '6': 6, '7': 7, '8': 8, '9': 9,
    '-': 10, '.': 11, ':': 12, 'C': 13, '%': 14
};
DIGI_W = const(12); DIGI_H = const(18);
DIGI_S = const(DIGI_W * DIGI_H);
DIGI = open("font/digi.bin", mode="rb")

ICON_MAP = {
    'battery': 0,
    'charge': 1,
    'light': 2,
    'wifi_on': 3,
    'wifi_off': 4
};
ICON_W = const(24); ICON_H = const(24);
ICON_S = const(ICON_W * ICON_H);
ICON = open("font/icon.bin", mode="rb")

# ---- 中文字集（12x12 子集，由 tools/make_cjk.py 生成）----
# 子集不能再按"码位 × 字宽"算偏移，必须查码位表（升序 uint16，二十几个字线性扫）。
UTF_W = const(12); UTF_H = const(12);
UTF_SIZE = const(UTF_W * 2);          # 12 列 × 2 段 = 24 字节/字
UTF = open("font/utf12.bin", mode="rb");
UTF_TAB = open("font/utf12.tab", mode="rb").read();

def __utf_seek__(code):
    for i in range(int(len(UTF_TAB) / 2)):
        if ((UTF_TAB[i * 2] << 8) | UTF_TAB[i * 2 + 1]) == code:
            return i * UTF_SIZE;
    return -1;

def cjk(x, y, fore, back, code):
    off = __utf_seek__(code);
    if (off < 0):
        return False;
    UTF.seek(off);
    bwp(x, y, UTF_W, UTF_H, fore, back, UTF.read(UTF_SIZE));
    return True;


def __rgb_565__(color):
    c =  (((color & 0xFF0000) >> 16) & 0xFF) >> 3;
    c <<= 6;
    c |= (((color & 0x00FF00) >> 8 ) & 0xFF) >> 2;
    c <<= 5;
    c |= (((color & 0x0000FF)      ) & 0xFF) >> 3;
    return c;


def __rgb__(color):
    return (
        ((color & 0xFF0000) >> 16) & 0xFF,
        ((color & 0x00FF00) >> 8 ) & 0xFF,
        ((color & 0x0000FF)      ) & 0xFF
    );


def cmd(value):
    CS.value(0);
    DC.value(0);
    bus_write(value);
    CS.value(1);


def dat(value):
    CS.value(0);
    DC.value(1);
    bus_write(value);
    CS.value(1);


def dats(value, times):
    CS.value(0);
    DC.value(1);
    bus_writes(value, times);
    CS.value(1);


def reset():
    RST.value(0);
    time.sleep_ms(200);
    RST.value(1);


def on():
    cmd(SSD1351_CMD_NORMALDISPLAY);


def off():
    cmd(SSD1351_CMD_DISPLAYALLOFF);


def init():
    reset();
    
    i = 0; r = 0; l = 0; x = 0;
    size = len(SSD1351_INIT_SEQ);
    while (i < size):
        r = SSD1351_INIT_SEQ[i]; i += 1;
        l = SSD1351_INIT_SEQ[i]; i += 1;
        cmd(r);
        for j in range(0, l):
            dat(SSD1351_INIT_SEQ[i]);
            i += 1;
    
    clear(0x000000);


def pos(x, y, w, h):
    xs = int(x) & 0x7F;
    ys = int(y) & 0x7F;
    xe = int(xs + w - 1) & 0x7F;
    ye = int(ys + h - 1) & 0x7F;
    cmd(SSD1351_CMD_SETCOLUMN);
    dat(xs);
    dat(xe);
    cmd(SSD1351_CMD_SETROW);
    dat(ys);
    dat(ye);


def send(x, y, w, h, buffer):
    pos(x, y, w, h);
    cmd(SSD1351_CMD_WRITERAM);
    dat(buffer);


def fill(x, y, w, h, color):
    c = __rgb_565__(color);
    pos(x, y, w, h);
    cmd(SSD1351_CMD_WRITERAM);
    dats(c, w * h);


def fillc(x, y, w, h, color):
    fill(x - w / 2, y - h / 2, w, h, color);


def clear(color):
    fill(0, 0, OLED_WIDTH, OLED_HEIGHT, color);
    pass;


def bmp(x, y, w, h, buffer, center = False):
    if center:
        send(x - w / 2, y - h / 2, w, h, buffer)
        pass;
    else:
        send(x, y, w, h, buffer)
        pass;


def bmpf(x, y, w, h, path):
    file = open(path, mode = 'rb');
    buff = file.read();
    file.close();
    bmp(x, y, w, h, buff, True);


def bwp(x, y, w, h, fore, back, buffer):
    if x > OLED_WIDTH - w:
        x = 0;
        y += h;
        
    fore = __rgb_565__(fore);
    back = __rgb_565__(back);
    
    buff = [0x00] * int(w * 8 * 2);
    # ⚠️ 12x12 中文需要三处分段修正（h 不是 8 的倍数）：段数向上取整 /
    #    最后一段的行在 h 处停 / 每段只发实际需要的像素数。
    for seg in range(0, int((h + 7) / 8)):
        for col in range(0, int(w)):
            f = w * seg + col
            for row in range(0, 8):
                if (seg * 8 + row >= h):
                    break;
                pos = int(w * row + col);
                c = fore if buffer[f] & (1 << row) else back;
                buff[pos * 2] = (c >> 8) & 0xFF;
                buff[pos * 2 + 1] = c & 0xFF;
        sh = min(8, h - seg * 8);
        bmp(x, y + seg * 8, w, sh, bytes(buff[:int(w * sh * 2)]));


def char(x, y, fid, fore, back, ch):
    c = ord(ch);
    if (c > 0xFF):
        return;
    
    c -= ord(' ');
    (f, f_w, f_h) = __font__(fid);
    bwp(x, y, f_w, f_h, fore, back, f[int(c * f_w * f_h / 8): int((c + 1) * f_w * f_h / 8)]);
    
    
def __chk_utf__(c):
    val = ord(c);
    return 0 if (val <= 0xFF) else val;


def prt(x, y, fid, fore, back, string):
    cnt = 0;
    siz = len(string);
    (f, f_w, f_h) = __font__(fid);

    while cnt < siz:
        # 越界判断用**这一轮实际要画的字**的高度（中文 12 / ASCII 8）。
        # 一律用 f_h 的话，12x12 的中文只要 y > 116 就被误判越界、触发清屏。
        _gh = UTF_H if (__chk_utf__(string[cnt]) != 0) else f_h;
        if y > OLED_HEIGHT - _gh:
            x = 0;
            y = 0;
            clear(back);

        if string[cnt] == '\n':
            cnt += 1;
            x = 0;
            y += f_h;
            continue;
        elif string[cnt] == '\x08':
            cnt += 1;
            if x >= f_w:
                x -= f_w;
                pass;
            else:
                x = OLED_WIDTH - f_w;
                y -= f_h;
            char(x, y, fid, fore, back, ' ');
            continue
        elif (__chk_utf__(string[cnt]) != 0):
            cjk(x, y, fore, back, ord(string[cnt]));
            x += UTF_W;
            if x >= OLED_WIDTH - UTF_W:
                x = 0;
                y += UTF_H;
            cnt += 1;
        else:
            char(x, y, fid, fore, back, string[cnt]);
            x += f_w;
            if x >= OLED_WIDTH - f_w:
                x = 0;
                y += f_h;
            cnt += 1;


def prtc(x, y, fid, fore, back, string):
    (f, f_w, f_h) = __font__(fid);
    end = len(string);
    prt(x - end * f_w / 2, y - f_h / 2, fid, fore, back, string);


def digi(x, y, fore, back, string):
    x -= len(string) * DIGI_W / 2;
    y -= DIGI_H / 2;
    
    (fr, fg, fb) = __rgb__(fore);
    back = __rgb_565__(back);
    
    buff = [0x00] * DIGI_S * 2;
    for s in string:
        offset = DIGI_MAP.get(s, len(DIGI_MAP)) * DIGI_S;
        DIGI.seek(offset);
        digi_buf = DIGI.read(DIGI_S);
        for r in range(0, DIGI_H):
            for c in range(0, DIGI_W):
                pos = r * DIGI_W + c;
                if (digi_buf[pos] == 0x00):
                    buff[2 * pos] = (back >> 8) & 0xFF;
                    buff[2 * pos + 1] = back & 0xFF;
                else:
                    f = digi_buf[pos] / 255;
                    color = __rgb_565__(round(fr * f) << 16 | round(fg * f) << 8 | round(fb * f));
                    buff[2 * pos] = (color >> 8) & 0xFF;
                    buff[2 * pos + 1] = color & 0xFF;
        bmp(x, y, DIGI_W, DIGI_H, bytes(buff));
        x += DIGI_W;


def icon(x, y, fore, back, name):
    x -= ICON_W / 2;
    y -= ICON_H / 2;
    
    (fr, fg, fb) = __rgb__(fore);
    back = __rgb_565__(back);
    
    buff = [0x00] * ICON_S * 2;
    offset = ICON_MAP.get(name.lower(), len(ICON_MAP)) * ICON_S;
    ICON.seek(offset);
    icon_buf = ICON.read(ICON_S);
    for r in range(0, ICON_H):
        for c in range(0, ICON_W):
            pos = r * ICON_W + c;
            if (icon_buf[pos] == 0x00):
                buff[2 * pos] = (back >> 8) & 0xFF;
                buff[2 * pos + 1] = back & 0xFF;
            else:
                f = icon_buf[pos] / 255;
                color = __rgb_565__(round(fr * f) << 16 | round(fg * f) << 8 | round(fb * f));
                buff[2 * pos] = (color >> 8) & 0xFF;
                buff[2 * pos + 1] = color & 0xFF;
    bmp(x, y, ICON_W, ICON_H, bytes(buff));

