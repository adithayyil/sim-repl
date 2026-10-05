"""The mutant sample must be exactly reproducible from the pinned driver source.

If this fails, the mutants no longer describe the vendored code and every stored
result is stale.
"""

from __future__ import annotations

import json

import pytest

from simplay import mutgen
from simplay.sensors import SENSOR_NAMES, load

CASES = {"bme280": (200, 20261004), "bmp388": (300, 20261005)}


@pytest.mark.parametrize("name", SENSOR_NAMES)
def test_regenerated_mutants_match_the_recorded_sample(name: str) -> None:
    sensor = load(name)
    n, seed = CASES[name]
    recorded = json.loads((sensor.results / "mutants.json").read_text())
    assert (recorded["seed"], len(recorded["mutants"]), recorded["n_sites"]) == (
        seed,
        n,
        recorded["n_sites"],
    )

    fresh = mutgen.generate(sensor, n, seed)
    assert fresh["n_sites"] == recorded["n_sites"]
    assert fresh["mutants"] == recorded["mutants"]


@pytest.mark.parametrize("name", SENSOR_NAMES)
def test_every_mutant_applies_to_the_pinned_source(name: str) -> None:
    sensor = load(name)
    for m in mutgen.load(sensor)["mutants"]:
        src = sensor.source_file(m["file"]).read_text()
        assert src[m["start"] : m["end"]] == m["orig"], m["id"]


@pytest.mark.parametrize("name", SENSOR_NAMES)
def test_mutant_sites_are_inside_the_compiled_region(name: str) -> None:
    sensor = load(name)
    excluded = sensor.mutgen["excluded"]
    driver = sensor.mutgen["driver"]
    for s in mutgen.sites_in(sensor):
        if s["file"] != driver:
            continue  # define constants live in the header
        assert s["line"] >= sensor.mutgen["first_line"], s
        assert not any(a <= s["line"] <= b for a, b in excluded), s
