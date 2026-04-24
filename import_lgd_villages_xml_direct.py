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
INPUT_DIR = ROOT / "data" / "lgd_villages_input"
OUT_DIR = ROOT / "data"
PKG_DATA = ROOT / "indic_places" / "data"

CUSTOM_PLACES = PKG_DATA / "custom_places.txt"
OUT_UNIQUE = OUT_DIR / "all_india_villages_unique.txt"
OUT_FULL = OUT_DIR / "all_india_villages_full.csv"
OUT_FULL_GZ = OUT_DIR / "all_india_villages_full.csv.gz"
PYPROJECT = ROOT / "pyproject.toml"
README = ROOT / "README.md"


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

    key = name_key(s)
    if key in {"VILLAGE", "VILLAGENAME", "NAME", "NA", "NONE", "NULL", "NIL", "NAN"}:
        return ""

    # LGD sometimes stores names like "Jha Village"; keep as-is except title-case all-caps.
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


def is_real_village_header(values: list[str]) -> bool:
    cols = [normalize_col(v) for v in values]
    joined = " | ".join(cols)

    # Do NOT accept title rows like "All Villages of India".
    has_village_code = any(c == "village code" or "village code" in c for c in cols)
    has_village_name = any("village name" in c for c in cols)

    return has_village_code and has_village_name


def find_index(headers: list[str], *phrases: str) -> int | None:
    cols = [normalize_col(h) for h in headers]

    for phrase in phrases:
        p = normalize_col(phrase)
        for i, c in enumerate(cols):
            if c == p:
                return i

    for phrase in phrases:
        p = normalize_col(phrase)
        for i, c in enumerate(cols):
            if p and p in c:
                return i

    return None


def iter_xml_excel_rows(path: Path) -> Iterable[dict]:
    header: list[str] | None = None
    parsed_rows = 0
    data_rows = 0

    for event, elem in ET.iterparse(path, events=("end",)):
        if local_name(elem.tag) != "Row":
            continue

        parsed_rows += 1
        values = row_values(elem)
        elem.clear()

        if not any(values):
            continue

        if header is None:
            if is_real_village_header(values):
                header = values
                print("Detected village header:", header[:12])
            continue

        if values == header:
            continue

        # Skip title/footer/noise rows.
        if len([v for v in values if v]) < 3:
            continue

        data_rows += 1

        yield {
            header[i]: values[i] if i < len(values) else ""
            for i in range(len(header))
        }

        if data_rows % 100000 == 0:
            print(f"  parsed village rows: {data_rows:,}")

    if header is None:
        print("ERROR: Real village header not found.")
        print("Expected columns like: Village Code, Village Name(In English), State Name(In English)")


def iter_csv_rows(path: Path) -> Iterable[dict]:
    raw = path.read_bytes()
    text = None

    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin1"):
        try:
            text = raw.decode(enc)
            break
        except Exception:
            pass

    if not text:
        return

    delimiter = max([",", "\t", "|", ";"], key=lambda c: text[:4096].count(c))
    reader = csv.DictReader(text.splitlines(), delimiter=delimiter)

    for row in reader:
        yield row


def iter_input_rows(path: Path) -> Iterable[dict]:
    suffix = path.suffix.lower()

    if suffix == ".xls":
        head = path.read_bytes()[:500].lstrip()
        if head.startswith(b"<?xml") or b"mso-application" in head:
            yield from iter_xml_excel_rows(path)
            return

    if suffix in {".csv", ".txt", ".tsv"}:
        yield from iter_csv_rows(path)
        return

    if suffix in {".xls", ".xlsx"}:
        try:
            import pandas as pd
            sheets = pd.read_excel(path, sheet_name=None, dtype=str)
        except Exception as exc:
            print(f"SKIP {path}: {exc}")
            return

        for _name, df in sheets.items():
            df = df.fillna("")
            headers = [str(c).strip() for c in df.columns]
            for _, r in df.iterrows():
                yield {headers[i]: clean_cell(r.iloc[i]) for i in range(len(headers))}
        return


def extract_record(row: dict) -> dict | None:
    headers = list(row.keys())

    village_i = find_index(headers, "Village Name(In English)", "Village Name", "Village")
    if village_i is None:
        return None

    village_code_i = find_index(headers, "Village Code")
    state_i = find_index(headers, "State Name(In English)", "State Name", "State")
    district_i = find_index(headers, "District Name(In English)", "District Name", "District")
    subdistrict_i = find_index(headers, "Sub District Name", "Sub-District Name", "Subdistrict Name", "Sub District")
    pin_i = find_index(headers, "Pincode", "Pin Code", "PIN")

    def get(index: int | None) -> str:
        if index is None:
            return ""
        return clean_cell(row.get(headers[index], ""))

    village = pretty_name(get(village_i))
    if not village:
        return None

    return {
        "village": village,
        "state": get(state_i),
        "district": get(district_i),
        "subdistrict": get(subdistrict_i),
        "pincode": get(pin_i),
        "lgd_code": get(village_code_i),
    }


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
        'description = "Indian place-name lookup, OCR address cleanup, all-India village vocabulary, correction, extraction, and address intelligence"',
        text,
    )
    PYPROJECT.write_text(text, encoding="utf-8")


def update_readme() -> None:
    if not README.exists():
        return

    text = README.read_text(encoding="utf-8", errors="ignore")
    note = """
### All-India village vocabulary

Village names can be imported from LGD all-village XML Excel files. The importer adds only unique village names to:

```text
indic_places/data/custom_places.txt
```

Duplicate detection ignores case, spaces, and punctuation.
"""

    if "### All-India village vocabulary" not in text:
        README.write_text(text.rstrip() + "\n\n" + note.strip() + "\n", encoding="utf-8")


def input_files() -> list[Path]:
    if not INPUT_DIR.exists():
        return []

    return [
        p for p in INPUT_DIR.rglob("*")
        if p.is_file() and p.suffix.lower() in {".xls", ".xlsx", ".csv", ".txt", ".tsv"}
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", default="1.3.4")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not (ROOT / "indic_places").exists():
        raise SystemExit("ERROR: Run from indic_names_library repo root.")

    files = input_files()

    if not files:
        print("No files found in:", INPUT_DIR)
        return

    records = []
    structured_seen = set()

    for file in files:
        print("Reading:", file)
        before = len(records)

        for row in iter_input_rows(file):
            rec = extract_record(row)
            if not rec:
                continue

            skey = (
                name_key(rec["village"]),
                name_key(rec["state"]),
                name_key(rec["district"]),
                name_key(rec["subdistrict"]),
                rec["pincode"],
                rec["lgd_code"],
            )

            if skey in structured_seen:
                continue

            structured_seen.add(skey)
            records.append(rec)

        print(f"  records added: {len(records) - before:,}")

    unique_villages: dict[str, str] = {}
    for rec in records:
        key = name_key(rec["village"])
        if key:
            unique_villages.setdefault(key, rec["village"])

    existing_custom = read_existing_custom()
    new_only = {k: v for k, v in unique_villages.items() if k not in existing_custom}

    merged = dict(existing_custom)
    merged.update(new_only)

    print("=" * 80)
    print("SUMMARY")
    print(f"Structured village records read : {len(records):,}")
    print(f"Unique village names found      : {len(unique_villages):,}")
    print(f"Already present in custom_places: {len(unique_villages) - len(new_only):,}")
    print(f"New unique names to add         : {len(new_only):,}")
    print(f"Final custom_places count       : {len(merged):,}")

    if args.dry_run:
        print("DRY RUN ONLY. No files changed.")
        return

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    PKG_DATA.mkdir(parents=True, exist_ok=True)

    with OUT_FULL.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["village", "state", "district", "subdistrict", "pincode", "lgd_code"],
        )
        writer.writeheader()
        writer.writerows(records)

    with OUT_FULL.open("rb") as src, gzip.open(OUT_FULL_GZ, "wb", compresslevel=9) as dst:
        shutil.copyfileobj(src, dst)

    OUT_UNIQUE.write_text(
        "\n".join(sorted(unique_villages.values(), key=lambda x: x.upper())) + "\n",
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
