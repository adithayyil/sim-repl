"""End-to-end tests: every command of the playground and the CLI, both sensors.

The offline ones run in CI. The `live` ones build and simulate, so they need
arm-none-eabi-gcc and the Simantic engine; set SIMPLAY_LIVE=1 to include them.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest
import simantic

from simplay import analyze, build, harness, mutgen, sweep
from simplay.cli import main as cli_main
from simplay.sensors import SENSOR_NAMES, load
from simplay.shell import Shell

ROOT = Path(__file__).resolve().parents[1]
LIVE = bool(os.environ.get("SIMPLAY_LIVE"))


def drive(sensor: str, script: str, stdin: str = "") -> str:
    """Feed `script` to the playground the way a user would."""
    shell = Shell(sensor)
    buf = io.StringIO()
    with redirect_stdout(buf):
        for line in script.splitlines():
            shell.onecmd(line)
    return buf.getvalue()


# -- offline: no simulator needed ------------------------------------------
@pytest.mark.parametrize("name", SENSOR_NAMES)
def test_every_offline_command_runs(name: str) -> None:
    rows = analyze.rows(load(name))
    caught = next((r["id"] for r in rows if r.get("caught")), None)
    out = drive(name, "\n".join([
        "help",
        "list 5",
        "stats",
        "escapes",
        "bus",
        "bus golden",
        f"show {caught}",
        f"clauses {caught}",
        "score",
        "nonsense",
    ]))
    for expected in ("catch rates", "live (differ from golden)", f"{caught}"):
        assert expected in out, f"{name}: {expected!r} missing from the playground output"


@pytest.mark.parametrize("name", SENSOR_NAMES)
def test_source_context_points_at_the_vendored_driver(name: str) -> None:
    """Regression: mutants name driver files bare, which live under vendor/."""
    sensor = load(name)
    row = analyze.rows(sensor)[0]
    assert sensor.source_file(row["file"]).exists()
    out = drive(name, f"show {row['id']}")
    assert str(row["line"]) in out


@pytest.mark.parametrize("name", SENSOR_NAMES)
def test_unknown_mutant_is_a_clean_error(name: str) -> None:
    """A typo must not end the session: the next command still runs."""
    caught = next(r for r in analyze.rows(load(name)) if r.get("caught"))
    out = drive(name, f"show m999\nshow {caught['id']}")
    assert "no mutant m999" in out
    assert str(caught["line"]) in out, "the second command should still print source"


@pytest.mark.parametrize("name", SENSOR_NAMES)
def test_unknown_run_id_keeps_the_session_alive(name: str) -> None:
    out = drive(name, "bus m999\nlist 2")
    assert "no recorded run for m999" in out
    assert "caught by" in out


def test_a_run_that_never_completed_is_a_clean_error() -> None:
    """Regression: such a record has no bus log, and do_bus used to raise KeyError."""
    sensor = load("bme280")
    stuck = next(r["id"] for r in analyze.rows(sensor) if r["status"] != "observed")
    out = drive("bme280", f"bus {stuck}\nlist 2")
    assert "is no_completion" in out
    assert "caught by" in out


def test_no_mutation_site_is_inside_a_string_literal() -> None:
    """The tokenizer has no string rule, so a site inside a literal would be a
    mutant of the text rather than of the code. None of the 1,047 candidate
    sites is one; if a pinned driver changes, this is the test that says so."""
    for name in SENSOR_NAMES:
        sensor = load(name)
        for site in mutgen.sites_in(sensor):
            window = sensor.source_file(site["file"]).read_text()[: site["start"]]
            quotes = [i for i, c in enumerate(window) if c == '"' and window[i - 1] != "\\"]
            assert len(quotes) % 2 == 0, f"{name} {site['file']}:{site['line']}"


def test_a_word_where_a_number_belongs_is_a_clean_error() -> None:
    out = drive("bme280", "list lots\nscore")
    assert "'lots' is not a number" in out
    assert "0/0 guesses correct" in out


def test_the_game_stops_cleanly_when_input_runs_out(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression: input() raises EOFError, which used to leave a traceback."""

    def no_input(prompt: str = "") -> str:
        raise EOFError

    monkeypatch.setattr("builtins.input", no_input)
    out = drive("bme280", "play 1")
    assert "stopping" in out
    assert "Traceback" not in out


@pytest.mark.parametrize("name", SENSOR_NAMES)
def test_cli_analyze_and_verify(name: str, capsys: pytest.CaptureFixture) -> None:
    assert cli_main([name, "analyze"]) == 0
    assert cli_main([name, "verify"]) == 0
    out = capsys.readouterr().out
    assert "0 verdict mismatches" in out
    assert "identical" in out


def test_cli_rejects_an_unknown_sensor() -> None:
    with pytest.raises(SystemExit):
        cli_main(["bme999", "analyze"])


@pytest.mark.parametrize("name", SENSOR_NAMES)
def test_mutant_rewrites_the_recorded_source(name: str, tmp_path: Path) -> None:
    """The mutation must apply cleanly to the pinned driver, or nothing is honest."""
    sensor = load(name)
    mutant = analyze.rows(sensor)[0]
    build.apply_mutant(sensor, tmp_path, mutant)
    text = (tmp_path / mutant["file"]).read_text()
    assert mutant["repl"] in text
    assert mutant["orig"] not in text or mutant["repl"] != mutant["orig"]


def test_platform_file_names_the_peer_after_the_sensor(tmp_path: Path) -> None:
    """A BMP388 run whose Renode log calls the sensor bme0 misleads whoever reads it."""
    for name in SENSOR_NAMES:
        sensor = load(name)
        repl = build.write_repl(sensor, tmp_path).read_text()
        stanza = repl[repl.index("SPI.ScriptedSpiSlave") - 20 :]
        assert f"\n{name}0: SPI.ScriptedSpiSlave" in stanza
        assert f"4 -> {name}0@0" in stanza
        assert "bme0" not in repl.replace(str(sensor.peer), "")


def test_a_truncated_state_log_does_not_crash_the_bus_check() -> None:
    """Regression: the BMP388 trigger clause indexed s[3] on a state the peer may log short."""
    from simplay.sensors.bmp388 import checks as bmp

    sensor = load("bmp388")
    bus = list(analyze.gold(sensor)["bus"])
    i = next(i for i, m in enumerate(bus) if m.startswith("M "))
    bus[i] = "M 0b 02 04"  # prefix matches the expected settings, fourth byte gone
    clauses = bmp.L3_CLAUSES(dict(analyze.gold(sensor), bus=bus))
    assert clauses["settings_at_each_trigger"] is False
    assert bmp.L3(dict(analyze.gold(sensor), bus=bus)) is False


def test_a_sweep_that_does_not_cover_the_sample_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """A new seed with an old sweep would otherwise report rates over whatever survived."""
    sensor = load("bme280")
    real = analyze.load_json

    def truncated(path: Path) -> dict:
        if not path.name.startswith("mut_raw"):
            return real(path)
        data = real(path)
        return {k: v for i, (k, v) in enumerate(sorted(data.items())) if i < 5}

    monkeypatch.setattr(analyze, "load_json", truncated)
    with pytest.raises(SystemExit, match="no run for"):
        analyze.rows(sensor)


def test_golden_command_keeps_the_recording_when_the_run_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A broken golden would turn every mutant into a live one."""
    sensor = load("bme280")
    before = (sensor.results / "gold.json").read_bytes()
    monkeypatch.setattr(sweep, "run_one", lambda *a, **k: dict(
        status="sim_error", uart="", bus=[], ram={}, err="rig is on fire"))
    assert cli_main(["bme280", "golden"]) == 1
    assert (sensor.results / "gold.json").read_bytes() == before


class _FakeSim:
    """Just enough Sim to make observe() classify the failure it is meant to see."""

    raises: Exception = simantic.ExpectTimeout("DONE", "", 0.0)

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def expect(self, pattern: str, timeout: float = 30) -> None:
        raise self.raises

    def run_for(self, seconds: float) -> None:
        pass

    def read_uart(self, from_start: bool = False) -> str:
        return ""

    def logs(self, from_start: bool = False) -> list[dict]:
        return []

    def read_memory(self, addr: int, n: int) -> bytes:
        return b"\x00" * n

    def symbol(self, name: str) -> int:
        return 0


@pytest.mark.parametrize("failure, expected", [
    (simantic.ExpectTimeout("DONE", "", 0.0), "no_completion"),
    (ValueError("renamed API"), "sim_error"),
])
def test_only_a_timeout_counts_as_a_hang(
    monkeypatch: pytest.MonkeyPatch, failure: Exception, expected: str
) -> None:
    """Regression: any exception from expect() used to be recorded as a mutant hang."""
    sensor = load("bme280")
    fake = type("Fake", (_FakeSim,), {"raises": failure})
    monkeypatch.setattr(simantic, "Sim", fake)
    obs = harness.observe(sensor, Path("sim.elf"), Path("/tmp"), wall=0.1)
    assert obs["status"] == expected


# -- live: needs the ARM toolchain and the Simantic engine -------------------
def test_peers_stay_inside_ironpython() -> None:
    """The SPI peers run inside Renode's IronPython 2.7, so a py3-only construct
    would fail at simulation time with a stack trace instead of a clear error."""
    import ast

    for name in SENSOR_NAMES:
        peer = load(name).peer.read_text()
        tree = ast.parse(peer)
        assert not any(isinstance(n, ast.JoinedStr) for n in ast.walk(tree)), f"{name} f-string"
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                a = node.args
                assert not (a.posonlyargs or a.kwonlyargs)
                assert all(x.annotation is None for x in
                           [*a.args, *a.posonlyargs, *a.kwonlyargs])
                assert node.returns is None
        for banned in ("yield from", "nonlocal ", ":="):
            assert banned not in peer, f"{name} peer uses {banned!r}"
        assert peer.startswith("#"), f"{name} peer should say what it is"


@pytest.mark.live
@pytest.mark.skipif(not LIVE, reason="set SIMPLAY_LIVE=1")
@pytest.mark.parametrize("name", SENSOR_NAMES)
def test_sweep_writes_a_recording_the_analysis_can_read(name: str, tmp_path: Path) -> None:
    """Regression: sweep() itself had no test; it is what produces every result."""
    out = tmp_path / "slice.json"
    runs = sweep.sweep(name, workers=2, wall=12.0, limit=3, out=str(out),
                       progress=False, save_gold=False)
    assert len(runs) == 3
    assert json.loads(out.read_text()).keys() == runs.keys()
    assert load(name).results.joinpath("gold.json").exists(), "save_gold=False must not write"
    for mid, obs in runs.items():
        assert obs["id"] == mid
        assert obs["status"] == "observed", obs.get("err")


@pytest.mark.live
@pytest.mark.skipif(not LIVE, reason="set SIMPLAY_LIVE=1")
@pytest.mark.parametrize("name", SENSOR_NAMES)
def test_golden_run_passes_every_check(name: str) -> None:
    obs = sweep.run_one(name, None, wall=20.0)
    assert obs["status"] == "observed", obs.get("err")
    assert all(sweep.load(name).mod.CHECKS[c](obs) for c in ("L0", "L1", "L2", "L3"))
    assert obs["uart"] == "OK\nDONE"


@pytest.mark.live
@pytest.mark.skipif(not LIVE, reason="set SIMPLAY_LIVE=1")
def test_golden_command_prints_the_stock_driver_source() -> None:
    out = drive("bme280", "golden")
    first = load("bme280").source_file("bme280.c").read_text().splitlines()[0]
    assert first.strip() in out, "golden should show the stock driver it built"
    assert "passed every check" in out


@pytest.mark.live
@pytest.mark.skipif(not LIVE, reason="set SIMPLAY_LIVE=1")
def test_run_command_reproduces_the_recorded_verdict() -> None:
    name = "bmp388"
    row = next(r for r in analyze.rows(load(name)) if r.get("caught") == ["L2"])
    out = drive(name, f"run {row['id']}")
    assert "caught by L2" in out


@pytest.mark.live
@pytest.mark.skipif(not LIVE, reason="set SIMPLAY_LIVE=1")
def test_installed_console_script_works() -> None:
    r = subprocess.run([sys.executable, "-m", "simplay.cli", "bme280", "analyze"],
                       capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, r.stderr[-400:]
    assert "catch rates over live mutants" in r.stdout
