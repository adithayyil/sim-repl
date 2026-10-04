# Synthetic BMP388 SPI slave written from Bosch BST-BMP388-DS001-07 rev 1.7 (register map Sec. 4, SPI Sec. 5.3).
# Trim and raw ADC values are made up; they are NOT from a real part.
TRIM = dict(T1=28000, T2=18000, T3=-10,
            P1=30919, P2=16400, P3=5, P4=-3, P5=1000, P6=1200, P7=-5, P8=-20, P9=-300, P10=10, P11=-3)
MEAS = [(8659000, 6600000), (8663000, 6610000)]      # (raw_t, raw_p) per forced measurement

def u16(v): return [v & 0xFF, (v >> 8) & 0xFF]
def s8(v): return v & 0xFF

def calib():
    t = TRIM
    b = (u16(t['T1']) + u16(t['T2']) + [s8(t['T3'])] + u16(t['P1'] & 0xFFFF) + u16(t['P2'] & 0xFFFF) +
         [s8(t['P3']), s8(t['P4'])] + u16(t['P5']) + u16(t['P6']) + [s8(t['P7']), s8(t['P8'])] +
         u16(t['P9'] & 0xFFFF) + [s8(t['P10']), s8(t['P11'])])
    assert len(b) == 21
    return {0x31 + i: v for i, v in enumerate(b)}

class Slave:
    def __init__(self, ctx):
        self.ctx = ctx
        self.cal = calib()
        self.k = 0
        self.reset_regs()
        self.phase = 0

    def reset_regs(self):
        self.pwr = 0; self.osr = 0x02; self.odr = 0; self.cfg = 0
        self.data = {4: 0, 5: 0, 6: 0x80, 7: 0, 8: 0, 9: 0x80}
        self.drdy_p = 0; self.drdy_t = 0

    def measure(self):
        rt, rp = MEAS[min(self.k, len(MEAS) - 1)]
        self.k += 1
        if self.pwr & 1:
            self.data[4], self.data[5], self.data[6] = rp & 0xFF, (rp >> 8) & 0xFF, (rp >> 16) & 0xFF
            self.drdy_p = 1
        if self.pwr & 2:
            self.data[7], self.data[8], self.data[9] = rt & 0xFF, (rt >> 8) & 0xFF, (rt >> 16) & 0xFF
            self.drdy_t = 1

    def read_reg(self, a):
        if a == 0x00: return 0x50
        if a == 0x02: return 0x00
        if a == 0x03: return 0x10 | (self.drdy_p << 5) | (self.drdy_t << 6)
        if a in self.data:
            if a <= 6: self.drdy_p = 0
            else: self.drdy_t = 0
            return self.data[a]
        if a == 0x1B: return self.pwr
        if a == 0x1C: return self.osr
        if a == 0x1D: return self.odr
        if a == 0x1F: return self.cfg
        if a in self.cal: return self.cal[a]
        return 0x00

    def write_reg(self, a, v):
        if a == 0x7E:
            if v == 0xB6: self.reset_regs()
        elif a == 0x1B:
            self.pwr = v & 0x33
            mode = (v >> 4) & 3
            if mode in (1, 2):
                self.ctx.info("M %02x %02x %02x %02x" % (self.osr, self.odr, self.cfg, v))
                self.measure()
                self.pwr &= 0x03              # forced mode returns to sleep
        elif a == 0x1C: self.osr = v & 0x3F
        elif a == 0x1D: self.odr = v & 0x1F
        elif a == 0x1F: self.cfg = v & 0x0E

    def on_select(self):
        self.phase = 0
        self.ctx.info("S")

    def on_deselect(self):
        self.ctx.info("D")

    def on_transmit(self, b):
        if self.phase == 0:
            self.rd = bool(b & 0x80); self.addr = b & 0x7F
            self.phase = 1
            self.nread = 0
            self.ctx.info("B %02x 00" % b)
            return 0x00
        if self.rd:
            if self.nread == 0:                 # datasheet Sec. 5.3.2: one dummy byte after the control byte
                self.nread = 1
                self.ctx.info("B %02x 00" % b)
                return 0x00
            out = self.read_reg(self.addr)
            self.addr = (self.addr + 1) & 0x7F
            self.ctx.info("B %02x %02x" % (b, out))
            return out
        if self.phase == 1:
            self.write_reg(self.addr, b)
            self.phase = 2
        else:
            self.addr = b & 0x7F
            self.rd = bool(b & 0x80)
            self.phase = 1
        self.ctx.info("B %02x 00" % b)
        return 0x00
