"""Every third-party byte in this repository is pinned in PROVENANCE.json."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "PROVENANCE.json"

ORIGINAL = tuple(
    sorted(str(p.relative_to(ROOT)) for d in ("bme280", "bmp388")
           for p in (ROOT / "src/simplay/sensors" / d).iterdir()
           if p.is_dir() and p.name in {"firmware", "results"})
)


def manifest() -> dict:
    return json.loads(MANIFEST.read_text())


def test_manifest_has_the_fields_a_vendored_file_needs() -> None:
    m = manifest()
    assert m["note"]
    for entry in m["vendored"]:
        for field in ("component", "url", "commit", "license", "destination", "files"):
            assert entry[field], f"{entry.get('component')} is missing {field}"
        assert entry["url"].startswith("https://github.com/")
        assert len(entry["commit"]) == 40, entry["component"]


def test_vendored_files_match_their_recorded_digests() -> None:
    for path, digest in manifest()["sha256"].items():
        blob = (ROOT / path).read_bytes()
        assert hashlib.sha256(blob).hexdigest() == digest, f"{path} differs from PROVENANCE.json"


def test_every_third_party_file_is_listed() -> None:
    listed = set(manifest()["sha256"])
    for entry in manifest()["vendored"]:
        dest = ROOT / entry["destination"]
        on_disk = {p.name for p in dest.iterdir() if p.is_file()} if dest.is_dir() else {dest.name}
        assert on_disk == set(entry["files"]), f"{entry['destination']} contents drifted"
        for name in entry["files"]:
            key = (f"{entry['destination']}/{name}" if (ROOT / entry["destination"]).is_dir()
                   else entry["destination"])
            assert key in listed, f"{key} is on disk but not pinned in PROVENANCE.json"


def test_vendored_licenses_are_present_and_named() -> None:
    for entry in manifest()["vendored"]:
        if entry["destination"].endswith("vendor"):
            text = (ROOT / entry["destination"] / "LICENSE").read_text()
            assert "BSD" in text or "MIT" in text
            assert entry["license"].split("-")[0] in text


def test_original_code_is_not_in_the_vendored_list() -> None:
    listed = set(manifest()["sha256"])
    for path in ORIGINAL:
        assert path not in listed, f"{path} is original work and must not be pinned as third-party"