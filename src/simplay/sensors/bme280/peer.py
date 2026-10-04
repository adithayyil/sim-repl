# Synthetic BME280 SPI slave built from Bosch datasheet rev 1.23 (register map s5, SPI s6.3).
# Trim and raw ADC values are made up; H and raw values are NOT from a real part.
TRIM = dict(T1=27504, T2=26435, T3=-1000,
            P1=36477, P2=-10685, P3=3024, P4=2855, P5=140, P6=-7, P7=15500, P8=-14600, P9=6000,
            H1=75, H2=362, H3=12, H4=314, H5=50, H6=30)
MEAS = [(519888, 415148, 30000), (521000, 414000, 31500)]   # (adc_T, adc_P, adc_H)

def u16(v): return [v & 0xFF, (v >> 8) & 0xFF]

def calib():
    r = {}
    t = TRIM
    b = (u16(t['T1']) + u16(t['T2'] & 0xFFFF) + u16(t['T3'] & 0xFFFF) +
         u16(t['P1']) + [x for k in ('P2','P3','P4','P5','P6','P7','P8','P9') for x in u16(t[k] & 0xFFFF)])
    for i, v in enumerate(b): r[0x88 + i] = v
    r[0xA0] = 0x00
    r[0xA1] = t['H1']
    r[0xE1], r[0xE2] = u16(t['H2'] & 0xFFFF)
    r[0xE3] = t['H3']
    r[0xE4] = (t['H4'] >> 4) & 0xFF
    r[0xE5] = (t['H4'] & 0x0F) | ((t['H5'] & 0x0F) << 4)
    r[0xE6] = (t['H5'] >> 4) & 0xFF
    r[0xE7] = t['H6'] & 0xFF
    return r

class Slave:
    def __init__(self, ctx):
        self.ctx = ctx
        self.cal = calib()
        self.k = 0
        self.reset_regs()
        self.phase = 0
        self.im_pending = 1   # NVM copy at power-on

    def reset_regs(self):
        self.ctrl_hum = 0; self.ctrl_meas = 0; self.config = 0
        self.data = {0xF7: 0x80, 0xF8: 0, 0xF9: 0, 0xFA: 0x80, 0xFB: 0, 0xFC: 0, 0xFD: 0x80, 0xFE: 0}
        self.im_pending = 1

    def load_measurement(self):
        T, P, H = MEAS[min(self.k, len(MEAS) - 1)]
        self.k += 1
        osrs_t = (self.ctrl_meas >> 5) & 7
        osrs_p = (self.ctrl_meas >> 2) & 7
        osrs_h = self.ctrl_hum & 7
        if osrs_t == 0: T = 0x80000
        if osrs_p == 0: P = 0x80000
        if osrs_h == 0: H = 0x8000
        d = self.data
        d[0xF7] = (P >> 12) & 0xFF; d[0xF8] = (P >> 4) & 0xFF; d[0xF9] = (P & 0xF) << 4
        d[0xFA] = (T >> 12) & 0xFF; d[0xFB] = (T >> 4) & 0xFF; d[0xFC] = (T & 0xF) << 4
        d[0xFD] = (H >> 8) & 0xFF; d[0xFE] = H & 0xFF

    def read_reg(self, a):
        if a == 0xD0: return 0x60
        if a == 0xE0: return 0x00
        if a in self.cal: return self.cal[a]
        if a == 0xF2: return self.ctrl_hum
        if a == 0xF3:
            if self.im_pending > 0:
                self.im_pending -= 1
                return 0x01
            return 0x00
        if a == 0xF4: return self.ctrl_meas
        if a == 0xF5: return self.config
        if a in self.data: return self.data[a]
        return 0x00

    def write_reg(self, a, v):
        if a == 0xE0:
            if v == 0xB6: self.reset_regs()
        elif a == 0xF2:
            self.ctrl_hum = v & 7
        elif a == 0xF4:
            self.ctrl_meas = v
            mode = v & 3
            if mode != 0:
                self.ctx.info("M %02x %02x %02x" % (self.ctrl_hum, v, self.config))
                self.load_measurement()
                if mode in (1, 2): self.ctrl_meas = v & 0xFC   # forced mode returns to sleep
        elif a == 0xF5:
            if (self.ctrl_meas & 3) != 3: self.config = v

    def on_select(self):
        self.phase = 0
        self.ctx.info("S")

    def on_deselect(self):
        self.ctx.info("D")

    def on_transmit(self, b):
        if self.phase == 0:
            self.rd = bool(b & 0x80); self.addr = b & 0x7F
            self.phase = 1
            self.ctx.info("B %02x 00" % b)
            return 0x00
        if self.rd:
            full = self.addr | 0x80
            out = self.read_reg(full)
            self.addr = (self.addr + 1) & 0x7F
            self.ctx.info("B %02x %02x" % (b, out))
            return out
        # write: alternating data / control
        if self.phase == 1:
            self.write_reg(self.addr | 0x80, b)
            self.phase = 2
        else:
            self.addr = b & 0x7F
            self.rd = bool(b & 0x80)
            self.phase = 1
        self.ctx.info("B %02x 00" % b)
        return 0x00
