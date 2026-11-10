#!/usr/bin/env python3
"""Package this repository as an installable ``.mflp`` plugin and an index.

## What a package is

The launcher accepts a ZIP archive with ``manifest.json`` at the root and any
files it references in ``assets/``. ``.mflp`` and ``.mfplugin`` are the same
format; the extension is a hint, not a contract. So packaging is: zip the
manifest and the artwork, deterministically, and record the hash.

## Why deterministic

Two builds of the same source must produce the same bytes, otherwise every
release looks like a change to the plugin index even when nothing moved, and a
``sha256`` recorded today stops verifying tomorrow. The three settings that make
a zip reproducible are: sorted entry order, a fixed timestamp, and no
compression-level variation. All three are set below.

## Why the index is generated and not hand-written

``index.json`` carries a SHA-256 for the package. Hand-editing it after every
build is exactly the step that gets skipped, and a wrong hash means installs are
refused — or worse, a hash that matches an older archive than the one published.
Generating it from the archive that was just written makes the two agree by
construction.

Usage:
    python tools/package.py            # build the package and refresh index.json
    python tools/package.py --check    # verify index.json matches a rebuild
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DIST = ROOT / "dist"
MANIFEST = ROOT / "manifest.json"
ASSETS = ROOT / "assets"

# Fixed timestamp for every entry: 1980-01-01 00:00, the earliest a ZIP can
# represent. Using the build time would make every build differ.
ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)


def collect() -> list[tuple[Path, str]]:
    """Every file to ship, as (path on disk, name inside the archive).

    Sorted by archive name so the central directory order is stable regardless of
    what order the filesystem hands entries back. Hidden files and build output
    are excluded: a stray ``.DS_Store`` in a plugin package is noise at best.
    """
    entries: list[tuple[Path, str]] = [(MANIFEST, "manifest.json")]

    for path in sorted(ASSETS.rglob("*")):
        if not path.is_file():
            continue
        name = path.relative_to(ROOT).as_posix()
        if Path(name).name.startswith("."):
            continue
        entries.append((path, name))

    return sorted(entries, key=lambda item: item[1])


def build(target: Path) -> Path:
    """Write the archive, deterministic in name order and content."""
    DIST.mkdir(parents=True, exist_ok=True)
    entries = collect()

    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for source, name in entries:
            info = zipfile.ZipInfo(name, date_time=ZIP_EPOCH)
            # 0o644: a plugin's files are read by the launcher, never executed, so
            # the executable bit would only invite questions.
            info.external_attr = 0o644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, source.read_bytes())

    return target


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def write_index(package: Path, digest: str) -> Path:
    """Refresh index.json from the manifest and the archive just written.

    The index is what the launcher's plugin source reads. Its fields mirror
    ``PluginIndexEntry`` in the launcher's ``utils/pluginInstall.ts``; the
    download URL is a GitHub release asset reference, which has to be filled in
    once the release exists — so the checked-in file points at the ``releases``
    page rather than guessing a tag.
    """
    manifest = json.loads(MANIFEST.read_text("utf-8"))
    version = manifest["version"]

    entry = {
        "id": manifest["id"],
        "name": manifest["name"]["fallback"],
        "description": manifest["description"]["fallback"],
        "author": manifest["author"],
        "version": version,
        # Replace with the real asset URL after publishing the release:
        #   https://github.com/Hgit-1/mfmcl-aria-with-you/releases/download/v<version>/aria-with-you-<version>.mflp
        "download": (
            "https://github.com/Hgit-1/mfmcl-aria-with-you/releases/download/"
            f"v{version}/aria-with-you-{version}.mflp"
        ),
        "homepage": manifest.get("homepage"),
        "sha256": digest,
        "permissions": manifest.get("permissions", []),
        "hooks": manifest.get("hooks", []),
        "minLauncherVersion": "0.1.0",
    }

    index = {
        "schema": 1,
        "name": "MFMCL Aria with You",
        "plugins": [entry],
    }
    target = ROOT / "index.json"
    target.write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n", "utf-8")
    return target


def main(argv: list[str]) -> int:
    manifest = json.loads(MANIFEST.read_text("utf-8"))
    version = manifest["version"]
    package = DIST / f"aria-with-you-{version}.mflp"

    build(package)
    digest = sha256(package)

    if "--check" in argv:
        index = json.loads((ROOT / "index.json").read_text("utf-8"))
        recorded = index["plugins"][0].get("sha256")
        if recorded != digest:
            print(f"MISMATCH: index has {recorded}, rebuild has {digest}", file=sys.stderr)
            return 1
        print(f"ok: {package.name} matches index.json ({digest[:16]}...)")
        return 0

    index_path = write_index(package, digest)
    size = package.stat().st_size
    print(f"package {package.relative_to(ROOT)}  {size / 1024 / 1024:.2f} MiB")
    print(f"sha256  {digest}")
    print(f"index   {index_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
