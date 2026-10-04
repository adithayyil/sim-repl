"""Check levels for the BME280 scenario.

L0  the firmware's own status line
L1  the numbers are inside a plausible range for the synthetic peer
L2  the numbers equal the datasheet's arithmetic (independent oracle)
L3  the SPI traffic matches the datasheet sequence the scenario prescribes

A check returns True when the run passes it, so a mutant is "caught" when a
check returns False.  Thresholds and clauses are the pre-registered ones; L2x is
kept only because the preregistration and the first write-up mention it (the
stock Bosch driver fails it, see PREREG.md addendum B).
"""

from __future__ import annotations

from . import oracle as ORACLE

T_RANGE = (1500, 3500)  # 15.00 .. 35.00 degC, in centi-degrees
P_RANGE = (9000000, 10500000)  # 90000.00 .. 105000.00 Pa, in 1/100 Pa
H_RANGE = (20480, 81920)  # 20.00 .. 80.00 %RH, in Q22.10
P_TOLERANCE = 8  # 1/100 Pa: the stock driver truncates where the datasheet rounds

TRIGGER_STATE = (0x01, 0x51, 0x28)  # ctrl_hum, ctrl_meas, config at each forced-mode write
RESET = (0x60, 0xB6)  # write pair: reset register, soft-reset command


def _observed(o: dict) -> bool:
    return o["status"] == "observed" and bool(o["ram"])


def L0(o: dict) -> bool:
    return o["status"] == "observed" and o["uart"].startswith("OK")


def L1(o: dict) -> bool:
    if not _observed(o):
        return False
    r = o["ram"]
    return (
        all(T_RANGE[0] <= t <= T_RANGE[1] for t in r["T"])
        and all(P_RANGE[0] <= p <= P_RANGE[1] for p in r["P"])
        and all(H_RANGE[0] <= h <= H_RANGE[1] for h in r["H"])
    )


def L2(o: dict) -> bool:
    if not _observed(o):
        return False
    r = o["ram"]
    expected = ORACLE.expected_measurements()
    matched = all(
        t == e[0] and h == e[2] and abs(p - e[1]) <= P_TOLERANCE
        for (t, p, h), e in zip(zip(r["T"], r["P"], r["H"], strict=False), expected, strict=False)
    )
    return matched and len(r["T"]) == len(expected) and r["md"] == ORACLE.t_measure_max_us(2, 8, 1)


def L2x(o: dict) -> bool:
    """Strict L2, no pressure tolerance. The stock Bosch driver fails this."""
    if not _observed(o):
        return False
    r = o["ram"]
    exact = list(zip(r["T"], r["P"], r["H"], strict=False)) == ORACLE.expected_measurements()
    return exact and r["md"] == ORACLE.t_measure_max_us(2, 8, 1)


def transactions(bus: list[str]) -> list[list[tuple[int, int]]]:
    txs: list[list[tuple[int, int]]] = []
    cur: list[tuple[int, int]] | None = None
    for m in bus:
        if m == "S":
            cur = []
        elif m == "D":
            if cur:
                txs.append(cur)
            cur = None
        elif m.startswith("B ") and cur is not None:
            _, mosi, miso = m.split()
            cur.append((int(mosi, 16), int(miso, 16)))
    return txs


def _states(bus: list[str]) -> list[tuple[int, ...]]:
    return [tuple(int(x, 16) for x in m.split()[1:]) for m in bus if m.startswith("M ")]


def _clauses(o: dict) -> dict[str, bool]:
    txs = transactions(o["bus"])
    first = txs[0] if txs else []
    reset_at = next(
        (
            i
            for i, t in enumerate(txs)
            if len(t) >= 2 and t[0][0] == RESET[0] and t[1][0] == RESET[1]
        ),
        None,
    )
    after = txs[reset_at + 1 :] if reset_at is not None else []
    status_at = next((i for i, t in enumerate(after) if t[0][0] == 0xF3), None)
    calib_at = next((i for i, t in enumerate(after) if t[0][0] == 0x88), None)
    writes = [t[0][0] for t in after if not t[0][0] & 0x80]
    delays = (o["ram"] or {}).get("delays") or []

    def burst(addr: int, nbytes: int) -> bool:
        return any(t[0][0] == addr and len(t) - 1 == nbytes for t in after)

    return {
        "chip_id_read_first": bool(first) and first[0][0] == 0xD0,
        "soft_reset_written": reset_at is not None,
        "status_polled_after_reset": status_at is not None,
        "calibration_bursts_read": burst(0x88, 26) and burst(0xE1, 7),
        "calibration_after_status": status_at is not None and calib_at is not None and calib_at > status_at,
        "settings_at_each_trigger": _states(o["bus"]) == [TRIGGER_STATE, TRIGGER_STATE],
        "humidity_set_before_measuring": 0x72 in writes and 0x74 in writes and writes.index(0x72) <= writes.index(0x74),
        "two_8byte_data_bursts": sum(1 for t in after if t[0][0] == 0xF7 and len(t) - 1 == 8) == 2,
        "reset_delay_at_least_2ms": bool(delays) and delays[0] >= 2000,
    }


def L3_CLAUSES(o: dict) -> dict[str, bool]:
    return _clauses(o)


def L3(o: dict) -> bool:
    if o["status"] != "observed" or not transactions(o["bus"]):
        return False
    return all(L3_CLAUSES(o).values())


CHECKS = {"L0": L0, "L1": L1, "L2": L2, "L2x": L2x, "L3": L3}


def readings(ram: dict) -> list[str]:
    if not ram or "T" not in ram:
        return []
    return [
        f"T={t / 100:.2f} C  P={p / 100:.2f} Pa  H={h / 1024:.2f} %RH"
        for t, p, h in zip(ram["T"], ram["P"], ram["H"], strict=False)
    ]


# The BME280 puts the read flag in bit 7 of the register address itself, so the
# on-wire byte is the register name: 0xD0 is a read of CHIP_ID, 0x60 a write to RESET.
REGISTERS = {
    0xD0: "CHIP_ID",
    0xF3: "STATUS",
    0xF7: "DATA",
    0x88: "CALIB_TP",
    0xA1: "CALIB_H1",
    0xE1: "CALIB_H2",
    0x60: "RESET",
    0x72: "CTRL_HUM",
    0x74: "CTRL_MEAS",
    0xF5: "CONFIG",
}


def decode_tx(tx: list[tuple[int, int]]) -> str:
    """One SPI transaction as text."""
    if not tx:
        return "<empty>"
    control = tx[0][0]
    name = REGISTERS.get(control, f"0x{control:02x}")
    if control & 0x80:
        data = [miso for _, miso in tx[1:]]
        return f"R {name:<11} -> {' '.join(f'{b:02x}' for b in data[:8])}"
    pairs = [(tx[i][0], tx[i + 1][0]) for i in range(1, len(tx) - 1, 2)]
    body = " ".join(f"{REGISTERS.get(a, f'0x{a:02x}')}=0x{v:02x}" for a, v in pairs[:4])
    return f"W {name:<11} {body}"