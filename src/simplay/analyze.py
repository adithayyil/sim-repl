"""Turning recorded runs into the audit table.

A mutant is *no-observable-difference* (NOD) when its UART output, SPI traffic
and firmware RAM match the golden run exactly.  Catch rates are reported over
the mutants that do differ, because a mutant nobody can observe is a statement
about the scenario, not about the checks.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from .harness import signature
from .sensors import Sensor
from .stats import cluster_bootstrap, fmt_rate, mcnemar, table

# Which pairs the headline table reports.  A sensor that does not implement all
# of them is skipped rather than reported against a level it lacks.
COMBOS = (("L2", "L3"), ("L0", "L1"))
PAIRS = (("L2", "L0"), ("L2", "L1"), ("L3", "L0"), ("L3", "L2"))


def load_json(path: Path) -> dict:
    return json.loads(Path(path).read_text())


def gold(sensor: Sensor) -> dict:
    return load_json(sensor.results / "gold.json")


def raw(sensor: Sensor, name: str = "mut_raw.json") -> dict:
    return load_json(sensor.results / name)


def rows(sensor: Sensor, name: str = "mut_raw.json") -> list[dict]:
    """One row per mutant: what changed, and which checks caught it.

    The sweep has to cover the sample: a `gen` with a different seed or a sweep
    that died half way would otherwise turn every number below into a KeyError,
    or worse, into rates over whichever mutants survived.
    """
    spec = load_json(sensor.results / "mutants.json")
    runs = raw(sensor, name)
    missing = [m["id"] for m in spec["mutants"] if m["id"] not in runs]
    if missing:
        raise SystemExit(
            f"{name} has no run for {len(missing)} of the {len(spec['mutants'])} mutants "
            f"in mutants.json (first: {missing[:5]}). Regenerate the sample with the "
            f"recorded seed, or re-run the sweep."
        )
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
    spec = load_json(sensor.results / "mutants.json")
    golden_run = gold(sensor)
    all_rows = rows(sensor, name)
    obs = [r for r in all_rows if r["status"] == "observed"]
    nod = [r for r in obs if r["nod"]]
    muts = live(all_rows)
    hangs = [r for r in all_rows if r["status"] != "observed"]
    checks = sensor.checks

    golden_line = " ".join(
        f"{c}{'ok' if sensor.mod.CHECKS[c](golden_run) else 'FAIL'}" for c in checks
    )
    lines = [
        f"{sensor.part}  ({sensor.blurb})",
        (
            f"driver {sensor.mod.DRIVER}"
            f" + {', '.join(sensor.extra_sources) or 'no extra sources'}   "
            f"mutants {len(all_rows)} (seed {spec['seed']}, {spec['n_sites']} sites)   file {name}"
        ),
        f"golden: {golden_run['status']}   checks on golden: {golden_line}",
        f"status: {dict(Counter(r['status'] for r in all_rows))}",
        f"no observable difference: {len(nod)}   live (differ from golden): {len(muts)}",
        "",
        "catch rates over live mutants:",
    ]
    for c in checks:
        hits = sum(1 for r in muts if c in r["caught"])
        lines.append(f"  {c:<3} {fmt_rate(hits, len(muts))}")
    for combo in COMBOS:
        if not all(c in checks for c in combo):
            continue
        hits = sum(1 for r in muts if set(combo) & set(r["caught"]))
        lines.append(f"  {'|'.join(combo):<3} {fmt_rate(hits, len(muts))}")

    lines += ["", "only-caught-by (missed by every other level):"]
    for c in checks:
        n = sum(1 for r in muts if r["caught"] == [c])
        lines.append(f"  {c:<3} {n}")
    escapees = [r for r in muts if not r["caught"]]
    lines.append(f"  none  {len(escapees)}")

    lines += ["", "paired comparisons (exact McNemar):"]
    for a, b in PAIRS:
        if a not in checks or b not in checks:
            continue
        ao = sum(1 for r in muts if a in r["caught"] and b not in r["caught"])
        bo = sum(1 for r in muts if b in r["caught"] and a not in r["caught"])
        lines.append(f"  {a} vs {b}: {a}-only {ao:3d}   {b}-only {bo:3d}   P={mcnemar(ao, bo):.4g}")

    lines += ["", "line-clustered bootstrap (mutants on one line are not independent):"]
    for c in checks:
        lo, hi = cluster_bootstrap([((r["file"], r["line"]), c in r["caught"]) for r in muts])
        k = sum(1 for r in muts if c in r["caught"])
        lines.append(f"  {c:<3} {k / max(1, len(muts)):.3f}  [{lo:.3f}, {hi:.3f}]")

    lines += ["", "by operator class (live mutants):"]
    body = []
    for cls in sorted({r["cls"] for r in muts}):
        pop = [r for r in muts if r["cls"] == cls]
        hits = [sum(1 for r in pop if c in r["caught"]) for c in checks]
        body.append([cls, str(len(pop)), *[str(h) for h in hits]])
    lines.append(table(body, ["class", "n", *checks]))

    if hangs:
        lines += ["", "not observed (excluded from every rate):"]
        for r in hangs:
            lines.append(f"  {r['id']} {r['file']}:{r['line']} {r['status']}")
    return "\n".join(lines)


def diff_runs(
    sensor: Sensor, runs: dict, name: str = "mut_raw.json", complete: bool = False
) -> list[tuple]:
    """Field-by-field differences between fresh runs and a recorded sweep.

    Only the mutants that were re-run are compared; pass ``complete`` after a
    full sweep to also report mutants the recording has but the rerun missed.
    Values are truncated: a differing field is a whole SPI log, not a number.
    """
    stored = raw(sensor, name)
    fields = ("status", "uart", "ram", "bus")
    out: list[tuple] = []
    for mid, r in runs.items():
        s = stored.get(mid)
        if s is None:
            out.append((mid, "id", "-", "absent from stored sweep"))
            continue
        for f in fields:
            if r.get(f) != s.get(f):
                out.append((mid, f, brief(r.get(f)), brief(s.get(f))))
    if complete:
        out += [(mid, "id", "-", "not re-run") for mid in sorted(stored.keys() - runs.keys())]
    return out


def brief(value) -> str:
    text = value if isinstance(value, str) else json.dumps(value, sort_keys=True)
    return text if len(text) <= 72 else f"{text[:69]}..."


def ablate(sensor: Sensor, name: str = "mut_raw.json") -> dict:
    """Leave-one-clause-out and clause-alone catch rates for L3, offline.

    The published reading of L3 came from this ablation: the check's strength is
    not spread evenly over its clauses, and saying "the bus check" without naming
    the dominant clause overstates what it measures.
    """
    runs = raw(sensor, name)
    golden = gold(sensor)
    golden_clauses = sensor.l3_clauses(golden)
    assert golden_clauses and all(golden_clauses.values()), "golden must satisfy every clause"
    live_rows = live(rows(sensor, name))
    live_ids = [r["id"] for r in live_rows]
    clauses = list(golden_clauses)

    def broken(mid: str) -> set[str]:
        return {c for c, ok in sensor.l3_clauses(runs[mid]).items() if not ok}

    full = {mid for mid in live_ids if broken(mid)}
    l2 = {r["id"] for r in live_rows if "L2" in r["caught"]}
    per_clause = {}
    for c in clauses:
        alone = {mid for mid in live_ids if c in broken(mid)}
        without = {mid for mid in live_ids if any(broken(mid) - {c})}
        per_clause[c] = dict(
            alone=len(alone), drop_one_loses=len(full - without), l3_only=len(alone - l2)
        )
    best = max(per_clause, key=lambda c: per_clause[c]["l3_only"])
    return dict(
        live=len(live_ids),
        l3=len(full),
        l2=len(l2),
        union=len(l2 | full),
        clauses=per_clause,
        strongest_clause=best,
        strongest_alone=per_clause[best]["alone"],
    )


def ablate_report(sensor: Sensor) -> str:
    a = ablate(sensor)
    lines = [
        f"{sensor.part}: L3 ablation over {a['live']} live mutants",
        f"  L3 catches {a['l3']}   L2 catches {a['l2']}   L2|L3 {a['union']}",
        "",
        f"  {'clause':34s} alone  drop-one loses  new-beyond-L2",
    ]
    for c, v in a["clauses"].items():
        lines.append(f"  {c:34s} {v['alone']:5d}  {v['drop_one_loses']:14d}  {v['l3_only']:14d}")
    lines.append("")
    lines.append(
        f"  strongest clause: {a['strongest_clause']} ({a['strongest_alone']} catches on its own)"
    )
    return "\n".join(lines)


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
    return dict(
        runs=len(stored),
        checked=sum(1 for r in stored.values() if r["status"] == "observed"),
        mismatches=mismatch,
    )
