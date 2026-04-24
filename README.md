# indic-places 🇮🇳

> **Indian Place Name Identifier** — fuzzy lookup, substring search, and NER tagging for Indian cities, states, villages, roads, areas, and landmarks.  
> Works like [SymSpellPy](https://github.com/mammothb/symspellpy) but built specifically for Indian place names.

---

## Install

```bash
# From GitHub (recommended until PyPI publish)
pip install git+https://github.com/Tinku746286/indic_names_library.git

# After PyPI publish
pip install indic-places
```

**Zero runtime dependencies.** Pure Python 3.8+.

---

## Quick Start

```python
from indic_places import IndicPlaces, PlaceTagger

ip = IndicPlaces()

# --- Fuzzy lookup (like SymSpellPy) ---
ip.lookup("Bangalor")
# [<PlaceResult name='Bangalore' kind='city' state='Karnataka' score=94.4>]

ip.lookup("Chennnai")
# [<PlaceResult name='Chennai' kind='city' state='Tamil Nadu' score=90.0>]

ip.lookup("Mahaarastra", kind="state")
# [<PlaceResult name='Maharashtra' kind='state' score=85.0>]

# --- Check if a word is an Indian place ---
"Mumbai" in ip       # True
"Blahblah" in ip     # False

# --- Substring / prefix search ---
ip.search("Nagar")               # all places containing "Nagar"
ip.search("pur", kind="village") # village names ending/containing "pur"

# --- Get metadata ---
ip.info("Karnataka")
# {'name': 'Karnataka', 'kind': 'state', 'cities': ['Bangalore', 'Mysore', ...]}

ip.info("Hyderabad")
# {'name': 'Hyderabad', 'kind': 'city', 'state': 'Telangana'}

# --- Cities in a state ---
ip.cities_in_state("Tamil Nadu")
# ['Chennai', 'Coimbatore', 'Madurai', ...]

# --- All states ---
ip.all_states()

# --- Dictionary stats ---
ip.stats()
# {'city': 900+, 'village': 1800+, 'area': 105, ...}
```

---

## NER Tagging — Extract Places from Free Text

```python
from indic_places import PlaceTagger

tagger = PlaceTagger()

result = tagger.tag("I travelled from Mumbai to Banglore, stopped at Pune")

print(result.places)
# [<TaggedPlace text='Mumbai' → 'Mumbai' kind='city' score=100.0>,
#  <TaggedPlace text='Banglore' → 'Bangalore' kind='city' score=94.4>,
#  <TaggedPlace text='Pune' → 'Pune' kind='city' score=100.0>]

print(result.annotated)
# "I travelled from [Mumbai|city|Maharashtra] to [Banglore→Bangalore|city|Karnataka], stopped at [Pune|city|Maharashtra]"

print(result.place_names)
# ['Mumbai', 'Bangalore', 'Pune']

# Convenience
tagger.extract_places("Office in Bengaluru, home near Mysore")
# ['Bangalore', 'Mysore']
```

---

## Command-Line Interface

```bash
# Fuzzy lookup
indic-places lookup "Bangalor"
indic-places lookup "Mumbai" --kind city

# Substring search
indic-places search "Nagar"
indic-places search "pur" --kind village

# Tag places in text
indic-places tag "I live in Banglore near Koramanagala"
indic-places tag "I live in Banglore" --annotated

# Get place info
indic-places info "Maharashtra"
indic-places info "Chennai"

# Dictionary statistics
indic-places stats
```

---

## API Reference

### `IndicPlaces(max_edit_distance=2, prefix_length=7)`

| Method | Description |
|--------|-------------|
| `lookup(query, kind=None, top_n=5, min_score=50.0)` | Fuzzy match — returns `List[PlaceResult]` |
| `search(substring, kind=None, top_n=20)` | Substring search — returns `List[PlaceResult]` |
| `is_place(query, min_score=70.0)` | Returns `True/False` |
| `info(name)` | Returns dict with name, kind, state, cities |
| `cities_in_state(state)` | Returns `List[str]` |
| `all_states()` | Returns `List[str]` |
| `stats()` | Returns `Dict[str, int]` counts per kind |
| `name in ip` | `__contains__` support |
| `len(ip)` | Total entries in dictionary |

### `PlaceResult`

| Attribute | Type | Description |
|-----------|------|-------------|
| `name` | str | Canonical place name |
| `kind` | str | `city\|state\|village\|road\|area\|landmark\|district\|union_territory` |
| `state` | str\|None | Parent state (for cities) |
| `edit_distance` | int | Levenshtein distance from query |
| `score` | float | Similarity score 0–100 |

### `PlaceTagger(max_edit_distance=2, min_score=60.0, min_token_length=4)`

| Method | Description |
|--------|-------------|
| `tag(text)` | Returns `TagResult` |
| `extract_places(text)` | Returns `List[str]` canonical names |

### `TagResult`

| Attribute | Description |
|-----------|-------------|
| `places` | `List[TaggedPlace]` |
| `annotated` | Original text with inline place tags |
| `place_names` | List of canonical names |

---

## Place Categories Covered

| Kind | Examples |
|------|---------|
| `state` | Maharashtra, Tamil Nadu, Uttar Pradesh … (36 states + UTs) |
| `union_territory` | Delhi, Chandigarh, Puducherry … |
| `city` | Mumbai, Bangalore, Chennai, Hyderabad … (900+) |
| `district` | Pune, Nashik, Wardha … |
| `area` | Koramangala, Banjara Hills, Connaught Place … (100+) |
| `landmark` | Taj Mahal, Gateway of India, Charminar … (70+) |
| `village` | Ramnagar, Sitapur, Krishnapur … (1800+) |
| `road` | MG Road, NH 44, Grand Trunk Road … (80+) |

---

## Expanding the Dataset

To add more place names, edit `scripts/build_data.py` and regenerate:

```bash
python scripts/build_data.py
```

Or add directly in Python:

```python
import json, os
path = os.path.join(os.path.dirname(indic_places.__file__), "data", "places.json")
with open(path) as f:
    data = json.load(f)

data["cities"]["My State"].append("My New City")

with open(path, "w") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
```

---

## Run Tests

```bash
pip install pytest
pytest tests/ -v
```

---

## License

MIT © Tinku — contributions welcome!
