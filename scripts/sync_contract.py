"""Copies Lumber-Kit's contract (schema.json, vectors.json) into tests/contract at the kit version in
tests/contract/VERSION, from the npm registry, or from a local Lumber-Kit checkout with --from while the kit's change
isn't released yet.

    python scripts/sync_contract.py                    # the pinned version
    python scripts/sync_contract.py 0.8.0              # pin a new version
    python scripts/sync_contract.py --from ../Lumber-Kit

CI runs it and fails when the copy differs from the pinned version's.
"""

from __future__ import annotations

import argparse
import io
import shutil
import tarfile
import urllib.request
from pathlib import Path

FILES = ("schema.json", "vectors.json")
CONTRACT = Path(__file__).resolve().parent.parent / "tests" / "contract"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("version", nargs="?", help="the Lumber-Kit version to pin (default: tests/contract/VERSION)")
    parser.add_argument("--from", dest="source", type=Path, help="a local Lumber-Kit checkout to copy from")
    args = parser.parse_args()

    if args.source:
        for name in FILES:
            shutil.copyfile(args.source / "contract" / name, CONTRACT / name)
        print(f"Copied the contract from {args.source} (VERSION unchanged)")
        return

    version = args.version or (CONTRACT / "VERSION").read_text().strip()
    url = f"https://registry.npmjs.org/@infinitetoken/lumber-kit/-/lumber-kit-{version}.tgz"
    with urllib.request.urlopen(url, timeout=30) as response:
        tarball = io.BytesIO(response.read())
    with tarfile.open(fileobj=tarball, mode="r:gz") as archive:
        for name in FILES:
            member = archive.extractfile(f"package/contract/{name}")
            if member is None:
                raise SystemExit(f"Lumber-Kit {version} has no contract/{name}")
            (CONTRACT / name).write_bytes(member.read())
    (CONTRACT / "VERSION").write_text(f"{version}\n")
    print(f"Synced the contract from Lumber-Kit {version}")


if __name__ == "__main__":
    main()
