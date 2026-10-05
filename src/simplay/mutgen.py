"""Mechanical mutant generation.

Seven operators (relational, arithmetic, shift, bitwise, logical, constant,
define constant) applied to every eligible token of the pinned driver source.
Nothing is hand-picked: given a seed and a count the sample is reproducible,
and the seed is recorded next to the mutants.
"""

from __future__ import annotations

import json
import random
import re
from pathlib import Path

from .sensors import Sensor

KEYWORDS = {"return", "case", "else", "do", "sizeof", "goto"}

def token_re(*, floats: bool) -> re.Pattern:
    """Operator and literal tokens.

    A float literal has to be matched as one token where the driver uses them:
    splitting `1.5` into `1 . 5` would change every offset after it.
    """
    leading = r"\d+\.\d*(?:[eE][-+]?\d+)?[fF]?" if floats else None
    parts = [leading] if leading else []
    parts += [
        r"0[xX][0-9a-fA-F]+[uUlL]*",
        r"\d+[uUlL]*",
        r"[A-Za-z_]\w*",
        r"<<=|>>=|<<|>>|<=|>=|==|!=|&&|\|\||->|\+\+|--|\+=|-=|\*=|/=|&=|\|=|\^=|%=",
        r"[-+*/%&|^~!<>=?:;,.(){}\[\]]",
    ]
    return re.compile("|".join(parts))

DEFINE = re.compile(
    r"^#define\s+(?P<name>%(prefix)s[A-Z0-9_]+)\s+\(?U?INT(?:8|16|32)_C\((?P<args>[^)]*)\)"
    r"|^#define\s+(?P<name2>%(prefix)s[A-Z0-9_]+)\s+\((?P<hex>0x[0-9A-Fa-f]+)\)",
    re.M,
)


def strip_comments(src: str) -> str:
    """Blank comments but keep every newline, so token offsets stay valid."""

    def blank(m: re.Match) -> str:
        return re.sub(r"[^\n]", " ", m.group(0))

    src = re.sub(r"/\*.*?\*/", blank, src, flags=re.S)
    return re.sub(r"//[^\n]*", blank, src)


def _kind(token: str) -> str:
    if re.match(r"\d+\.\d*(?:[eE][-+]?\d+)?[fF]?$", token):
        return "flt"
    if re.match(r"(0[xX][0-9a-fA-F]+|\d+)[uUlL]*$", token):
        return "num"
    return "id" if re.match(r"[A-Za-z_]", token) else "op"


def int_repls(token: str) -> list[str]:
    m = re.match(r"(0[xX][0-9a-fA-F]+|\d+)([uUlL]*)$", token)
    body, suffix = m.group(1), m.group(2)
    hexish = body.lower().startswith("0x")
    v = int(body, 16) if hexish else int(body)
    fmt = hex if hexish else str
    return [fmt(v + 1) + suffix, fmt(v ^ 1) + suffix, fmt(v - 1) + suffix if v > 0 else "(-1)"]


def float_repls(token: str) -> list[str]:
    suffix = "f" if token[-1] in "fF" else ""
    v = float(token.rstrip("fF"))
    return [repr(v * 2) + suffix, repr(v / 2) + suffix]


def sites_in(sensor: Sensor) -> list[dict]:
    """Every mutation site in the driver and its register defines."""
    cfg = sensor.mutgen
    driver = sensor.source_file(cfg["driver"])
    code = strip_comments(driver.read_text())
    toks = [
        (m.start(), m.end(), m.group(0), _kind(m.group(0)))
        for m in token_re(floats=cfg["float_literals"]).finditer(code)
    ]
    preproc = {i + 1 for i, line in enumerate(code.split("\n")) if line.lstrip().startswith("#")}
    excluded = cfg["excluded"]

    sites = []
    for i, (start, end, tok, kind) in enumerate(toks):
        line = code.count("\n", 0, start) + 1
        if line in preproc or line < cfg["first_line"] or any(a <= line <= b for a, b in excluded):
            continue
        prev = toks[i - 1] if i else None
        binary = prev is not None and (
            prev[3] in ("num", "flt")
            or (prev[3] == "id" and prev[2] not in KEYWORDS)
            or prev[2] in (")", "]")
        )
        cls = cand = None
        if tok in ("==", "!="):
            cls, cand = "ROR", ["!=" if tok == "==" else "=="]
        elif tok in ("<", "<=", ">", ">="):
            swaps = {"<": ["<=", ">="], "<=": ["<", ">"], ">": [">=", "<="], ">=": [">", "<"]}
            cls, cand = "ROR", swaps[tok]
        elif tok in ("+", "-") and binary:
            cls, cand = "AOR", ["-" if tok == "+" else "+"]
        elif tok in ("<<", ">>"):
            cls, cand = "SHIFT", [">>" if tok == "<<" else "<<"]
        elif tok in ("&", "|") and binary:
            cls, cand = "BITWISE", ["|" if tok == "&" else "&"]
        elif tok in ("&&", "||"):
            cls, cand = "LOGICAL", ["||" if tok == "&&" else "&&"]
        elif kind == "num":
            cls, cand = "CONST", int_repls(tok)
        elif kind == "flt" and cfg["float_literals"]:
            cls, cand = "CONST", float_repls(tok)
        if cls:
            sites.append(
                dict(file=cfg["driver"], start=start, end=end, line=line,
                     cls=cls, orig=tok, cand=cand)
            )

    defs = sensor.source_file(cfg["defs"])
    src = defs.read_text()
    pattern = re.compile(DEFINE.pattern % {"prefix": cfg["define_prefix"]}, re.M)
    for m in pattern.finditer(src):
        body, body_start = (m.group("args"), m.start("args")) if m.group("args") else (
            m.group("hex"),
            m.start("hex"),
        )
        for n in re.finditer(r"0[xX][0-9a-fA-F]+|\d+", body):
            sites.append(
                dict(
                    file=cfg["defs"],
                    start=body_start + n.start(),
                    end=body_start + n.end(),
                    line=src.count("\n", 0, body_start) + 1,
                    cls="DEFCONST",
                    orig=n.group(0),
                    cand=int_repls(n.group(0)),
                )
            )
    return sites


def generate(sensor: Sensor, n: int, seed: int) -> dict:
    sites = sites_in(sensor)
    rng = random.Random(seed)
    picked = sorted(rng.sample(range(len(sites)), min(n, len(sites))))
    mutants = [
        dict(
            id=f"m{k:03d}",
            **{
                key: sites[i][key]
                for key in ("file", "start", "end", "line", "cls", "orig")
            },
            repl=rng.choice(sites[i]["cand"]),
        )
        for k, i in enumerate(picked)
    ]
    return {"seed": seed, "n_sites": len(sites), "mutants": mutants}


def save(sensor: Sensor, spec: dict, path: Path | None = None) -> Path:
    out = path or (sensor.results / "mutants.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(spec, indent=1))
    return out


def load(sensor: Sensor) -> dict:
    return json.loads((sensor.results / "mutants.json").read_text())
