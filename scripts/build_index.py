"""Build the compact package data file for indic_places.

Run this from repo root:
    python scripts/build_index.py

It reads:
    data/india_places_full.csv
or fallback:
    data/unique_place_names.txt

It writes:
    indic_places/data/places_index.json.gz
"""
from __future__ import annotations

import csv
import gzip
import json
from pathlib import Path
from typing import Any, Dict, Optional

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "indic_places" / "data"
OUT_FILE = OUT_DIR / "places_index.json.gz"

# Import from local source tree.
import sys
sys.path.insert(0, str(ROOT))
from indic_places.core import _COMMON_SEGMENT_WORDS, normalize_place_name  # noqa: E402


def row_value(row: Dict[str, Any], *names: str) -> str:
    for name in names:
        val = row.get(name)
        if val is not None and str(val).strip():
            return str(val).strip()
    return ""


def make_record(row: Dict[str, Any]) -> Optional[Dict[str, str]]:
    name = row_value(row, "place_name", "officename", "office_name", "OfficeName", "name", "Place Name")
    norm = normalize_place_name(name)
    if not norm:
        return None

    office_type = row_value(row, "office_type", "officetype", "OfficeType").upper().replace(".", "")
    kind = "post_office"
    if office_type == "BO":
        kind = "village_or_branch_office"
    elif office_type == "SO":
        kind = "sub_office"
    elif office_type in {"HO", "GPO", "MDG"}:
        kind = "head_office"

    return {
        "name": name,
        "normalized": norm,
        "kind": kind,
        "state": row_value(row, "state", "StateName", "circle", "CircleName"),
        "district": row_value(row, "district", "District", "districtname", "DistrictName"),
        "pincode": row_value(row, "pincode", "Pincode", "pin", "PIN"),
        "source": "india_places_full.csv",
    }


def add_word_freq(word_freq: Dict[str, int], text: str, weight: int) -> None:
    norm = normalize_place_name(text)
    if not norm:
        return
    compact = norm.replace(" ", "")
    if compact:
        word_freq[compact] = word_freq.get(compact, 0) + weight
    for tok in norm.split():
        if len(tok) >= 2:
            word_freq[tok] = word_freq.get(tok, 0) + weight


def build_from_csv(path: Path) -> tuple[list[Dict[str, str]], Dict[str, int]]:
    records: list[Dict[str, str]] = []
    seen: set[tuple[str, str, str, str]] = set()
    word_freq: Dict[str, int] = dict(_COMMON_SEGMENT_WORDS)

    with path.open("r", encoding="utf-8", errors="ignore", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rec = make_record(row)
            if not rec:
                continue
            key = (rec["normalized"], rec["state"], rec["district"], rec["pincode"])
            if key in seen:
                continue
            seen.add(key)
            records.append(rec)

            add_word_freq(word_freq, rec["name"], 20)
            add_word_freq(word_freq, rec["district"], 80)
            add_word_freq(word_freq, rec["state"], 100)

    return records, word_freq


def build_from_unique_names(path: Path) -> tuple[list[Dict[str, str]], Dict[str, int]]:
    records: list[Dict[str, str]] = []
    seen: set[str] = set()
    word_freq: Dict[str, int] = dict(_COMMON_SEGMENT_WORDS)

    with path.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            name = line.strip()
            norm = normalize_place_name(name)
            if not norm or norm in seen:
                continue
            seen.add(norm)
            records.append(
                {
                    "name": name,
                    "normalized": norm,
                    "kind": "place",
                    "state": "",
                    "district": "",
                    "pincode": "",
                    "source": "unique_place_names.txt",
                }
            )
            add_word_freq(word_freq, name, 30)

    return records, word_freq


def main() -> None:
    csv_path = ROOT / "data" / "india_places_full.csv"
    txt_path = ROOT / "data" / "unique_place_names.txt"

    if csv_path.exists():
        records, word_freq = build_from_csv(csv_path)
    elif txt_path.exists():
        records, word_freq = build_from_unique_names(txt_path)
    else:
        raise FileNotFoundError("Expected data/india_places_full.csv or data/unique_place_names.txt")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "record_count": len(records),
        "records": records,
        "word_freq": word_freq,
    }
    with gzip.open(OUT_FILE, "wt", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))

    print(f"Wrote {OUT_FILE}")
    print(f"Records: {len(records):,}")
    print(f"Word dictionary: {len(word_freq):,}")


if __name__ == "__main__":
    main()
