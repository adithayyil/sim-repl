"""Offline end-to-end tests: every command of the playground and the CLI.

Nothing here builds or simulates; the tests that need the ARM toolchain and
the Simantic engine live in test_live.py.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import simantic
from helpers import drive

from simplay import analyze, build, harness, mutgen, sweep
from simplay.cli import main as cli_main
from simplay.sensors import SENSOR_NAMES, load

ROOT = Path(__file__).resolve().parents[1]


# -- offline: no simulator needed ------------------------------------------
@pytest.mark.parametrize("name", SENSOR_NAMES)
def test_every_offline_command_runs(name: str) -> None:
    rows = analyze.rows(load(name))
    caught = next((r["id"] for r in rows if r.get("caught")), None)
    out = drive(
        name,
        "\n".join(
            [
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
            ]
        ),
    )
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


@pytest.mark.parametrize("name", SENSOR_NAMES)
def test_a_bare_command_falls_back_to_its_default_count(
    name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: _number() ignored its `default`, so `list` and `play` with no
    argument died with "'' is not a number" instead of using the default."""
    rows = analyze.rows(load(name))
    out = drive(name, "list")
    assert out.splitlines()[1].split()[0] == rows[0]["id"]
    assert "is not a number" not in out

    monkeypatch.setattr("builtins.input", lambda prompt="": "")
    assert "Traceback" not in drive(name, "play")


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
    monkeypatch.setattr(
        sweep,
        "run_one",
        lambda *a, **k: dict(status="sim_error", uart="", bus=[], ram={}, err="rig is on fire"),
    )
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


@pytest.mark.parametrize(
    "failure, expected",
    [
        (simantic.ExpectTimeout("DONE", "", 0.0), "no_completion"),
        (ValueError("renamed API"), "sim_error"),
    ],
)
def test_only_a_timeout_counts_as_a_hang(
    monkeypatch: pytest.MonkeyPatch, failure: Exception, expected: str
) -> None:
    """Regression: any exception from expect() used to be recorded as a mutant hang."""
    sensor = load("bme280")
    fake = type("Fake", (_FakeSim,), {"raises": failure})
    monkeypatch.setattr(simantic, "Sim", fake)
    obs = harness.observe(sensor, Path("sim.elf"), Path("/tmp"), wall=0.1)
    assert obs["status"] == expected


@pytest.mark.parametrize("failing", ["run_for", "read_uart", "logs"])
def test_a_failed_read_does_not_reclassify_a_hang(
    monkeypatch: pytest.MonkeyPatch, failing: str
) -> None:
    """Regression: the UART/log/RAM reads ran after a timeout too, and an API error
    there was caught by the outer handler, turning a mutant hang into sim_error."""
    sensor = load("bme280")

    def raise_it(self, *a, **k):
        raise RuntimeError("session already torn down")

    class Hung(_FakeSim):
        raises = simantic.ExpectTimeout("DONE", "", 0.0)

    class Completed(_FakeSim):
        raises = None

        def expect(self, pattern: str, timeout: float = 30) -> None:
            return None

    monkeypatch.setattr(Hung, failing, raise_it)
    monkeypatch.setattr(simantic, "Sim", Hung)
    obs = harness.observe(sensor, Path("sim.elf"), Path("/tmp"), wall=0.1)
    assert obs["status"] == "no_completion", obs
    assert "read:" in obs["err"], obs["err"]

    monkeypatch.setattr(Completed, failing, raise_it)
    monkeypatch.setattr(simantic, "Sim", Completed)
    assert harness.observe(sensor, Path("sim.elf"), Path("/tmp"), wall=0.1)["status"] == "sim_error"


@pytest.mark.parametrize("name", SENSOR_NAMES)
def test_a_failed_build_still_produces_a_complete_record(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    """Regression: a compile failure returned a dict without uart/bus/ram, so
    signature() and the playground would KeyError on it."""
    sensor = load(name)

    def boom(sensor, workdir, mutant):
        raise build.BuildError("cc: nope")

    monkeypatch.setattr(build, "compile_firmware", boom)
    row = dict(analyze.rows(sensor)[0])
    obs = sweep.run_one(name, row, wall=1.0)
    assert obs["status"] == "compile_fail"
    assert set(obs) >= {"id", "status", "uart", "bus", "ram", "err"}
    assert obs["id"] == row["id"]
    harness.signature(obs)  # must not raise


@pytest.mark.parametrize("name", SENSOR_NAMES)
def test_measurement_count_matches_the_peer(name: str) -> None:
    """read_ram() sizes its arrays from MEASUREMENTS; the peer serves one reading
    per round, and a mismatch would fail L2 on length alone."""
    sensor = load(name)
    served = re.search(
        r"^MEAS = \[(.*?)\]", sensor.peer.read_text(), re.DOTALL | re.MULTILINE
    ).group(1)
    assert len(re.findall(r"\(", served)) == sensor.mod.MEASUREMENTS


@pytest.mark.parametrize("name", SENSOR_NAMES)
def test_plausible_values_need_a_measurement(name: str) -> None:
    """Regression: all() over an empty list is True, so a mutant that skipped the
    measurement loop entirely passed L1 vacuously."""
    mod = load(name).mod
    empty = dict(status="observed", uart="OK", ram=dict(T=[], P=[], H=[], delays=[1]))
    assert not mod.CHECKS["L1"](empty)
    one_short = {**empty["ram"], "T": [0] * (mod.MEASUREMENTS - 1)}
    assert not mod.CHECKS["L1"](dict(status="observed", uart="OK", ram=one_short))


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
                assert all(x.annotation is None for x in [*a.args, *a.posonlyargs, *a.kwonlyargs])
                assert node.returns is None
        for banned in ("yield from", "nonlocal ", ":="):
            assert banned not in peer, f"{name} peer uses {banned!r}"
        assert peer.startswith("#"), f"{name} peer should say what it is"
