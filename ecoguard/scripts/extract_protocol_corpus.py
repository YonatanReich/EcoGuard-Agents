"""Unpacking the fire service procedure archives into safe, predictable filenames."""

from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path

from ecoguard.paths import PACKAGE_ROOT

SOURCE = PACKAGE_ROOT / "detectors" / "fire" / "Reference"
DESTINATION = PACKAGE_ROOT / "data" / "protocols" / "raw"

# The two divisions, and the short name each is filed under. Kept explicit
# rather than globbed so a third archive appearing later is a decision rather
# than a silent change in what the corpus contains.
ARCHIVES = {
    "ops": "נהלי חטיבת מבצעים 1.zip",
    "control": "נהלי משל_ט ארצי.zip",
}

DIVISION = {
    "ops": 'אג"ם / תוה"ד — חטיבת מבצעים',
    "control": 'משל"ט ארצי',
    "wui": "עקרונות מנחים — הגנה על יישובים סמוכי יער",
}

# Loose PDFs sitting beside the archives rather than inside one. The
# wildland/urban interface principles arrived this way, and it is the document
# that closes the corpus's largest gap — there is no other Israeli source here
# for fire threatening a settlement. Picked up by scanning the folder so a
# second one does not need code.

ESCAPE = re.compile(r"#U([0-9a-fA-F]{4})")


def decode(name: str) -> str:
    """The real Hebrew title behind a `#Uxxxx`-escaped archive entry."""
    return ESCAPE.sub(lambda match: chr(int(match.group(1), 16)), name)


def extract() -> dict:
    """Unpack the procedure archives into safe filenames."""
    DESTINATION.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, dict] = {}

    for short_name, archive_name in ARCHIVES.items():
        archive_path = SOURCE / archive_name
        if not archive_path.exists():
            raise SystemExit(f"missing archive: {archive_path}")

        folder = DESTINATION / short_name
        folder.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(archive_path) as archive:
            entries = [
                entry for entry in archive.namelist()
                if entry.lower().endswith(".pdf")
            ]
            for index, entry in enumerate(sorted(entries)):
                safe = folder / f"{index:02d}.pdf"
                safe.write_bytes(archive.read(entry))
                title = decode(Path(entry).stem)
                manifest[f"{short_name}/{safe.name}"] = {
                    "title": title,
                    "division": DIVISION[short_name],
                    "archive": archive_name,
                    "archive_entry": entry,
                    "bytes": safe.stat().st_size,
                }

    # Loose PDFs, filed under their own division.
    loose = sorted(SOURCE.glob("*.pdf"))
    if loose:
        folder = DESTINATION / "wui"
        folder.mkdir(parents=True, exist_ok=True)
        for index, source_pdf in enumerate(loose):
            safe = folder / f"{index:02d}.pdf"
            safe.write_bytes(source_pdf.read_bytes())
            manifest[f"wui/{safe.name}"] = {
                "title": source_pdf.stem,
                "division": DIVISION["wui"],
                "archive": "(loose file)",
                "archive_entry": source_pdf.name,
                "bytes": safe.stat().st_size,
            }

    mapping = DESTINATION / "manifest.json"
    mapping.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return manifest


def main() -> None:
    """Extract the corpus from the command line."""
    manifest = extract()
    print(f"{len(manifest)} documents extracted to {DESTINATION}")
    for short_name in ARCHIVES:
        count = sum(1 for key in manifest if key.startswith(f"{short_name}/"))
        print(f"  {short_name}: {count}")
    print(f"mapping: {DESTINATION / 'manifest.json'}")


if __name__ == "__main__":
    main()
