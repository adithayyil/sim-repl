"""Running a batch of mutants: build, simulate, check, record."""

from __future__ import annotations

import json
import shutil
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from . import build, harness, mutgen
from .sensors import load


def write_json(path: Path, data: dict) -> None:
    """Write a recording in one go: a sweep killed mid-write must not truncate it."""
    tmp = path.with_suffix(path.suffix + ".partial")
    tmp.write_text(json.dumps(data))
    tmp.replace(path)


def scratch_dir() -> Path:
    """Prefer tmpfs: builds are small and the sweep is I/O bound."""
    root = Path("/dev/shm") if Path("/dev/shm").is_dir() else Path(tempfile.gettempdir())
    return Path(tempfile.mkdtemp(prefix="simplay-", dir=root))


def run_one(name: str, mutant: dict | None, wall: float) -> dict:
    """Build (optionally mutated) firmware, run it, and evaluate every check."""
    sensor = load(name)
    workdir = scratch_dir()
    try:
        build.write_repl(sensor, workdir)
        try:
            elf = build.compile_firmware(sensor, workdir, mutant)
        except build.BuildError as e:
            # Same shape as an observed run: signature() and the REPL index ram
            # and bus by key, so a failed build must carry them too.
            return dict(
                id=(mutant or {}).get("id", "golden"),
                status="compile_fail",
                uart="",
                bus=[],
                ram={},
                err=str(e)[:200],
            )
        obs = harness.observe(sensor, elf, workdir, wall=wall)
        if obs["status"] == "observed":
            obs.update({c: sensor.mod.CHECKS[c](obs) for c in sensor.mod.CHECKS})
        obs["id"] = (mutant or {}).get("id", "golden")
        return obs
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _job(args: tuple[str, dict, float]) -> dict:
    return run_one(*args)


def sweep(
    name: str,
    workers: int = 8,
    wall: float = 8.0,
    limit: int | None = None,
    out: str = "mut_raw.json",
    progress: bool = True,
    save_gold: bool = True,
) -> dict:
    sensor = load(name)
    mutants = mutgen.load(sensor)["mutants"]
    if limit:
        mutants = mutants[:limit]
    gold = run_one(name, None, wall=max(wall, 20.0))
    if save_gold:
        write_json(sensor.results / "gold.json", gold)
    results: dict[str, dict] = {}
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(_job, (name, m, wall)): m for m in mutants}
        for i, f in enumerate(as_completed(futures), 1):
            m = futures[f]
            try:
                r = f.result()
            except Exception as e:  # noqa: BLE001 - one bad mutant must not stop the sweep
                r = dict(
                    id=m["id"], status="runner_error", uart="", bus=[], ram={}, err=str(e)[:200]
                )
            results[m["id"]] = r
            if progress:
                print(f"  {i:4d}/{len(mutants)} {m['id']} {m['cls']:<8} {r['status']}", flush=True)
    out_path = Path(out)
    path = out_path if out_path.is_absolute() else sensor.results / out
    write_json(path, dict(sorted(results.items())))
    if progress:
        print(f"wrote {path} in {time.time() - t0:.0f}s")
    return results


def repeat_agree(name: str, other: str = "mut_raw.json") -> dict:
    """Compare two recorded sweeps field by field (determinism of the rig)."""
    a = json.loads((load(name).results / other).read_text())
    b = json.loads((load(name).results / "mut_raw_repeat.json").read_text())
    common = a.keys() & b.keys()
    fields = ("status", "uart", "ram", "bus")
    same = {k for k in common if all(a[k].get(f) == b[k].get(f) for f in fields)}
    return dict(compared=len(common), identical=len(same), differing=sorted(common - same))
