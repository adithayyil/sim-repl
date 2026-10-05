"""Tests that build firmware and drive the real simulator.

These need arm-none-eabi-gcc and the Simantic engine, so they are opt-in:

    SIMPLAY_LIVE=1 uv run pytest tests/test_live.py

CI runs the offline suite only.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from helpers import drive

from simplay import analyze, sweep
from simplay.sensors import SENSOR_NAMES, load

ROOT = Path(__file__).resolve().parents[1]
LIVE = bool(os.environ.get("SIMPLAY_LIVE"))
pytestmark = [pytest.mark.live, pytest.mark.skipif(not LIVE, reason="set SIMPLAY_LIVE=1")]


@pytest.mark.live
@pytest.mark.parametrize("name", SENSOR_NAMES)
def test_sweep_writes_a_recording_the_analysis_can_read(name: str, tmp_path: Path) -> None:
    """Regression: sweep() itself had no test; it is what produces every result."""
    out = tmp_path / "slice.json"
    runs = sweep.sweep(
        name, workers=2, wall=12.0, limit=3, out=str(out), progress=False, save_gold=False
    )
    assert len(runs) == 3
    assert json.loads(out.read_text()).keys() == runs.keys()
    assert load(name).results.joinpath("gold.json").exists(), "save_gold=False must not write"
    for mid, obs in runs.items():
        assert obs["id"] == mid
        assert obs["status"] == "observed", obs.get("err")


@pytest.mark.live
@pytest.mark.parametrize("name", SENSOR_NAMES)
def test_golden_run_passes_every_check(name: str) -> None:
    obs = sweep.run_one(name, None, wall=20.0)
    assert obs["status"] == "observed", obs.get("err")
    assert all(load(name).mod.CHECKS[c](obs) for c in ("L0", "L1", "L2", "L3"))
    assert obs["uart"] == "OK\nDONE"


@pytest.mark.live
def test_golden_command_prints_the_stock_driver_source() -> None:
    out = drive("bme280", "golden")
    first = load("bme280").source_file("bme280.c").read_text().splitlines()[0]
    assert first.strip() in out, "golden should show the stock driver it built"
    assert "passed every check" in out


@pytest.mark.live
def test_run_command_reproduces_the_recorded_verdict() -> None:
    name = "bmp388"
    row = next(r for r in analyze.rows(load(name)) if r.get("caught") == ["L2"])
    out = drive(name, f"run {row['id']}")
    assert "caught by L2" in out


@pytest.mark.live
def test_installed_console_script_works() -> None:
    r = subprocess.run(
        [sys.executable, "-m", "simplay.cli", "bme280", "analyze"],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert r.returncode == 0, r.stderr[-400:]
    assert "catch rates over live mutants" in r.stdout
