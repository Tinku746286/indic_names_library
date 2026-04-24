from __future__ import annotations

import argparse
import csv
import gzip
import re
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterable


ROOT = Path(".")
INPUT_DIR = ROOT / "data" / "south_india_input"
OUT_DIR = ROOT / "data"
PKG_DATA = ROOT / "indic_places" / "data"

CUSTOM_PLACES = PKG_DATA / "custom_places.txt"
OUT_UNIQUE = OUT_DIR / "south_india_admin_localities_unique.txt"
OUT_FULL = OUT_DIR / "south_india_admin_localities_full.csv"
OUT_FULL_GZ = OUT_DIR / "south_india_admin_localities_full.csv.gz"
PYPROJECT = ROOT / "pyproject.toml"
README = ROOT / "README.md"

SOUTH_STATES = {
    "KERALA",
    "TAMIL NADU",
    "KARNATAKA",
    "ANDHRA PRADESH",
    "TELANGANA",
    "PUDUCHERRY",
    "LAKSHADWEEP",
}

NAME_HINTS = (
    "village name",
    "village name in english",
    "village name(in english)",
    "sub district name",
    "sub-district name",
    "subdistrict name",
    "taluk",
    "taluka",
    "tehsil",
    "mandal",
    "block name",
    "local body name",
    "office name",
    "officename",
    "post office",
    "po name",
    "locality",
    "colony",
    "area",
    "place name",
    "name",
)

STATE_HINTS = (
    "state name",
    "state name in english",
    "state name(in english)",
    "statename",
    "state",
    "circle name",
    "circlename",
)

DISTRICT_HINTS = (
    "district name",
    "district name in english",
    "district name(in english)",
    "districtname",
    "district",
)

PIN_HINTS = (
    "pincode",
    "pin code",
    "pin",
    "postal code",
)

TYPE_HINTS = (
    "office type",
    "officetype",
    "entity type",
    "type",
    "category",
)


def clean_cell(value: object) -> str:
    s = str(value or "").replace("\ufeff", "").strip()
    s = re.sub(r"\s+", " ", s)
    return s.strip(" ,;:-|[]{}()")


def normalize_col(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def name_key(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def state_key(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


SOUTH_STATE_KEYS = {state_key(x) for x in SOUTH_STATES}


def pretty_name(value: str) -> str:
    s = clean_cell(value)

    if not s:
        return ""

    if re.fullmatch(r"[\d.\-_/]+", s):
        return ""

    key = name_key(s)
    bad = {
        "VILLAGE",
        "VILLAGENAME",
        "SUBDISTRICT",
        "SUBDISTRICTNAME",
        "OFFICENAME",
        "LOCALITY",
        "COLONY",
        "AREA",
        "NAME",
        "NA",
        "NONE",
        "NULL",
        "NIL",
        "NAN",
    }
    if key in bad:
        return ""

    # Remove postal office suffix for vocabulary usefulness.
    s = re.sub(
        r"(?i)\s+\b(?:G\.?P\.?O\.?|H\.?O\.?|S\.?O\.?|B\.?O\.?|P\.?O\.?|GPO|HO|SO|BO|PO)$",
        "",
        s,
    ).strip(" ,;:-|")

    if s.isupper() and len(s) > 3:
        s = s.title()

    return s


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


def is_xml_excel(path: Path) -> bool:
    head = path.read_bytes()[:500].lstrip()
    return head.startswith(b"<?xml") or b"mso-application" in head


def looks_like_header(values: list[str]) -> bool:
    cols = [normalize_col(v) for v in values]
    has_name = any(
        any(normalize_col(h) in c for h in NAME_HINTS)
        for c in cols
    )
    has_state_or_district = any("state" in c or "district" in c or "circle" in c for c in cols)
    return has_name and has_state_or_district


def iter_xml_excel_rows(path: Path) -> Iterable[dict]:
    header: list[str] | None = None
    data_rows = 0

    for _event, elem in ET.iterparse(path, events=("end",)):
        if local_name(elem.tag) != "Row":
            continue

        values = row_values(elem)
        elem.clear()

        if not any(values):
            continue

        if header is None:
            if looks_like_header(values):
                header = values
                print("Detected header:", header[:12])
            continue

        if values == header:
            continue

        if len([v for v in values if v]) < 2:
            continue

        data_rows += 1
        if data_rows % 100000 == 0:
            print(f"  parsed rows: {data_rows:,}")

        yield {
            header[i]: values[i] if i < len(values) else ""
            for i in range(len(header))
        }

    if header is None:
        print("WARNING: No usable header found in", path)


def iter_csv_rows(path: Path) -> Iterable[dict]:
    raw = path.read_bytes()
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


def iter_excel_rows(path: Path) -> Iterable[dict]:
    try:
        import pandas as pd
    except Exception:
        print("Install Excel support first: python -m pip install pandas xlrd openpyxl")
        return

    try:
        sheets = pd.read_excel(path, sheet_name=None, dtype=str)
    except Exception as exc:
        print(f"SKIP {path}: {exc}")
        return

    for _sheet_name, df in sheets.items():
        df = df.fillna("")
        headers = [str(c).strip() for c in df.columns]
        for _, row in df.iterrows():
            yield {headers[i]: clean_cell(row.iloc[i]) for i in range(len(headers))}


def iter_input_rows(path: Path) -> Iterable[dict]:
    suffix = path.suffix.lower()

    if suffix == ".xls" and is_xml_excel(path):
        yield from iter_xml_excel_rows(path)
        return

    if suffix in {".xls", ".xlsx"}:
        yield from iter_excel_rows(path)
        return

    if suffix in {".csv", ".txt", ".tsv"}:
        yield from iter_csv_rows(path)
        return


def input_files() -> list[Path]:
    if not INPUT_DIR.exists():
        return []

    return [
        p for p in INPUT_DIR.rglob("*")
        if p.is_file() and p.suffix.lower() in {".xls", ".xlsx", ".csv", ".txt", ".tsv"}
    ]


def row_state_matches_south(row: dict, headers: list[str]) -> bool:
    state_i = find_index(headers, STATE_HINTS)
    if state_i is None:
        # If source file is manually placed in south input but has no state column,
        # allow import. Use carefully.
        return True

    state = clean_cell(row.get(headers[state_i], ""))
    return state_key(state) in SOUTH_STATE_KEYS


def extract_records(row: dict) -> list[dict]:
    headers = list(row.keys())

    if not row_state_matches_south(row, headers):
        return []

    state_i = find_index(headers, STATE_HINTS)
    district_i = find_index(headers, DISTRICT_HINTS)
    pin_i = find_index(headers, PIN_HINTS)
    type_i = find_index(headers, TYPE_HINTS)

    def get(index: int | None) -> str:
        if index is None:
            return ""
        return clean_cell(row.get(headers[index], ""))

    state = get(state_i).upper()
    district = get(district_i).upper()
    pincode = get(pin_i)
    source_type = get(type_i)

    out = []

    # Extract from all possible name-like columns, not just one.
    for i, header in enumerate(headers):
        h = normalize_col(header)

        if not any(normalize_col(hint) in h for hint in NAME_HINTS):
            continue

        name = pretty_name(row.get(header, ""))
        key = name_key(name)

        if not key or len(key) < 3:
            continue

        out.append({
            "name": name,
            "state": state,
            "district": district,
            "pincode": pincode,
            "source_type": source_type or header,
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
        'description = "Indian place-name lookup, OCR address cleanup, South India locality vocabulary, correction, extraction, and address intelligence"',
        text,
    )
    PYPROJECT.write_text(text, encoding="utf-8")


def update_readme() -> None:
    if not README.exists():
        return

    text = README.read_text(encoding="utf-8", errors="ignore")
    note = """
### South India subdistrict, village, and locality vocabulary

South Indian subdistrict, village, post-office, locality, colony, and area names can be imported into:

```text
indic_places/data/custom_places.txt
```

The importer keeps only unique names and filters rows to South Indian states/UTs by state column when available.
"""

    if "### South India subdistrict, village, and locality vocabulary" not in text:
        README.write_text(text.rstrip() + "\n\n" + note.strip() + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", default="1.3.8")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not (ROOT / "indic_places").exists():
        raise SystemExit("ERROR: Run from indic_names_library repo root.")

    INPUT_DIR.mkdir(parents=True, exist_ok=True)

    files = input_files()
    if not files:
        print("No input files found.")
        print("Put South India LGD / pincode / locality CSV-XLS files here:")
        print(INPUT_DIR)
        return

    records = []
    seen_full = set()

    for file in files:
        print("Reading:", file)
        before = len(records)

        for row in iter_input_rows(file):
            for rec in extract_records(row):
                full_key = (
                    name_key(rec["name"]),
                    state_key(rec["state"]),
                    name_key(rec["district"]),
                    rec["pincode"],
                    name_key(rec["source_type"]),
                )

                if full_key in seen_full:
                    continue

                seen_full.add(full_key)
                records.append(rec)

        print(f"  records added: {len(records) - before:,}")

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
    print(f"Structured records read          : {len(records):,}")
    print(f"Unique South India names found   : {len(unique_names):,}")
    print(f"Already present in custom_places : {len(unique_names) - len(new_only):,}")
    print(f"New unique names to add          : {len(new_only):,}")
    print(f"Final custom_places count        : {len(merged):,}")

    if args.dry_run:
        print("DRY RUN ONLY. No files changed.")
        return

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    PKG_DATA.mkdir(parents=True, exist_ok=True)

    with OUT_FULL.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["name", "state", "district", "pincode", "source_type"],
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
