"""An interactive playground for one sensor.

Everything the sweep recorded is browsable offline; `run` and `golden` build and
simulate on the spot, so you can point at a mutation, guess which check level
catches it, and find out.
"""

from __future__ import annotations

import cmd
import random
import shlex
import sys

from . import analyze, sweep
from .sensors import load

RESET = "\033[0m"
STYLES = {"dim": "\033[2m", "red": "\033[31m", "green": "\033[32m", "yellow": "\033[33m",
          "cyan": "\033[36m", "bold": "\033[1m"}


class CommandError(Exception):
    """A bad argument: report it and keep the prompt."""


class Colours:
    def __init__(self, on: bool):
        self.on = on

    def __call__(self, text: str, style: str) -> str:
        return f"{STYLES[style]}{text}{RESET}" if self.on else text


class Shell(cmd.Cmd):
    intro = ""
    prompt = "simplay> "

    def __init__(self, name: str):
        super().__init__()
        self.sensor = load(name)
        self.col = Colours(sys.stdout.isatty())
        self.rng = random.Random(7)
        self.score = [0, 0]
        self.records = self._load_records()
        self.rows = analyze.rows(self.sensor)
        self.by_id = {r["id"]: r for r in self.rows}
        self.gold = analyze.gold(self.sensor)

    def onecmd(self, line: str) -> bool | None:
        try:
            return super().onecmd(line)
        except CommandError as exc:
            self.say(self.col(str(exc), "red"))
            return False

    # -- helpers ----------------------------------------------------------
    def _load_records(self) -> dict:
        try:
            return analyze.raw(self.sensor)
        except FileNotFoundError:
            return {}

    def say(self, text: str = "") -> None:
        print(text)

    def dim(self, text: str) -> str:
        return self.col(text, "dim")

    def _row(self, mid: str) -> dict:
        if mid not in self.by_id:
            raise CommandError(self.col(f"no mutant {mid}", "red"))
        return self.by_id[mid]

    def _number(self, arg: str, default: int) -> int:
        try:
            return int(arg.strip())
        except ValueError:
            raise CommandError(self.col(f"{arg.strip()!r} is not a number", "red")) from None

    def _source(self, row: dict, context: int = 3) -> list[str]:
        lines = self.sensor.source_file(row["file"]).read_text().splitlines()
        lo = max(1, row["line"] - context)
        out = []
        for n in range(lo, min(len(lines), row["line"] + context) + 1):
            text = lines[n - 1]
            mark = ">" if n == row["line"] else " "
            body = self.col(text, "yellow") if n == row["line"] else self.dim(text)
            out.append(f"{mark} {self.dim(str(n).rjust(5))} {body}")
        return out

    def _verdict(self, obs: dict) -> list[str]:
        out = []
        for c in self.sensor.checks:
            ok = self.sensor.mod.CHECKS[c](obs)
            word = "pass" if ok else self.col("CAUGHT", "red")
            out.append(f"    {c} {self.dim(self._label(c)):<22} {word}")
        return out

    def _label(self, c: str) -> str:
        return {
            "L0": "firmware says OK",
            "L1": "values plausible",
            "L2": "matches datasheet",
            "L3": "bus + config",
        }.get(c, c)

    def _catch_line(self, obs: dict, golden: bool = False) -> str:
        caught = [c for c in self.sensor.checks if not self.sensor.mod.CHECKS[c](obs)]
        if obs["status"] != "observed":
            return self.col(f"no observable result ({obs['status']})", "dim")
        if not caught:
            return self.col("passed every check" if golden else "escaped every check",
                            "green" if golden else "red")
        return "caught by " + ", ".join(caught)

    def _print_run(self, row: dict, obs: dict) -> None:
        self.say()
        for line in self._source(row):
            self.say("  " + line)
        self.say(f"    {self.dim(row['id'] + ' ' + row['cls'])} {row['orig']} -> "
                 f"{self.col(row['repl'], 'cyan')}")
        self.say()
        self.say(f"  status  {obs['status']}   uart {obs.get('uart', '')!r}")
        for line in self.sensor.readings(obs.get("ram") or {}):
            self.say(f"    measured {line}")
        for line in self.sensor.expected_readings():
            self.say(f"    {self.dim('datasheet')} {line}")
        self.say()
        for line in self._verdict(obs):
            self.say(line)
        clauses = self.sensor.l3_clauses(obs)
        if clauses and not self.sensor.mod.CHECKS["L3"](obs):
            broken = [k for k, v in clauses.items() if not v]
            self.say(f"    L3 clauses failed: {self.col(', '.join(broken), 'red')}")
        self.say(f"  {self._catch_line(obs, golden=row.get('id') == 'golden')}")

    # -- commands ---------------------------------------------------------
    def do_help(self, arg: str) -> None:
        if arg:
            return super().do_help(arg)
        self.say(
            "golden              run the unmutated driver and show every check\n"
            "list [n]            mutants with the checks that caught them (recorded sweep)\n"
            "show <id>           source context for a mutation\n"
            "run <id>            build and run one mutant now, live\n"
            "play [n]            guess which checks catch n random mutants\n"
            "bus <id>            decoded SPI traffic of a recorded run\n"
            "escapes             mutants no check caught\n"
            "stats               full catch-rate table\n"
            "clauses <id>        which L3 clause fires for a recorded run\n"
            "score               how your guesses have gone\n"
            "quit                leave\n"
        )

    def do_golden(self, arg: str) -> None:
        self.say(self.dim("building and running the stock driver ..."))
        obs = sweep.run_one(self.sensor.name, None, wall=20.0)
        self._print_run(dict(id="golden", cls="stock", file=self.sensor.mod.DRIVER, line=1,
                             orig="", repl="", caught=[]), obs)

    def do_list(self, arg: str) -> None:
        n = self._number(arg, 40)
        self.say(f"{'id':<6}{'class':<9}{'site':<18}{'change':<18}caught by")
        for row in self.rows[:n]:
            site = f"{row['file']}:{row['line']}"
            caught = ", ".join(row.get("caught", [])) or self.dim(
                "nothing" if row.get("status") == "observed" else row["status"])
            self.say(f"{row['id']:<6}{row['cls']:<9}{site:<18}"
                     f"{row['orig'] + '->' + row['repl']:<18}{caught}")

    def do_show(self, arg: str) -> None:
        row = self._row(arg.strip())
        for line in self._source(row, context=4):
            self.say(line)

    def do_run(self, arg: str) -> None:
        row = self._row(arg.strip())
        self.say(self.dim("building and running ..."))
        obs = sweep.run_one(self.sensor.name, dict(row), wall=8.0)
        self._print_run(row, obs)

    def do_bus(self, arg: str) -> None:
        mid = arg.strip()
        obs = self.gold if mid in ("", "golden") else self.records.get(mid)
        if obs is None:
            raise CommandError(self.col(f"no recorded run for {mid}", "red"))
        if obs["status"] != "observed":
            raise CommandError(self.col(f"{mid or 'golden'} is {obs['status']}", "red"))
        self.say(f"{mid or 'golden'}  {len(obs['bus'])} log lines")
        self.say()
        for i, line in enumerate(self.sensor.transactions(obs["bus"])):
            self.say(f"  {i:3d}  {self.sensor.decode_tx(line)}")

    def do_clauses(self, arg: str) -> None:
        obs = self.records.get(arg.strip())
        if obs is None:
            raise CommandError(self.col(f"no recorded run for {arg.strip()}", "red"))
        for name, ok in self.sensor.l3_clauses(obs).items():
            mark = self.col("ok    ", "green") if ok else self.col("broken", "red")
            self.say(f"  {mark}  {name}")

    def do_escapes(self, arg: str) -> None:
        for row in self.rows:
            if row["status"] == "observed" and not row.get("nod") and not row.get("caught"):
                self.say(f"  {row['id']} {row['file']}:{row['line']} "
                         f"{row['orig']} -> {row['repl']}")
                for line in self._source(row, context=1):
                    self.say("   " + line)

    def do_stats(self, arg: str) -> None:
        self.say(analyze.report(self.sensor))

    def do_play(self, arg: str) -> None:
        rounds = self._number(arg, 5)
        pool = [r for r in self.rows if r["status"] == "observed" and not r.get("nod")]
        if not pool:
            raise CommandError(self.col("no recorded runs; run a sweep first", "red"))
        for _ in range(rounds):
            row = self.rng.choice(pool)
            self.say()
            self.say(self.col(f"{row['id']}  {row['cls']}  {row['file']}:{row['line']}", "bold"))
            for line in self._source(row):
                self.say(line)
            self.say(f"  {row['orig']} -> {self.col(row['repl'], 'cyan')}")
            try:
                guess = input("  which levels catch it? [e.g. L2 L3, or none] ").strip().upper()
            except (EOFError, KeyboardInterrupt):
                self.say()
                raise CommandError(self.col("stopping", "dim")) from None
            guessed = {c.upper() for c in shlex.split(guess.replace(",", " "))}
            actual = {c for c in self.sensor.checks if not self.records[row["id"]][c]}
            hit = guessed == actual
            self.score[0] += 1
            self.score[1] += int(hit)
            self.say("  " + self._catch_line(self.records[row["id"]])
                     + ("   " + self.col("correct", "green") if hit else
                        "   " + self.col("wrong", "red") + f" (it was {sorted(actual) or 'none'})"))

    def do_score(self, arg: str) -> None:
        self.say(f"{self.score[1]}/{self.score[0]} guesses correct")

    def do_quit(self, arg: str) -> bool:
        return True

    do_exit = do_quit
    do_EOF = do_quit

    def emptyline(self) -> bool:
        return False

    def default(self, line: str) -> None:
        self.say(self.col(f"unknown command {line!r}; try help", "red"))


def main() -> None:  # pragma: no cover - convenience entry point
    Shell(sys.argv[1] if len(sys.argv) > 1 else "bme280").cmdloop()
