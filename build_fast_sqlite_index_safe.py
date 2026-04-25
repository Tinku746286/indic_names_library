from __future__ import annotations

import argparse
import json
import re
import sqlite3
import time
from pathlib import Path


ROOT = Path(".")
DATA_DIR = ROOT / "indic_places" / "data"
CUSTOM_PLACES = DATA_DIR / "custom_places.txt"
PLACES_JSON = DATA_DIR / "places.json"
OUT_DB = DATA_DIR / "fast_places.sqlite"


def norm_key(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def consonant_key(value: str) -> str:
    return re.sub(r"[AEIOU]", "", norm_key(value))


def clean_name(value: str) -> str:
    s = str(value or "").strip()
    s = re.sub(r"\s+", " ", s)
    return s.strip(" ,;:-|[]{}()")


def iter_names_from_obj(obj):
    if obj is None:
        return

    if isinstance(obj, dict):
        for key in ("name", "place", "city", "district", "state", "office_name", "officename"):
            val = obj.get(key)
            if isinstance(val, str) and val.strip():
                yield val.strip()

        for val in obj.values():
            if isinstance(val, (dict, list)):
                yield from iter_names_from_obj(val)

        return

    if isinstance(obj, list):
        for item in obj:
            yield from iter_names_from_obj(item)


def iter_all_names():
    if CUSTOM_PLACES.exists():
        for line in CUSTOM_PLACES.read_text(encoding="utf-8", errors="ignore").splitlines():
            name = line.split("#", 1)[0].strip()
            if name:
                yield name

    if PLACES_JSON.exists():
        try:
            obj = json.loads(PLACES_JSON.read_text(encoding="utf-8", errors="ignore"))
            yield from iter_names_from_obj(obj)
        except Exception as exc:
            print("WARNING: places.json skipped:", exc)


def choose_best(existing: str, new_name: str) -> str:
    if not existing:
        return new_name

    e = clean_name(existing)
    n = clean_name(new_name)

    # Prefer readable canonical value but do not over-prefer tiny abbreviations.
    if len(n) >= 4 and len(n) < len(e):
        return n

    return e


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(OUT_DB))
    args = parser.parse_args()

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)

    t0 = time.time()

    names_by_norm: dict[str, str] = {}

    for name in iter_all_names():
        name = clean_name(name)
        n = norm_key(name)

        if len(n) < 2:
            continue

        names_by_norm[n] = choose_best(names_by_norm.get(n, ""), name)

    print("Unique normalized names:", f"{len(names_by_norm):,}")

    if out.exists():
        out.unlink()

    conn = sqlite3.connect(out)
    cur = conn.cursor()

    cur.execute("PRAGMA journal_mode=OFF")
    cur.execute("PRAGMA synchronous=OFF")
    cur.execute("PRAGMA temp_store=MEMORY")

    cur.execute("""
        CREATE TABLE places (
            norm TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            p1 TEXT,
            p2 TEXT,
            p3 TEXT,
            p4 TEXT,
            skip1p3 TEXT,
            cons TEXT,
            cons6 TEXT,
            length INTEGER
        )
    """)

    batch = []
    batch_size = 50000

    for norm, name in names_by_norm.items():
        cons = consonant_key(norm)
        batch.append((
            norm,
            name,
            norm[:1],
            norm[:2],
            norm[:3],
            norm[:4],
            norm[1:4] if len(norm) > 3 else "",
            cons,
            cons[:6],
            len(norm),
        ))

        if len(batch) >= batch_size:
            cur.executemany(
                "INSERT OR REPLACE INTO places(norm,name,p1,p2,p3,p4,skip1p3,cons,cons6,length) VALUES (?,?,?,?,?,?,?,?,?,?)",
                batch,
            )
            conn.commit()
            print("Inserted:", f"{cur.execute('SELECT COUNT(*) FROM places').fetchone()[0]:,}")
            batch.clear()

    if batch:
        cur.executemany(
            "INSERT OR REPLACE INTO places(norm,name,p1,p2,p3,p4,skip1p3,cons,cons6,length) VALUES (?,?,?,?,?,?,?,?,?,?)",
            batch,
        )
        conn.commit()

    print("Creating indexes...")
    cur.execute("CREATE INDEX idx_places_p4 ON places(p4)")
    cur.execute("CREATE INDEX idx_places_p3 ON places(p3)")
    cur.execute("CREATE INDEX idx_places_skip1p3 ON places(skip1p3)")
    cur.execute("CREATE INDEX idx_places_p2 ON places(p2)")
    cur.execute("CREATE INDEX idx_places_p1 ON places(p1)")
    cur.execute("CREATE INDEX idx_places_cons ON places(cons)")
    cur.execute("CREATE INDEX idx_places_cons6 ON places(cons6)")
    cur.execute("CREATE INDEX idx_places_len ON places(length)")
    conn.commit()

    cur.execute("VACUUM")
    conn.close()

    print("DONE")
    print("SQLite index:", out)
    print("Size MB:", round(out.stat().st_size / 1024 / 1024, 2))
    print("Time sec:", round(time.time() - t0, 2))


if __name__ == "__main__":
    main()
