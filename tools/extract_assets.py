"""Extract the Firehawk tone-model data from your own copy of the Line 6 app.

FreedomHawk ships no Line 6 data.  To keep the project a clean, non-redistributing
interoperability tool, the pedal's model/parameter/catalog data is NOT stored in this
repository — you generate it locally from an APK of the (discontinued) Firehawk Remote
app that you lawfully have.

Usage:
    python tools/extract_assets.py [path-to-firehawk-remote.apk]

With no argument it looks for ``com-line6-firehawk-*.apk`` in the project root.  It
writes the needed files into ``src/firehawk/data/`` and regenerates
``firehawk_symbols.json`` from the symbol table.
"""

from __future__ import annotations

import glob
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "src" / "firehawk" / "data"

# The build this project was developed against (informational; other versions may work).
KNOWN_SHA256 = "eeaaa742ae412085632a569e56a2010c3c2abde415551bdb00ffa122981dccb5"

# Which asset files the app needs, matched by pattern inside the APK's assets/ folder.
ASSET_PATTERNS = (
    r"assets/[^/]+\.models$",
    r"assets/[^/]+Catalog\.json$",
    r"assets/default_preset\.json$",
    r"assets/defaultSymbolTable\.bin$",
)


def find_apk(argv: list[str]) -> Path:
    if len(argv) > 1:
        return Path(argv[1])
    matches = glob.glob(str(ROOT / "com-line6-firehawk-*.apk"))
    if not matches:
        sys.exit(
            "No APK given and none found in the project root.\n"
            "Usage: python tools/extract_assets.py <path-to-firehawk-remote.apk>"
        )
    return Path(matches[0])


def main(argv: list[str]) -> int:
    apk_path = find_apk(argv)
    if not apk_path.exists():
        sys.exit(f"APK not found: {apk_path}")

    sha = hashlib.sha256(apk_path.read_bytes()).hexdigest()
    if sha == KNOWN_SHA256:
        print(f"APK verified (sha256 matches the known build).")
    else:
        print(f"Note: APK sha256 {sha} differs from the known build; extraction will\n"
              f"      still be attempted (a different app version may work fine).")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    patterns = [re.compile(p) for p in ASSET_PATTERNS]
    extracted = 0
    with zipfile.ZipFile(apk_path) as z:
        for name in z.namelist():
            if any(p.search(name) for p in patterns):
                target = DATA_DIR / Path(name).name
                target.write_bytes(z.read(name))
                extracted += 1
    print(f"Extracted {extracted} asset files into {DATA_DIR}")

    _regenerate_symbols()
    print("Done. You can now run:  python -m firehawk")
    return 0


def _regenerate_symbols() -> None:
    """Rebuild firehawk_symbols.json from the extracted symbol table."""
    sys.path.insert(0, str(ROOT / "src"))
    try:
        from firehawk.model.symbols import SymbolTable
    except Exception as exc:  # noqa: BLE001
        print(f"(skipped symbol JSON regeneration: {exc})")
        return
    bin_path = DATA_DIR / "defaultSymbolTable.bin"
    if not bin_path.exists():
        print("(no defaultSymbolTable.bin extracted; skipping symbol JSON)")
        return
    table = SymbolTable.load(bin_path)
    data = [{"index": s.index, "name": s.name, "hash": s.hash} for s in table]
    (DATA_DIR / "firehawk_symbols.json").write_text(
        json.dumps(data, indent=1), encoding="utf-8"
    )
    print(f"Regenerated firehawk_symbols.json ({len(data)} symbols)")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
