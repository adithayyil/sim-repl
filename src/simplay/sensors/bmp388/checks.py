"""Check levels for the BMP388 scenario.

L0  the firmware's own status line
L1  the numbers are inside the sensor's operating range
L2  the numbers equal the datasheet's arithmetic (independent oracle)
L3  the SPI traffic matches the datasheet sequence the scenario prescribes

A check returns True when the run passes it, so a mutant is "caught" when a
check returns False.  Thresholds and clauses are the pre-registered ones; the
pressure tolerance is ~2% of the part's accuracy because the driver's float
helper and the datasheet reference do not agree bit-for-bit.
"""

from __future__ import annotations

from ...spi import observed, states, transactions
from . import oracle as ORACLE

T_RANGE = (15.0, 35.0)  # degC
P_RANGE = (90000.0, 105000.0)  # Pa
T_TOLERANCE = 0.01  # degC
P_TOLERANCE = 1.0  # Pa

RESET = (0x7E, 0xB6)  # write pair: command register, soft-reset command
WRITABLE = {0x1B, 0x1C, 0x1D, 0x1F, 0x7E}  # everything else is read-only


def L0(o: dict) -> bool:
    return o["status"] == "observed" and o["uart"].startswith("OK")


def L1(o: dict) -> bool:
    if not observed(o):
        return False
    r = o["ram"]
    # Non-empty on purpose: all() over an empty list is True, so a mutant that
    # skipped the measurement loop entirely would pass this level.
    return (
        bool(r["T"])
        and bool(r["P"])
        and all(T_RANGE[0] <= t <= T_RANGE[1] for t in r["T"])
        and all(P_RANGE[0] <= p <= P_RANGE[1] for p in r["P"])
    )


def L2(o: dict) -> bool:
    if not observed(o):
        return False
    r = o["ram"]
    expected = ORACLE.expected()
    return len(r["T"]) == len(r["P"]) == len(expected) and all(
        abs(t - e[0]) <= T_TOLERANCE and abs(p - e[1]) <= P_TOLERANCE
        for (t, p), e in zip(zip(r["T"], r["P"], strict=False), expected, strict=False)
    )


def _clauses(o: dict) -> dict[str, bool]:
    txs = transactions(o["bus"])
    first = txs[0] if txs else []
    reset_at = next(
        (
            i
            for i, t in enumerate(txs)
            if len(t) == 2 and t[0][0] == RESET[0] and t[1][0] == RESET[1]
        ),
        None,
    )
    after = txs[reset_at + 1 :] if reset_at is not None else []
    writes = [t for t in txs if not t[0][0] & 0x80]
    triggers = states(o["bus"])
    delays = (o["ram"] or {}).get("delays") or []

    # A burst write clocks complete (address, data) pairs and, per the stock
    # driver, one trailing byte; only the complete pairs are checked.
    def write_targets_ok() -> bool:
        for t in writes:
            for i in range(0, len(t) - len(t) % 2, 2):
                ctl = t[i][0]
                if ctl & 0x80 or ctl not in WRITABLE:
                    return False
        return True

    return {
        "chip_id_read_first": bool(first) and first[0][0] == 0x80 and len(first) == 3,
        "only_writable_registers_written": bool(txs) and write_targets_ok(),
        "soft_reset_after_status_read": reset_at not in (None, 0)
        and txs[reset_at - 1][0][0] == 0x83,
        "one_21byte_calibration_burst": sum(
            1 for t in after if t[0][0] == 0xB1 and len(t) - 2 == 21
        )
        == 1,
        "settings_at_each_trigger": len(triggers) == 2
        and all(
            len(s) >= 4 and s[:3] == (0x0B, 0x02, 0x04) and (s[3] & 0x33) == 0x13 for s in triggers
        ),
        "two_6byte_data_bursts": sum(1 for t in after if t[0][0] == 0x84 and len(t) - 2 == 6) == 2,
        "reset_delay_at_least_2ms": bool(delays) and delays[0] >= 2000,
    }


L3_CLAUSES = _clauses


def L3(o: dict) -> bool:
    if o["status"] != "observed" or not transactions(o["bus"]):
        return False
    return all(L3_CLAUSES(o).values())


CHECKS = {"L0": L0, "L1": L1, "L2": L2, "L3": L3}


def readings(ram: dict) -> list[str]:
    if not ram or "T" not in ram:
        return []
    return [f"T={t:.4f} C  P={p:.2f} Pa" for t, p in zip(ram["T"], ram["P"], strict=False)]


REGISTERS = {
    0x80: "CHIP_ID",
    0x82: "ERR",
    0x83: "STATUS",
    0x84: "DATA_P",
    0x87: "DATA_T",
    0xB1: "CALIB",
    0x1B: "PWR_CTRL",
    0x1C: "OSR",
    0x1D: "ODR",
    0x1F: "CONFIG",
    0x7E: "CMD",
}


def decode_tx(tx: list[tuple[int, int]]) -> str:
    """One SPI transaction as text; reads set bit 7 of the control byte and clock
    one dummy byte before the data (datasheet Sec. 5.3.2)."""
    if not tx:
        return "<empty>"
    control = tx[0][0]
    name = REGISTERS.get(control, f"0x{control:02x}")
    if control & 0x80:
        data = [miso for _, miso in tx[2:]]  # tx[1] is the dummy byte
        return f"R {name:<9} -> {' '.join(f'{b:02x}' for b in data[:8])}"
    pairs = [(tx[i][0], tx[i + 1][0]) for i in range(1, len(tx) - 1, 2)]
    body = " ".join(f"{REGISTERS.get(a, f'0x{a:02x}')}=0x{v:02x}" for a, v in pairs[:4])
    return f"W {name:<9} {body}"
