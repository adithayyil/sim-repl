"""Datasheet oracle for the BMP388 (Bosch BST-BMP388-DS001-07 rev 1.7, Sec. 3.11.1 + Sec. 9).

Independent of bmp3.c: coefficient scaling from the datasheet's table, formulas
from Sec. 9.2/9.3, evaluated in Python double.
"""

from __future__ import annotations

from . import peer


def quant(n: dict) -> dict[str, float]:
    """Datasheet 3.11.1: the register coefficients scaled to their real units."""
    return dict(
        t1=n["T1"] / 2**-8,
        t2=n["T2"] / 2**30,
        t3=n["T3"] / 2**48,
        p1=(n["P1"] - 2**14) / 2**20,
        p2=(n["P2"] - 2**14) / 2**29,
        p3=n["P3"] / 2**32,
        p4=n["P4"] / 2**37,
        p5=n["P5"] / 2**-3,
        p6=n["P6"] / 2**6,
        p7=n["P7"] / 2**8,
        p8=n["P8"] / 2**15,
        p9=n["P9"] / 2**48,
        p10=n["P10"] / 2**48,
        p11=n["P11"] / 2**65,
    )


def comp_T(raw_t: float, q: dict) -> float:
    """Datasheet 9.2, in degrees C."""
    d1 = raw_t - q["t1"]
    d2 = d1 * q["t2"]
    return d2 + d1 * d1 * q["t3"]


def comp_P(raw_p: float, t: float, q: dict) -> float:
    """Datasheet 9.3, in Pa."""
    o1 = q["p5"] + q["p6"] * t + q["p7"] * t**2 + q["p8"] * t**3
    o2 = raw_p * (q["p1"] + q["p2"] * t + q["p3"] * t**2 + q["p4"] * t**3)
    d = raw_p**2 * (q["p9"] + q["p10"] * t) + raw_p**3 * q["p11"]
    return o1 + o2 + d


def expected() -> list[tuple[float, float]]:
    """One (T_C, P_Pa) per reading the peer serves."""
    q = quant(peer.TRIM)
    out = []
    for raw_t, raw_p in peer.MEAS:
        t = comp_T(raw_t, q)
        out.append((t, comp_P(raw_p, t, q)))
    return out


def expected_ram() -> dict:
    """Same shape as read_ram(), so the oracle can be rendered and diffed directly."""
    e = expected()
    return dict(T=[x[0] for x in e], P=[x[1] for x in e], chip=0x50)


if __name__ == "__main__":
    for m, (t, p) in zip(peer.MEAS, expected(), strict=True):
        print(f"raw {m} -> T={t:.4f} C  P={p:.3f} Pa")
