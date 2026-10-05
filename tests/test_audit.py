"""The recorded sweeps must re-evaluate to the verdicts they were written with.

The stored raw files were produced by the original one-off harness, so this is
the regression test that the refactored check code is the same function.
"""

from __future__ import annotations

import pytest

from simplay import analyze
from simplay.sensors import SENSOR_NAMES, load

# Frozen so a silent change in a check shows up as a test failure.
HEADLINES = {
    "bme280": dict(mutants=200, live=126, L0=16, L1=52, L2=103, L3=44, union=118),
    "bmp388": dict(mutants=300, live=99, L0=33, L1=43, L2=73, L3=54, union=95),
}


# The clause ablation behind the published reading of L3: its strength is not
# spread over the clauses, it sits in one scenario-state check.
ABLATION = {
    "bme280": dict(l3=44, strongest="settings_at_each_trigger", alone=33, drop_one=23),
    "bmp388": dict(l3=54, strongest="settings_at_each_trigger", alone=38, drop_one=16),
}


@pytest.mark.parametrize("name", SENSOR_NAMES)
def test_clause_ablation_is_reproducible(name: str) -> None:
    got = analyze.ablate(load(name))
    want = ABLATION[name]
    assert got["l3"] == want["l3"]
    assert got["strongest_clause"] == want["strongest"]
    assert got["strongest_alone"] == want["alone"]
    assert got["clauses"][want["strongest"]]["drop_one_loses"] == want["drop_one"]


@pytest.mark.parametrize("name", SENSOR_NAMES)
def test_stored_verdicts_are_reproduced(name: str) -> None:
    result = analyze.reproduce_check(load(name))
    assert result["mismatches"] == []
    observed = sum(
        1 for r in analyze.raw(load(name)).values() if r["status"] == "observed"
    )
    assert result["checked"] == observed <= result["runs"]


@pytest.mark.parametrize("name", SENSOR_NAMES)
def test_golden_passes_every_reported_check(name: str) -> None:
    sensor = load(name)
    gold = analyze.gold(sensor)
    assert gold["status"] == "observed"
    assert gold["uart"].startswith("OK")
    for c in sensor.checks:
        assert sensor.mod.CHECKS[c](gold), c


@pytest.mark.parametrize("name", SENSOR_NAMES)
def test_catch_rates_match_the_published_audit(name: str) -> None:
    sensor = load(name)
    want = HEADLINES[name]
    rows = analyze.rows(sensor)
    live = analyze.live(rows)
    assert len(rows) == want["mutants"]
    assert len(live) == want["live"]
    for c in ("L0", "L1", "L2", "L3"):
        assert sum(1 for r in live if c in r["caught"]) == want[c], c
    union = sum(1 for r in live if {"L2", "L3"} & set(r["caught"]))
    assert union == want["union"]


@pytest.mark.parametrize("name", SENSOR_NAMES)
def test_l3_is_exactly_its_clauses(name: str) -> None:
    """The bus check is a conjunction of named clauses; the decomposition must
    reproduce it for every recorded run, which is what the ablation relied on."""
    sensor = load(name)
    runs = analyze.raw(sensor)
    for mid, obs in runs.items():
        if obs["status"] != "observed":
            continue
        clauses = sensor.l3_clauses(obs)
        assert clauses, mid
        assert all(clauses.values()) == sensor.mod.CHECKS["L3"](obs), mid


@pytest.mark.parametrize("name", SENSOR_NAMES)
def test_a_run_the_checks_have_seen_catches_nothing(name: str) -> None:
    """The golden run is the calibration point: no reported level may fire on it."""
    sensor = load(name)
    gold = analyze.gold(sensor)
    assert all(sensor.mod.CHECKS[c](gold) for c in sensor.checks)
