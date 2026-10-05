"""Building firmware: apply a mutant, compile it, write the Renode platform file."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from .sensors import Sensor


class BuildError(RuntimeError):
    pass


def gcc() -> str:
    found = os.environ.get("ARM_GCC") or shutil.which("arm-none-eabi-gcc")
    if not found:
        raise BuildError("arm-none-eabi-gcc not found (nix develop, or set ARM_GCC)")
    return found


def apply_mutant(sensor: Sensor, workdir: Path, mutant: dict | None) -> None:
    """Copy the driver + firmware into `workdir`, applying `mutant` to the driver."""
    workdir.mkdir(parents=True, exist_ok=True)
    for name in sensor.vendor:
        shutil.copy(sensor.source_file(name), workdir / name)
    for name in sensor.extra_sources:
        shutil.copy(sensor.path("firmware", name), workdir / name)
    shutil.copy(sensor.path("firmware", sensor.firmware_main), workdir / sensor.firmware_main)
    shutil.copy(sensor.path("firmware", "link.ld"), workdir / "link.ld")
    if mutant is None:
        return

    target = workdir / mutant["file"]
    text = target.read_text()
    found = text[int(mutant["start"]) : int(mutant["end"])]
    if found != mutant["orig"]:
        raise BuildError(f"mutant {mutant['id']} does not match the pinned source at {found!r}")
    target.write_text(text[: int(mutant["start"])] + mutant["repl"] + text[int(mutant["end"]) :])


def compile_firmware(sensor: Sensor, workdir: Path, mutant: dict | None = None) -> Path:
    apply_mutant(sensor, workdir, mutant)
    cmd = [
        gcc(),
        "-mcpu=cortex-m4",
        "-mthumb",
        *sensor.mod.CFLAGS,
        "-O1",
        "-ffreestanding",
        "-fno-builtin",
        "-nostdlib",
        *sensor.defines,
        "-I.",
        "-T",
        "link.ld",
        sensor.firmware_main,
        sensor.mod.DRIVER,
        *sensor.extra_sources,
        "-o",
        "sim.elf",
        "-lgcc",
    ]
    r = subprocess.run(cmd, cwd=workdir, capture_output=True, text=True)
    if r.returncode != 0:
        raise BuildError(r.stderr[-400:])
    return workdir / "sim.elf"


def write_repl(sensor: Sensor, workdir: Path) -> Path:
    """Renode platform file: the STM32F4 with the synthetic peer on PA4 / SPI1."""
    platform = sensor.repl.read_text()
    peer = f"{sensor.name}0"
    stanza = (
        f'\n{peer}: SPI.ScriptedSpiSlave @ spi1\n    file: "{sensor.peer}"\n'
        f"\ngpioPortA:\n    4 -> {peer}@0\n"
    )
    out = workdir / "stm32f4.repl"
    out.write_text(platform + stanza)
    return out
