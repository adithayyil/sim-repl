"""What the synthetic peers log, and how a run record turns into SPI data.

Every peer writes the same four kinds of line to the Renode log -- ``S`` and
``D`` around a transaction, ``B <mosi> <miso>`` per byte clocked, and ``M ...``
for the register state at a point of interest -- so parsing them belongs here
rather than in each sensor's checks.
"""

from __future__ import annotations


def transactions(bus: list[str]) -> list[list[tuple[int, int]]]:
    """The bus log as one list of (mosi, miso) byte pairs per chip-select."""
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


def states(bus: list[str]) -> list[tuple[int, ...]]:
    """The peer's ``M`` lines, as tuples of bytes."""
    return [tuple(int(x, 16) for x in m.split()[1:]) for m in bus if m.startswith("M ")]


def observed(o: dict) -> bool:
    """A run got far enough for its numbers to mean anything."""
    return o["status"] == "observed" and bool(o["ram"])
