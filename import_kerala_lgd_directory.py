from __future__ import annotations

import argparse
import csv
import gzip
import io
import re
import shutil
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterable


ROOT = Path(".")
INPUT_DIR = ROOT / "data" / "kerala_lgd_input"
OUT_DIR = ROOT / "data"
PKG_DATA = ROOT / "indic_places" / "data"

CUSTOM_PLACES = PKG_DATA / "custom_places.txt"
OUT_UNIQUE = OUT_DIR / "kerala_lgd_names_unique.txt"
OUT_FULL = OUT_DIR / "kerala_lgd_names_full.csv"
OUT_FULL_GZ = OUT_DIR / "kerala_lgd_names_full.csv.gz"
PYPROJECT = ROOT / "pyproject.toml"
README = ROOT / "README.md"

KERALA_KEYS = {"KERALA"}

NAME_HINTS = (
    "district name",
    "sub district name",
    "sub-district name",
    "subdistrict name",
    "block name",
    "development block name",
    "local body name",
    "localbody name",
    "localbodyname",
    "village name",
    "village name in english",
    "village name(in english",
    "ward name",
    "gram panchayat name",
    "panchayat name",
    "urban local body name",
    "traditional local body name",
    "ulb name",
    "pri local body name",
    "name in english",
    "name",
)

STATE_HINTS = (
    "state name",
    "state name in english",
    "state name(in english",
    "state",
)

DISTRICT_HINTS = (
    "district name",
    "district name in english",
    "district name(in english",
    "district",
)

PIN_HINTS = (
    "pincode",
    "pin code",
    "pin",
)

BAD_KEYS = {
    "NAME",
    "STATENAME",
    "DISTRICTNAME",
    "SUBDISTRICTNAME",
    "VILLAGENAME",
    "BLOCKNAME",
    "LOCALBODYNAME",
    "WARDNAME",
    "NA",
    "NONE",
    "NULL",
    "NIL",
    "NAN",
}


def clean_cell(value: object) -> str:
    s = str(value or "").replace("\ufeff", "").strip()
    s = re.sub(r"\s+", " ", s)
    return s.strip(" ,;:-|[]{}()")


def normalize_col(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def name_key(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def pretty_name(value: str) -> str:
    s = clean_cell(value)
    if not s:
        return ""

    if re.fullmatch(r"[\d.\-_/]+", s):
        return ""

    s = re.sub(
        r"(?i)\s+\b(?:G\.?P\.?O\.?|H\.?O\.?|S\.?O\.?|B\.?O\.?|P\.?O\.?|GPO|HO|SO|BO|PO)$",
        "",
        s,
    ).strip(" ,;:-|")

    key = name_key(s)
    if not key or key in BAD_KEYS:
        return ""

    # Avoid pure ward/serial labels with no locality value.
    if re.fullmatch(r"(?i)(ward|ward no|ward number)\s*\d+", s):
        return ""

    if s.isupper() and len(s) > 3:
        s = s.title()

    return s


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def cell_index(cell: ET.Element) -> int | None:
    for key, value in cell.attrib.items():
        if key.endswith("}Index") or key == "Index":
            try:
                return int(value)
            except Exception:
                return None
    return None


def row_values(row: ET.Element) -> list[str]:
    values: list[str] = []
    current_col = 1

    for cell in list(row):
        if local_name(cell.tag) != "Cell":
            continue

        idx = cell_index(cell)
        if idx:
            while current_col < idx:
                values.append("")
                current_col += 1

        value = ""
        for child in list(cell):
            if local_name(child.tag) == "Data":
                value = clean_cell("".join(child.itertext()))
                break

        values.append(value)
        current_col += 1

    return values


def looks_like_header(values: list[str]) -> bool:
    non_empty = [v for v in values if v]
    if len(non_empty) < 2:
        return False

    cols = [normalize_col(v) for v in values]

    has_name_col = any(
        any(h in c for h in [normalize_col(x) for x in NAME_HINTS])
        for c in cols
    )
    has_context_col = any(
        ("code" in c or "state" in c or "district" in c or "version" in c or "local body" in c or "village" in c)
        for c in cols
    )

    return has_name_col and has_context_col


def find_index(headers: list[str], hints: tuple[str, ...]) -> int | None:
    cols = [normalize_col(h) for h in headers]

    for hint in hints:
        h = normalize_col(hint)
        for i, c in enumerate(cols):
            if c == h:
                return i

    for hint in hints:
        h = normalize_col(hint)
        for i, c in enumerate(cols):
            if h and h in c:
                return i

    return None


def iter_xml_excel_rows_from_bytes(raw: bytes, source_name: str) -> Iterable[dict]:
    header: list[str] | None = None
    data_rows = 0

    for _event, elem in ET.iterparse(io.BytesIO(raw), events=("end",)):
        if local_name(elem.tag) != "Row":
            continue

        values = row_values(elem)
        elem.clear()

        if not any(values):
            continue

        if header is None:
            if looks_like_header(values):
                header = values
                print(f"Detected header in {source_name}:", header[:10])
            continue

        if values == header:
            continue

        if len([v for v in values if v]) < 2:
            continue

        data_rows += 1
        yield {
            header[i]: values[i] if i < len(values) else ""
            for i in range(len(header))
        }

    if header is None:
        print("WARNING: header not found:", source_name)


def read_file_bytes(path: Path) -> bytes:
    return path.read_bytes()


def is_xml_excel_bytes(raw: bytes) -> bool:
    head = raw[:500].lstrip()
    return head.startswith(b"<?xml") or b"mso-application" in head


def iter_csv_rows_from_bytes(raw: bytes) -> Iterable[dict]:
    text = None
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin1"):
        try:
            text = raw.decode(enc)
            break
        except Exception:
            continue

    if not text:
        return

    delimiter = max([",", "\t", "|", ";"], key=lambda c: text[:4096].count(c))
    reader = csv.DictReader(text.splitlines(), delimiter=delimiter)

    for row in reader:
        yield row


def iter_rows_from_named_bytes(source_name: str, raw: bytes) -> Iterable[dict]:
    lower = source_name.lower()

    if lower.endswith(".xls") and is_xml_excel_bytes(raw):
        yield from iter_xml_excel_rows_from_bytes(raw, source_name)
        return

    if lower.endswith((".csv", ".txt", ".tsv")):
        yield from iter_csv_rows_from_bytes(raw)
        return

    if lower.endswith((".xls", ".xlsx")):
        print("SKIP real binary Excel inside this importer:", source_name)
        print("Convert to CSV or use XML LGD .xls.")
        return


def iter_all_input_rows() -> Iterable[tuple[str, dict]]:
    if not INPUT_DIR.exists():
        return

    files = [
        p for p in INPUT_DIR.rglob("*")
        if p.is_file() and p.suffix.lower() in {".zip", ".xls", ".xlsx", ".csv", ".txt", ".tsv"}
    ]

    for path in files:
        suffix = path.suffix.lower()

        if suffix == ".zip":
            print("Reading ZIP:", path)
            with zipfile.ZipFile(path) as zf:
                for info in zf.infolist():
                    name = info.filename
                    if name.endswith("/"):
                        continue
                    if not name.lower().endswith((".xls", ".xlsx", ".csv", ".txt", ".tsv")):
                        continue

                    raw = zf.read(info)
                    for row in iter_rows_from_named_bytes(name, raw):
                        yield name, row
            continue

        print("Reading:", path)
        raw = read_file_bytes(path)
        for row in iter_rows_from_named_bytes(path.name, raw):
            yield path.name, row


def is_kerala_row(row: dict, headers: list[str], default_kerala: bool = True) -> bool:
    state_i = find_index(headers, STATE_HINTS)
    if state_i is None:
        return default_kerala

    state = clean_cell(row.get(headers[state_i], ""))
    return name_key(state) in KERALA_KEYS


def source_type_from_name(source_name: str, header: str) -> str:
    s = source_name.lower()

    if "subdistrict" in s:
        return "subdistrict"
    if "village" in s:
        return "village"
    if "block" in s:
        return "block"
    if "ulb" in s or "urban" in s:
        return "urban_local_body"
    if "ward" in s:
        return "ward"
    if "pri" in s or "panchayat" in s:
        return "panchayat"
    if "district" in s:
        return "district"
    if "tlb" in s:
        return "traditional_local_body"

    h = normalize_col(header)
    if "sub district" in h:
        return "subdistrict"
    if "village" in h:
        return "village"
    if "ward" in h:
        return "ward"

    return header


def extract_records(source_name: str, row: dict) -> list[dict]:
    headers = list(row.keys())

    if not is_kerala_row(row, headers, default_kerala=True):
        return []

    district_i = find_index(headers, DISTRICT_HINTS)
    pin_i = find_index(headers, PIN_HINTS)

    district = clean_cell(row.get(headers[district_i], "")) if district_i is not None else ""
    pincode = clean_cell(row.get(headers[pin_i], "")) if pin_i is not None else ""

    out = []

    for header in headers:
        h = normalize_col(header)

        # Skip state/district code/version columns.
        if "code" in h or "version" in h:
            continue

        # Extract all useful name-like columns.
        if not any(normalize_col(hint) in h for hint in NAME_HINTS):
            continue

        # Avoid adding state name itself from every row.
        if "state name" in h:
            continue

        name = pretty_name(row.get(header, ""))
        key = name_key(name)

        if not key or len(key) < 3:
            continue

        out.append({
            "name": name,
            "state": "KERALA",
            "district": district.upper(),
            "pincode": pincode,
            "source_type": source_type_from_name(source_name, header),
            "source_file": source_name,
        })

    return out


def read_existing_custom() -> dict[str, str]:
    out = {}
    if not CUSTOM_PLACES.exists():
        return out

    for line in CUSTOM_PLACES.read_text(encoding="utf-8", errors="ignore").splitlines():
        name = line.split("#", 1)[0].strip()
        key = name_key(name)
        if key:
            out.setdefault(key, name)

    return out


def update_pyproject(version: str) -> None:
    if not PYPROJECT.exists():
        return

    text = PYPROJECT.read_text(encoding="utf-8-sig")
    text = re.sub(r'(?m)^version\s*=.*$', f'version = "{version}"', text)
    text = re.sub(
        r'(?m)^description\s*=.*$',
        'description = "Indian place-name lookup, OCR address cleanup, Kerala LGD locality vocabulary, correction, extraction, and address intelligence"',
        text,
    )
    PYPROJECT.write_text(text, encoding="utf-8")


def update_readme() -> None:
    if not README.exists():
        return

    text = README.read_text(encoding="utf-8", errors="ignore")
    note = """
### Kerala LGD locality vocabulary

Kerala LGD data can be imported from downloaded LGD ZIP/XLS files. The importer extracts unique names from district, subdistrict, block, village, panchayat, urban local body, traditional local body, and ward-style files.

Output files:

```text
data/kerala_lgd_names_unique.txt
data/kerala_lgd_names_full.csv.gz
indic_places/data/custom_places.txt
```

Raw downloaded source files should stay ignored under:

```text
data/kerala_lgd_input/
```
"""

    if "### Kerala LGD locality vocabulary" not in text:
        README.write_text(text.rstrip() + "\n\n" + note.strip() + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", default="1.3.9")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not (ROOT / "indic_places").exists():
        raise SystemExit("ERROR: Run from indic_names_library repo root.")

    INPUT_DIR.mkdir(parents=True, exist_ok=True)

    records = []
    seen_full = set()

    for source_name, row in iter_all_input_rows():
        for rec in extract_records(source_name, row):
            full_key = (
                name_key(rec["name"]),
                name_key(rec["state"]),
                name_key(rec["district"]),
                rec["pincode"],
                name_key(rec["source_type"]),
            )
            if full_key in seen_full:
                continue

            seen_full.add(full_key)
            records.append(rec)

    unique_names: dict[str, str] = {}
    for rec in records:
        key = name_key(rec["name"])
        if key:
            unique_names.setdefault(key, rec["name"])

    existing = read_existing_custom()
    new_only = {k: v for k, v in unique_names.items() if k not in existing}
    merged = dict(existing)
    merged.update(new_only)

    print("=" * 80)
    print("SUMMARY")
    print(f"Kerala structured records read : {len(records):,}")
    print(f"Unique Kerala names found      : {len(unique_names):,}")
    print(f"Already present in custom      : {len(unique_names) - len(new_only):,}")
    print(f"New unique names to add        : {len(new_only):,}")
    print(f"Final custom_places count      : {len(merged):,}")

    if args.dry_run:
        print("DRY RUN ONLY. No files changed.")
        return

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    PKG_DATA.mkdir(parents=True, exist_ok=True)

    with OUT_FULL.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["name", "state", "district", "pincode", "source_type", "source_file"],
        )
        writer.writeheader()
        writer.writerows(records)

    with OUT_FULL.open("rb") as src, gzip.open(OUT_FULL_GZ, "wb", compresslevel=9) as dst:
        shutil.copyfileobj(src, dst)

    OUT_UNIQUE.write_text(
        "\n".join(sorted(unique_names.values(), key=lambda x: x.upper())) + "\n",
        encoding="utf-8",
    )

    CUSTOM_PLACES.write_text(
        "\n".join(sorted(merged.values(), key=lambda x: x.upper())) + "\n",
        encoding="utf-8",
    )

    update_pyproject(args.version)
    update_readme()

    print("=" * 80)
    print("DONE")
    print("Wrote:", OUT_FULL)
    print("Wrote:", OUT_FULL_GZ)
    print("Wrote:", OUT_UNIQUE)
    print("Updated:", CUSTOM_PLACES)
    print("Version:", args.version)


if __name__ == "__main__":
    main()
