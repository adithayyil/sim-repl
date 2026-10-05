#!/usr/bin/env python
"""Re-download every vendored file from upstream and compare it with the copy here.

    nix develop -c uv run tools/check_provenance.py

Needs network. The test suite only checks the local digests, so this is the
command that proves the pins still point at the sources they claim to.
"""

from __future__ import annotations

import json
import sys
import tarfile
import urllib.request
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UA = {"User-Agent": "simplay-provenance-check"}


def fetch(url: str) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=90) as r:
        return r.read()


def upstream_bytes(entry: dict) -> dict[str, bytes]:
    """Map destination-relative file name -> upstream content."""
    if entry["component"] == "renode/renode":
        raw = entry["url"].replace("github.com", "raw.githubusercontent.com")
        url = f"{raw}/{entry['commit']}/{entry['path_in_repo']}"
        return {entry["files"][0]: fetch(url)}
    tar = fetch(f"https://codeload.github.com/{entry['component']}/tar.gz/{entry['commit']}")
    out: dict[str, bytes] = {}
    with tarfile.open(fileobj=BytesIO(tar)) as tf:
        for member in tf.getmembers():
            name = Path(member.name).name
            # GitHub archives are "<repo>-<sha>/<path>"; take only the repo root.
            if member.isfile() and member.name.count("/") == 1 and name in entry["files"]:
                out[name] = tf.extractfile(member).read()
    return out


def main() -> int:
    manifest = json.loads((ROOT / "PROVENANCE.json").read_text())
    bad = 0
    for entry in manifest["vendored"]:
        dest = ROOT / entry["destination"]
        try:
            got = upstream_bytes(entry)
        except Exception as exc:  # noqa: BLE001 - report and keep going
            print(f"FAIL {entry['component']}@{entry['commit'][:8]}: could not fetch ({exc})")
            bad += 1
            continue
        for name in entry["files"]:
            local = (dest / name) if dest.is_dir() else dest
            remote = got.get(name)
            if remote is None:
                print(f"FAIL {entry['component']}: {name} not found upstream at this commit")
                bad += 1
            elif remote != local.read_bytes():
                print(f"FAIL {entry['component']}: {name} differs from upstream")
                bad += 1
            else:
                print(f"ok   {entry['component']}@{entry['commit'][:8]} {name}")
    print("all vendored files match upstream" if not bad else f"{bad} problem(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
