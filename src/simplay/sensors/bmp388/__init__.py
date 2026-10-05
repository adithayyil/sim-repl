"""BMP388: Bosch BMP3_SensorAPI (BSD-3), default floating-point compensation path.

Scenario (fixed): init -> settings (P x8, T x2, IIR 3, 50 Hz, forced mode) ->
2x { trigger; delay; read P/T }.  The SPI peer is synthetic, built from
BST-BMP388-DS001-07 rev 1.7; its trim values and raw ADC readings are made up.
"""

from __future__ import annotations

import struct

from . import checks as _c
from . import oracle as _oracle

PART = "BMP388"
BLURB = "Bosch BMP3_SensorAPI, floating-point compensation"
DATASHEET = "BST-BMP388-DS001-07 rev 1.7"
ORACLE = _oracle

DRIVER = "bmp3.c"
VENDOR = ("bmp3.c", "bmp3.h", "bmp3_defs.h")
EXTRA_SOURCES = ("stubs.c",)
CFLAGS = ("-mfloat-abi=soft",)
DEFINES = ()

MUTGEN = dict(
    driver="bmp3.c",
    defs="bmp3_defs.h",
    define_prefix="BMP3_",
    first_line=738,
    # the integer-compensation branch: not compiled on the default float path
    excluded=((2539, 2696),),
    float_literals=True,
)

# How many forced-mode rounds the firmware runs.  peer.py carries one MEAS entry
# per round and the firmware's Tc/Pc arrays are sized by it; tests pin the two
# against this.
MEASUREMENTS = 2

CHECKS = _c.CHECKS
L3_CLAUSES = _c.L3_CLAUSES
readings = _c.readings
decode_tx = _c.decode_tx


def _signed(v: int) -> int:
    return v - (1 << 32) if v & 0x80000000 else v


def read_ram(s) -> dict:
    """The firmware's own memory: chip id, compensated doubles, return codes, delays."""

    def u32(name: str, i: int = 0) -> int:
        return int.from_bytes(s.read_memory(s.symbol(name) + 4 * i, 4), "little")

    def f64(name: str, i: int) -> float:
        return struct.unpack("<d", bytes(s.read_memory(s.symbol(name) + 8 * i, 8)))[0]

    n = u32("ndelays")
    rounds = range(MEASUREMENTS)
    return dict(
        chip=u32("chip_id_seen"),
        nd=n,
        T=[f64("Tc", i) for i in rounds],
        P=[f64("Pc", i) for i in rounds],
        rc=[_signed(u32(nm)) for nm in ("r_init", "r_set")]
        + [_signed(u32("r_mode", i)) for i in rounds]
        + [_signed(u32("r_get", i)) for i in rounds],
        delays=[u32("delays", i) for i in range(min(n, 16))],
    )
