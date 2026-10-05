"""Registry of the audited sensors.

A sensor bundles a vendored driver, a firmware scenario, a datasheet oracle,
the synthetic SPI peer that replaces the real part, and its four check levels.
Everything sensor-specific lives in the per-sensor package; the harness only
knows about the interface declared by :class:`Sensor`.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

from .. import spi

SENSOR_NAMES = ("bme280", "bmp388")


class Sensor:
    """Everything needed to build, run and check one sensor scenario."""

    def __init__(self, name: str):
        mod: Any = importlib.import_module(f"{__name__}.{name}")
        self.name = name
        self.mod = mod
        self.root = Path(mod.__file__).parent
        self.part: str = mod.PART
        self.blurb: str = mod.BLURB
        self.datasheet: str = mod.DATASHEET
        self.firmware_main = "main.c"
        self.extra_sources: tuple[str, ...] = mod.EXTRA_SOURCES
        self.vendor: tuple[str, ...] = mod.VENDOR
        self.defines: tuple[str, ...] = mod.DEFINES
        self.mutgen: dict = mod.MUTGEN

    def path(self, *parts: str) -> Path:
        return self.root.joinpath(*parts)

    def source_file(self, name: str) -> Path:
        """Resolve a file named by a mutant: driver files live in vendor/.

        Mutants refer to sources by bare name ("bmp3.c"), so anything that reads
        a mutant's ``file`` field has to go through here.
        """
        vendored = self.root / "vendor" / name
        return vendored if vendored.exists() else self.path(name)

    @property
    def results(self) -> Path:
        return self.root / "results"

    @property
    def peer(self) -> Path:
        return self.root / "peer.py"

    @property
    def repl(self) -> Path:
        """Platform file for the STM32F4, as shipped by Renode."""
        return Path(__file__).resolve().parent.parent / "stm32f4.repl"

    # -- checks -----------------------------------------------------------
    @property
    def checks(self) -> tuple[str, ...]:
        """Check levels in reporting order (L2x is historical, never reported)."""
        return ("L0", "L1", "L2", "L3")

    def l3_clauses(self, obs: dict) -> dict[str, bool]:
        """Per-clause results of the bus check, for explaining a verdict."""
        if obs.get("status") != "observed":
            return {}
        return self.mod.L3_CLAUSES(obs)

    # -- presentation -----------------------------------------------------
    def transactions(self, bus: list[str]) -> list[list[tuple[int, int]]]:
        return spi.transactions(bus)

    def readings(self, ram: dict) -> list[str]:
        return self.mod.readings(ram)

    def expected_readings(self) -> list[str]:
        return self.mod.readings(self.mod.ORACLE.expected_ram())

    def decode_tx(self, tx: list[tuple[int, int]]) -> str:
        return self.mod.decode_tx(tx)


def load(name: str) -> Sensor:
    if name not in SENSOR_NAMES:
        raise SystemExit(f"unknown sensor {name!r}; known: {', '.join(SENSOR_NAMES)}")
    return Sensor(name)


__all__ = ["Sensor", "SENSOR_NAMES", "load"]
