"""BME280: Bosch BME280_SensorAPI (BSD-3), 64-bit fixed-point compensation path.

Scenario (fixed): init -> settings (T x2, P x8, H x1, normal mode) -> 2x
{ forced mode; delay; read T/P/H }.  The SPI peer is synthetic, built from
BST-BME280-DS002 rev 1.23; its trim values and raw ADC readings are made up.
"""

from __future__ import annotations

from . import checks as _c, oracle as _oracle

PART = "BME280"
BLURB = "Bosch BME280_SensorAPI, fixed-point compensation"
DATASHEET = "BST-BME280-DS002 rev 1.23"
ORACLE = _oracle

DRIVER = "bme280.c"
VENDOR = ("bme280.c", "bme280.h", "bme280_defs.h")
EXTRA_SOURCES = ()
CFLAGS = ()
DEFINES = ("-DBME280_64BIT_ENABLE",)

MUTGEN = dict(
    driver="bme280.c",
    defs="bme280_defs.h",
    define_prefix="BME280_",
    first_line=413,
    # the DOUBLE and 32BIT compensation branches: not compiled with the 64-bit macro
    excluded=((323, 364), (1122, 1241), (1326, 1387)),
    float_literals=False,
)

CHECKS = _c.CHECKS
L3_CLAUSES = _c.L3_CLAUSES
readings = _c.readings
decode_tx = _c.decode_tx


def _signed(v: int) -> int:
    return v - (1 << 32) if v & 0x80000000 else v


def read_ram(s) -> dict:
    """The firmware's own memory: chip id, compensated readings, return codes, delays."""

    def u32(name: str, i: int = 0) -> int:
        return int.from_bytes(s.read_memory(s.symbol(name) + 4 * i, 4), "little")

    n = u32("ndelays")
    return dict(
        chip=u32("chip_id_seen"),
        md=u32("meas_delay"),
        nd=n,
        T=[_signed(u32("Tc", i)) for i in (0, 1)],
        P=[_signed(u32("Pc", i)) for i in (0, 1)],
        H=[_signed(u32("Hc", i)) for i in (0, 1)],
        rc=[_signed(u32(nm)) for nm in ("r_init", "r_set", "r_delay")]
        + [_signed(u32("r_mode", i)) for i in (0, 1)]
        + [_signed(u32("r_get", i)) for i in (0, 1)],
        delays=[u32("delays", i) for i in range(min(n, 16))],
    )