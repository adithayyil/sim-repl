"""Datasheet oracle for the BME280 (Bosch BST-BME280-DS002 rev 1.23, sections 4.2.3, 5.4, 6.3, 9.1).

Independent of bme280.c: it reimplements the datasheet's fixed-point formulas.
Names follow the datasheet's own, so this file reads side by side with
sections 4.2.3 (compensation) and 9.1 (measurement time).  Units are the ones
bme280.c reports in fixed-point mode: centi-degrees, 1/100 Pa, Q22.10 %RH.
"""

from __future__ import annotations

from . import peer


def cdiv(a: int, b: int) -> int:
    """C integer division: truncates toward zero (Python // floors). Exact, no floats."""
    q = abs(a) // abs(b)
    return q if (a >= 0) == (b >= 0) else -q


def comp_T(adc_T: int, t: dict) -> tuple[int, int]:
    """Datasheet 4.2.3: temperature and t_fine, in centi-degrees."""
    var1 = (((adc_T >> 3) - (t["T1"] << 1)) * t["T2"]) >> 11
    var2 = (((((adc_T >> 4) - t["T1"]) * ((adc_T >> 4) - t["T1"])) >> 12) * t["T3"]) >> 14
    t_fine = var1 + var2
    return (t_fine * 5 + 128) >> 8, t_fine


def comp_P(adc_P: int, t_fine: int, t: dict) -> int:
    """Datasheet 4.2.3: pressure in Q24.8 Pa."""
    var1 = t_fine - 128000
    var2 = var1 * var1 * t["P6"]
    var2 = var2 + ((var1 * t["P5"]) << 17)
    var2 = var2 + (t["P4"] << 35)
    var1 = ((var1 * var1 * t["P3"]) >> 8) + ((var1 * t["P2"]) << 12)
    var1 = (((1 << 47) + var1) * t["P1"]) >> 33
    if var1 == 0:
        return 0
    p = 1048576 - adc_P
    p = cdiv(((p << 31) - var2) * 3125, var1)
    var1 = (t["P9"] * (p >> 13) * (p >> 13)) >> 25
    var2 = (t["P8"] * p) >> 19
    return ((p + var1 + var2) >> 8) + (t["P7"] << 4)


def comp_H(adc_H: int, t_fine: int, t: dict) -> int:
    """Datasheet 4.2.3: humidity in Q22.10 %RH."""
    v = t_fine - 76800
    h3 = ((v * t["H3"]) >> 11) + 32768
    h6 = (((v * t["H6"]) >> 10) * h3) >> 10
    v = ((((adc_H << 14) - (t["H4"] << 20) - (t["H5"] * v)) + 16384) >> 15) * (
        ((h6 + 2097152) * t["H2"] + 8192) >> 14
    )
    v = v - (((((v >> 15) * (v >> 15)) >> 7) * t["H1"]) >> 4)
    return min(max(v, 0), 419430400) >> 12


def expected_measurements() -> list[tuple[int, int, int]]:
    """One (T_centi_degC, P_pa_x100, H_q10) per reading the peer serves."""
    out = []
    for aT, aP, aH in peer.MEAS:
        T, t_fine = comp_T(aT, peer.TRIM)
        P = comp_P(aP, t_fine, peer.TRIM)
        H = comp_H(aH, t_fine, peer.TRIM)
        out.append((T, (P * 100) // 256, H))  # Q24.8 Pa -> 1/100 Pa
    return out


def expected_ram() -> dict:
    """Same shape as read_ram(), so the oracle can be rendered and diffed directly."""
    m = expected_measurements()
    return dict(
        T=[x[0] for x in m],
        P=[x[1] for x in m],
        H=[x[2] for x in m],
        md=t_measure_max_us(2, 8, 1),
        chip=0x60,
    )


def t_measure_max_us(osr_t: int, osr_p: int, osr_h: int) -> int:
    """Datasheet 9.1 in us. osr_* are actual oversampling factors; 0 means skipped."""
    t = 2.3 * osr_t if osr_t else 0
    p = 2.3 * osr_p + 0.575 if osr_p else 0
    h = 2.3 * osr_h + 0.575 if osr_h else 0
    return round((1.25 + t + p + h) * 1000)


if __name__ == "__main__":
    for m, (T, P, H) in zip(peer.MEAS, expected_measurements(), strict=True):
        print(f"raw {m} -> T={T / 100:.2f} C  P={P / 100:.2f} Pa  H={H / 1024:.2f} %RH")
    print("t_measure_max_us (T2x,P8x,H1x) =", t_measure_max_us(2, 8, 1))
