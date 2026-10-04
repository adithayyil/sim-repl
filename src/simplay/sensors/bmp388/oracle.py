"""Datasheet oracle for the BMP388 (Bosch BST-BMP388-DS001-07 rev 1.7, Sec. 3.11.1 + Sec. 9).
Independent of bmp3.c: coefficient scaling from the datasheet table, formulas from Sec. 9.2/9.3, evaluated in Python double."""
from . import peer

def quant(n):
    return dict(t1=n['T1'] / 2**-8, t2=n['T2'] / 2**30, t3=n['T3'] / 2**48,
                p1=(n['P1'] - 2**14) / 2**20, p2=(n['P2'] - 2**14) / 2**29, p3=n['P3'] / 2**32, p4=n['P4'] / 2**37,
                p5=n['P5'] / 2**-3, p6=n['P6'] / 2**6, p7=n['P7'] / 2**8, p8=n['P8'] / 2**15,
                p9=n['P9'] / 2**48, p10=n['P10'] / 2**48, p11=n['P11'] / 2**65)

def comp_T(raw_t, q):
    d1 = raw_t - q['t1']
    d2 = d1 * q['t2']
    return d2 + d1 * d1 * q['t3']

def comp_P(raw_p, t, q):
    o1 = q['p5'] + q['p6'] * t + q['p7'] * t**2 + q['p8'] * t**3
    o2 = raw_p * (q['p1'] + q['p2'] * t + q['p3'] * t**2 + q['p4'] * t**3)
    d = raw_p**2 * (q['p9'] + q['p10'] * t) + raw_p**3 * q['p11']
    return o1 + o2 + d

def expected():
    q = quant(peer.TRIM)
    out = []
    for rt, rp in peer.MEAS:          # MEAS = (raw_t, raw_p)
        t = comp_T(rt, q)
        out.append((t, comp_P(rp, t, q)))
    return out

def expected_ram():
    """Same shape as read_ram(), so the oracle can be rendered and diffed directly."""
    e = expected()
    return dict(T=[x[0] for x in e], P=[x[1] for x in e], chip=0x50)

if __name__ == "__main__":
    for m, (t, p) in zip(peer.MEAS, expected()):
        print("raw", m, "-> T=%.4f C  P=%.3f Pa" % (t, p))
