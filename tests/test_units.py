"""Unit tests for the pieces the recorded results depend on."""

from __future__ import annotations

import json

from simplay import harness
from simplay.sensors import SENSOR_NAMES, load
from simplay.stats import cluster_bootstrap, mcnemar, wilson


def test_wilson_brackets_the_point_estimate() -> None:
    lo, hi = wilson(16, 126)
    assert lo < 16 / 126 < hi
    assert wilson(0, 10)[0] == 0.0


def test_mcnemar_is_symmetric_and_small_for_a_real_difference() -> None:
    assert mcnemar(0, 0) == 1.0
    assert mcnemar(47, 15) == mcnemar(15, 47)
    assert mcnemar(47, 15) < 0.001


def test_cluster_bootstrap_respects_clusters() -> None:
    one_line = [("c.c", 1, True)] * 20
    lo, hi = cluster_bootstrap([((f, ln), h) for f, ln, h in one_line], rounds=500)
    assert lo == hi == 1.0
    lo, hi = cluster_bootstrap([(("c.c", i), i % 2 == 0) for i in range(20)], rounds=500)
    assert lo < 0.5 < hi


def test_signature_ignores_key_order_but_not_values() -> None:
    a = dict(status="observed", uart="OK", bus=["S"], ram=dict(x=1, y=2))
    b = dict(status="observed", uart="OK", bus=["S"], ram=dict(y=2, x=1))
    c = dict(status="observed", uart="OK", bus=["S"], ram=dict(y=2, x=3))
    assert harness.signature(a) == harness.signature(b)
    assert harness.signature(a) != harness.signature(c)


def test_decoded_traffic_names_the_chip_id_read() -> None:
    for name in SENSOR_NAMES:
        sensor = load(name)
        bus = json.loads((sensor.results / "gold.json").read_text())["bus"]
        txs = sensor.transactions(bus)
        assert txs
        assert "CHIP_ID" in sensor.decode_tx(txs[0]), name
