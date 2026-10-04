"""Command line: build, generate, sweep, analyse, or open the playground."""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from pathlib import Path

from . import analyze, mutgen, sweep
from .sensors import SENSOR_NAMES, load


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="simplay", description=__doc__)
    p.add_argument("sensor", choices=SENSOR_NAMES)
    sub = p.add_subparsers(dest="cmd")

    sub.add_parser("golden", help="build and run the unmutated driver")

    g = sub.add_parser("gen", help="regenerate the mutant sample from the pinned source")
    g.add_argument("--n", type=int, required=True)
    g.add_argument("--seed", type=int, required=True)

    s = sub.add_parser("sweep", help="build and run every mutant")
    s.add_argument("-j", "--workers", type=int, default=8)
    s.add_argument("--wall", type=float, default=8.0, help="wall-clock seconds per run")
    s.add_argument("--limit", type=int)
    s.add_argument("--out", default="mut_raw.json")

    a = sub.add_parser("analyze", help="catch-rate table from recorded runs (no simulation)")
    a.add_argument("--raw", default="mut_raw.json")

    v = sub.add_parser("verify", help="recompute stored verdicts and diff them")
    v.add_argument("--live", action="store_true",
                   help="also re-simulate the first --limit mutants and diff against the recording")
    v.add_argument("--limit", type=int, default=25)
    v.add_argument("-j", "--workers", type=int, default=8)
    v.add_argument("--wall", type=float, default=8.0)

    sub.add_parser("play", help="interactive playground")

    args = p.parse_args(argv)
    sensor = load(args.sensor)

    if args.cmd == "gen":
        spec = mutgen.generate(sensor, args.n, args.seed)
        path = mutgen.save(sensor, spec)
        print(f"{len(spec['mutants'])} mutants over {spec['n_sites']} sites -> {path}")
        return 0

    if args.cmd == "sweep":
        sweep.sweep(args.sensor, workers=args.workers, wall=args.wall, limit=args.limit, out=args.out,
                    save_gold=args.limit is None)
        return 0

    if args.cmd == "analyze":
        print(analyze.report(sensor, args.raw))
        return 0

    if args.cmd == "verify":
        for raw in ("mut_raw.json", "mut_raw_repeat.json"):
            r = analyze.reproduce_check(sensor, raw)
            print(f"{raw}: {r['checked']}/{r['runs']} runs checked, "
                  f"{len(r['mismatches'])} verdict mismatches {r['mismatches'][:8]}")
        print("repeat sweep:", json.dumps(sweep.repeat_agree(args.sensor)))
        if args.live:
            tmp = Path(tempfile.mkdtemp(prefix="simplay-live-")) / "live_check.json"
            runs = sweep.sweep(args.sensor, workers=args.workers, wall=args.wall,
                               limit=args.limit, out=str(tmp), progress=False, save_gold=False)
            diff = analyze.diff_runs(sensor, runs, complete=args.limit is None)
            print(f"live rerun of {len(runs)} mutants against mut_raw.json: {len(diff)} field differences")
            for d in diff[:10]:
                print("  ", d)
            shutil.rmtree(tmp.parent, ignore_errors=True)
        return 0

    if args.cmd == "golden":
        obs = sweep.run_one(args.sensor, None, wall=20.0)
        (sensor.results / "gold.json").write_text(json.dumps(obs))
        print(f"status {obs['status']}  uart {obs['uart']!r}")
        for line in sensor.readings(obs["ram"]):
            print("  measured", line)
        for line in sensor.expected_readings():
            print("  datasheet", line)
        for c in sensor.checks:
            print(f"  {c} {'pass' if sensor.mod.CHECKS[c](obs) else 'FAIL'}")
        return 0

    if args.cmd == "play":
        from .shell import Shell

        Shell(args.sensor).cmdloop()
        return 0

    p.print_help()
    return 1