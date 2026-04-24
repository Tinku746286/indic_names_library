# Indic Names Library - India Places Database

A comprehensive database of **165,627 Indian place names** (post offices, villages, towns, cities)
sourced from India Post, covering all 37 states & Union Territories.

## Stats
| Metric | Count |
|--------|-------|
| Total records | 165,627 |
| Unique place names | 145,086 |
| States & UTs covered | 37 |

## Structure
```
data/
├── india_places_full.csv          # Full dataset as CSV
├── unique_place_names.txt         # 145,086 unique place names
├── state_summary.json             # Stats per state/UT
├── chunks/india_places_part01-06.json   # Split JSON (30K records each)
└── by_state/<STATE>.json          # One file per state/UT
```

## Schema
```json
{
  "place_name":  "Kothimir B.O",
  "district":    "KUMURAM BHEEM ASIFABAD",
  "state":       "TELANGANA",
  "pincode":     "504273",
  "office_type": "BO",
  "delivery":    true,
  "division":    "Adilabad Division",
  "region":      "Hyderabad Region",
  "circle":      "Telangana Circle",
  "latitude":    19.3638689,
  "longitude":   79.5376658
}
```

## Usage (Python)
```python
import csv, json

# Load all records
with open("data/india_places_full.csv") as f:
    places = list(csv.DictReader(f))
print(len(places), "records")

# Load by state
with open("data/by_state/KARNATAKA.json") as f:
    karnataka = json.load(f)

# Unique names
names = open("data/unique_place_names.txt").read().splitlines()
```

## Source
India Post pincode directory via [india-pincode](https://www.npmjs.com/package/india-pincode) npm package.
