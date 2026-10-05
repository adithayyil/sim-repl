"""Observing a firmware run: UART, the peer's SPI log, and the firmware's own
RAM state. Everything the checks see comes from here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _bus_lines(messages: list[dict]) -> list[str]:
    return [
        m["message"]
        for m in messages
        if m["message"] in ("S", "D") or m["message"][:2] in ("B ", "M ")
    ]


def observe(
    sensor: Any,
    elf: Path,
    workdir: Path,
    wall: float = 20.0,
    show_logs: bool = False,
) -> dict:
    """Run one ELF to completion (or wall-clock timeout) and record what happened.

    The firmware's main() prints DONE when the scenario ends; a mutant that never
    gets there is recorded as `no_completion` rather than failing the run, so
    hangs stay countable instead of being lost.
    """
    from simantic import ExpectTimeout, Sim

    out: dict = {"status": "observed", "uart": "", "bus": [], "ram": {}, "err": None}
    try:
        with Sim(
            elf=str(elf),
            repl=str(workdir / "stm32f4.repl"),
            uart="usart2",
            show_logs=show_logs,
            cwd=str(workdir),
        ) as s:
            try:
                s.expect("DONE", timeout=wall)
            except ExpectTimeout:
                # A hang is the mutant's verdict, not a rig failure.  Whatever is
                # printed up to the wall clock is still worth recording below.
                out["status"] = "no_completion"
            except Exception as e:  # noqa: BLE001 - an API failure is not a mutant hang
                out["status"] = "sim_error"
                out["err"] = f"expect: {type(e).__name__}: {e}"[:200]
            try:
                s.run_for(0.001)
                out["uart"] = s.read_uart(from_start=True).replace("\r", "").strip()
                out["bus"] = _bus_lines(s.logs(from_start=True))
                out["ram"] = sensor.mod.read_ram(s)
            except Exception as e:  # noqa: BLE001 - reading a hung session can fail too
                # Keep a recorded hang counted as a hang; only escalate the run
                # when the session was supposed to complete.
                out["err"] = f"read: {type(e).__name__}: {e}"[:200]
                if out["status"] == "observed":
                    out["status"] = "sim_error"
    except Exception as e:  # noqa: BLE001 - a broken rig must not kill a sweep
        out["status"] = "sim_error"
        out["err"] = str(e)[:200]
    return out


def signature(obs: dict) -> tuple:
    """What the checks compare mutants against: UART, bus bytes, firmware RAM.

    Two runs with the same signature are indistinguishable from outside the DUT.
    """
    ram = tuple(sorted((k, str(v)) for k, v in obs["ram"].items()))
    return (obs["uart"], tuple(obs["bus"]), ram)
