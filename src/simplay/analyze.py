"""Turning recorded runs into the audit table.

A mutant is *no-observable-difference* (NOD) when its UART output, SPI traffic
and firmware RAM match the golden run exactly.  Catch rates are reported over
the mutants that do differ, because a mutant nobody can observe is a statement
about the scenario, not about the checks.
"""

from __future__ import annotations

import json
from pathlib import Path

from .harness import signature
from .sensors import Sensor
from .stats import cluster_bootstrap, fmt_rate, mcnemar, table, wilson


def load_json(path: Path) -> dict:
    return json.loads(Path(path).read_text())


def gold(sensor: Sensor) -> dict:
    return load_json(sensor.results / "gold.json")


def raw(sensor: Sensor, name: str = "mut_raw.json") -> dict:
    return load_json(sensor.results / name)


def rows(sensor: Sensor, name: str = "mut_raw.json") -> list[dict]:
    """One row per mutant: what changed, and which checks caught it."""
    spec = load_json(sensor.results / "mutants.json")
    runs = raw(sensor, name)
    golden = signature(gold(sensor))
    out = []
    for m in spec["mutants"]:
        r = runs[m["id"]]
        row = dict(m)
        row["status"] = r["status"]
        if r["status"] == "observed":
            row["nod"] = signature(r) == golden
            row["caught"] = [c for c in sensor.checks if not sensor.mod.CHECKS[c](r)]
            row["uart"] = r["uart"]
        out.append(row)
    return out


def live(rows: list[dict]) -> list[dict]:
    return [r for r in rows if r["status"] == "observed" and not r.get("nod")]


def report(sensor: Sensor, name: str = "mut_raw.json") -> str:
    from collections import Counter

    spec = load_json(sensor.results / "mutants.json")
    all_rows = rows(sensor, name)
    obs = [r for r in all_rows if r["status"] == "observed"]
    nod = [r for r in obs if r["nod"]]
    muts = live(all_rows)
    hangs = [r for r in all_rows if r["status"] != "observed"]

    lines = [
        f"{sensor.part}  ({sensor.blurb})",
        f"driver {sensor.mod.DRIVER} + {', '.join(sensor.extra_sources) or 'no extra sources'}   "
        f"mutants {len(all_rows)} (seed {spec['seed']}, {spec['n_sites']} sites)   file {name}",
        f"golden: {'observed' if gold(sensor)['status'] == 'observed' else gold(sensor)['status']}"
        f"   checks on golden: "
        + " ".join(f"{c}{'ok' if sensor.mod.CHECKS[c](gold(sensor)) else 'FAIL'}" for c in sensor.checks),
        f"status: {dict(Counter(r['status'] for r in all_rows))}",
        f"no observable difference: {len(nod)}   live (differ from golden): {len(muts)}",
        "",
        "catch rates over live mutants:",
    ]
    for c in sensor.checks:
        hits = sum(1 for r in muts if c in r["caught"])
        lines.append(f"  {c:<3} {fmt_rate(hits, len(muts))}")
    for combo, label in ((("L2", "L3"), "L2|L3"), (("L0", "L1"), "L0|L1")):
        if not all(c in sensor.checks for c in combo):
            continue
        hits = sum(1 for r in muts if set(combo) & set(r["caught"]))
        lines.append(f"  {label:<3} {fmt_rate(hits, len(muts))}")

    lines += ["", "only-caught-by (missed by every other level):"]
    for c in sensor.checks:
        n = sum(1 for r in muts if r["caught"] == [c])
        lines.append(f"  {c:<3} {n}")
    escapees = [r for r in muts if not r["caught"]]
    lines.append(f"  none  {len(escapees)}")

    lines += ["", "paired comparisons (exact McNemar):"]
    for a, b in (("L2", "L0"), ("L2", "L1"), ("L3", "L0"), ("L3", "L2")):
        if a not in sensor.checks or b not in sensor.checks:
            continue
        ao = sum(1 for r in muts if a in r["caught"] and b not in r["caught"])
        bo = sum(1 for r in muts if b in r["caught"] and a not in r["caught"])
        lines.append(f"  {a} vs {b}: {a}-only {ao:3d}   {b}-only {bo:3d}   P={mcnemar(ao, bo):.4g}")

    lines += ["", "line-clustered bootstrap (mutants on one line are not independent):"]
    for c in sensor.checks:
        lo, hi = cluster_bootstrap([((r["file"], r["line"]), c in r["caught"]) for r in muts])
        k = sum(1 for r in muts if c in r["caught"])
        lines.append(f"  {c:<3} {k / max(1, len(muts)):.3f}  [{lo:.3f}, {hi:.3f}]")

    lines += ["", "by operator class (live mutants):"]
    body = []
    for cls in sorted({r["cls"] for r in muts}):
        pop = [r for r in muts if r["cls"] == cls]
        hits = [sum(1 for r in pop if c in r["caught"]) for c in sensor.checks]
        body.append([cls, str(len(pop)), *[str(h) for h in hits]])
    lines.append(table(body, ["class", "n", *sensor.checks]))

    if hangs:
        lines += ["", "not observed (excluded from every rate):"]
        for r in hangs:
            lines.append(f"  {r['id']} {r['file']}:{r['line']} {r['status']}")
    return "\n".join(lines)


def diff_runs(sensor: Sensor, runs: dict, name: str = "mut_raw.json",
              complete: bool = False) -> list[tuple]:
    """Field-by-field differences between fresh runs and a recorded sweep.

    Only the mutants that were re-run are compared; pass ``complete`` after a
    full sweep to also report mutants the recording has but the rerun missed.
    """
    stored = raw(sensor, name)
    fields = ("status", "uart", "ram", "bus")
    out = []
    for mid, r in runs.items():
        s = stored.get(mid)
        if s is None:
            out.append((mid, "id", "-", "absent from stored sweep"))
            continue
        for f in fields:
            if r.get(f) != s.get(f):
                out.append((mid, f, r.get(f), s.get(f)))
    if complete:
        out += [(mid, "id", "-", "not re-run") for mid in stored.keys() - runs.keys()]
    return out


def reproduce_check(sensor: Sensor, name: str = "mut_raw.json") -> dict:
    """Compare stored per-run verdicts with freshly computed ones.

    The stored raw file was written by the original one-off harness; this is the
    regression test that the refactor still computes exactly the same verdicts.
    """
    stored = raw(sensor, name)
    mismatch = []
    for mid, r in stored.items():
        if r["status"] != "observed":
            continue
        for c in sensor.checks:
            if bool(r.get(c)) != bool(sensor.mod.CHECKS[c](r)):
                mismatch.append((mid, c))
    return dict(runs=len(stored), checked=sum(1 for r in stored.values() if r["status"] == "observed"),
                mismatches=mismatch)