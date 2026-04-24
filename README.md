# Indic Places Library

Indian place-name lookup, fuzzy matching, OCR address cleanup, and merged-word address segmentation for Python.

`indic-places` is useful when Indian addresses are extracted from OCR/scanned PDFs and words are joined together without spaces. It uses a large Indian place-name vocabulary to identify cities, towns, villages, districts, postal-place aliases, and common address tokens.

## Install from PyPI

Install latest version:

```bash
pip install --upgrade indic-places
```

Force latest version without cache:

```bash
python -m pip install --no-cache-dir --upgrade --force-reinstall indic-places
```

Install exact version:

```bash
python -m pip install indic-places==1.1.7
```

Add to `requirements.txt`:

```text
indic-places>=1.1.7
```

## Import

PyPI package name:

```text
indic-places
```

Python import name:

```python
from indic_places import IndicPlaces
```

## Data Stats

| Metric | Count |
|---|---:|
| Structured GeoNames + postal records | 815,477 |
| Unique Indian place names | 817,641 |
| Runtime OCR/custom place aliases | 652,331 |
| Coverage | India-wide |

## Quick Python Usage

```python
from indic_places import IndicPlaces

ip = IndicPlaces()

address = "PILASSERYADIVARAMPUTHUPPADIADIVARAM PUDUPADIKATTIPARAADIVARAM THAMARASSERYKOZHIKODE - 673586"
print(ip.normalize_address_spacing(address))
```

Output:

```text
PILASSERY ADIVARAM PUTHUPPADI ADIVARAM PUDUPADI KATTIPARA ADIVARAM THAMARASSERY KOZHIKODE - 673586
```

## Use from CMD / Terminal

### Check installed version

```cmd
python -c "import importlib.metadata as m; print(m.version('indic-places'))"
```

### Normalize an OCR address from CMD

```cmd
python -c "from indic_places import IndicPlaces; ip=IndicPlaces(); print(ip.normalize_address_spacing('PILASSERYADIVARAMPUTHUPPADIADIVARAM PUDUPADIKATTIPARAADIVARAM THAMARASSERYKOZHIKODE - 673586'))"
```

### Place lookup from CMD

```cmd
python -c "from indic_places import IndicPlaces; ip=IndicPlaces(); print(ip.lookup('Bangalor', top_n=5))"
```

### Extract places from text using CMD

```cmd
python -c "from indic_places import IndicPlaces; ip=IndicPlaces(); print(ip.extract_places('PONMINISSERY HOUSE PERAMBRA THRISSUR 680689'))"
```

### Word segmentation from CMD

```cmd
python -c "from indic_places import IndicPlaces; ip=IndicPlaces(); r=ip.segment('iliveinmumbaiorkerala'); print(r.segmented)"
```

## CLI Usage

If the console script is available after install:

```cmd
indic-places stats
```

```cmd
indic-places lookup Bangalor
```

```cmd
indic-places segment iliveinmumbaiorkerala
```

```cmd
indic-places extract "PONMINISSERY HOUSE PERAMBRA THRISSUR 680689"
```

If the command is not found, use:

```cmd
python -m indic_places.cli stats
```

## What This Library Solves

OCR may return Indian addresses like:

```text
PILASSERYADIVARAMPUTHUPPADIADIVARAM
KUNNUMPURATHHOUSEKALLARAP.O
THAMARASSERYKOZHIKODE
```

This library helps convert merged OCR text into cleaner address text by using Indian place names and address vocabulary.

Example:

```python
from indic_places import IndicPlaces

ip = IndicPlaces()

raw = "KUNNUMPURATHHOUSE KALLARA P.O KOTTAYAM - 686611"
clean = ip.normalize_address_spacing(raw)

print(clean)
```

Output style:

```text
KUNNUMPURATH HOUSE KALLARA P.O KOTTAYAM - 686611
```

## Main Features

- Indian place-name lookup
- OCR merged-address spacing
- Fuzzy lookup for misspelled place names
- Word segmentation for merged text
- Place extraction from address text
- India-wide GeoNames and postal vocabulary
- Runtime OCR/custom place aliases from `indic_places/data/custom_places.txt`

## Recommended Integration Pattern

For large OCR/document pipelines, do not create `IndicPlaces()` again and again. Create it once and reuse it.

```python
from indic_places import IndicPlaces

_PLACE_ENGINE = IndicPlaces()


def clean_address(address: str) -> str:
    address = " ".join(str(address or "").split()).strip(" ,:-|")

    if not address:
        return ""

    return _PLACE_ENGINE.normalize_address_spacing(address)
```

Use it after your extraction logic has already identified the address candidate.

```python
raw_address = "PILASSERYADIVARAMPUTHUPPADIADIVARAM PUDUPADIKATTIPARAADIVARAM THAMARASSERYKOZHIKODE - 673586"
final_address = clean_address(raw_address)
print(final_address)
```

## Use with an Existing Address Extractor

If your project already has a final address cleanup function, call `normalize_address_spacing()` there.

```python
from indic_places import IndicPlaces

_PLACE_ENGINE = IndicPlaces()


def finalize_address(address: str) -> str:
    address = " ".join(str(address or "").split()).strip(" ,:-|")

    if not address:
        return ""

    address = _PLACE_ENGINE.normalize_address_spacing(address)

    return " ".join(address.split()).strip(" ,:-|")
```

If your extraction function stores a best address candidate before returning, normalize before storing the final value.

```python
def evaluate_and_store_address(candidate: str):
    candidate = finalize_address(candidate)

    if not candidate:
        return False

    # Store candidate in your output dictionary/model.
    return True
```

## Complete Address Analysis

Use `analyze_address()` when you want spacing, extraction, correction, and details together.

```python
from indic_places import IndicPlaces

ip = IndicPlaces()

result = ip.analyze_address("indrapuriratibadbhopalmadhyapradesh")

print(result["clean_address"])
print(result["places"])
print(result["corrections"])
```

It returns:

```python
{
    "raw_address": "...",
    "clean_address": "...",
    "places": [
        {
            "text_found": "...",
            "name": "...",
            "state": "...",
            "district": "...",
            "pincode": "...",
            "score": ...
        }
    ],
    "corrections": [
        {
            "input": "...",
            "corrected": "...",
            "state": "...",
            "district": "...",
            "pincode": "..."
        }
    ],
    "tokens": [...]
}
```

This is useful for OCR address pipelines where you want:

```text
spacing + extraction + correction + state/district/pincode details
```

## Correct Place Name Search

`indic-places` also supports correction-style place search through:

```python
ip.correct_place_name(...)
ip.correct_place(...)
```

Use these when the user input is incomplete, misspelled, or has missing letters.

Examples:

```python
from indic_places import IndicPlaces

ip = IndicPlaces()

print(ip.correct_place_name("bhop"))          # Bhopal
print(ip.correct_place_name("bhopa"))         # Bhopal
print(ip.correct_place_name("kera"))          # Kerala
print(ip.correct_place_name("jhark"))         # Jharkhand
print(ip.correct_place_name("hrissu kerala")) # Thrissur
```

For correction with details:

```python
from indic_places import IndicPlaces

ip = IndicPlaces()

print(ip.correct_place("bhop"))
print(ip.correct_place("kera"))
print(ip.correct_place("jhark"))
```

Expected output style:

```python
{'name': 'Bhopal', 'state': 'MADHYA PRADESH', 'district': 'BHOPAL', 'pincode': ''}
{'name': 'Kerala', 'state': 'KERALA', 'district': '', 'pincode': ''}
{'name': 'Jharkhand', 'state': 'JHARKHAND', 'district': '', 'pincode': ''}
```

Difference between lookup and correction:

```text
lookup()              = gives search suggestions
correct_place_name()  = gives one clean corrected place name
correct_place()       = gives corrected place name with state/district/pincode details
```

This is useful for search boxes, OCR correction, address parsing, and user-entered location cleanup.

### CMD Examples

```cmd
python -c "from indic_places import IndicPlaces; ip=IndicPlaces(); print(ip.correct_place_name('bhop'))"
```

```cmd
python -c "from indic_places import IndicPlaces; ip=IndicPlaces(); print(ip.correct_place_name('kera')); print(ip.correct_place_name('jhark'))"
```

```cmd
python -c "from indic_places import IndicPlaces; ip=IndicPlaces(); print(ip.correct_place('hrissu kerala'))"
```

## Lookup Places

```python
from indic_places import IndicPlaces

ip = IndicPlaces()

results = ip.lookup("Bangalor", top_n=5)

for r in results:
    print(r.name, r.state, r.district, r.pincode, r.score)
```

## Extract Places from Text

```python
from indic_places import IndicPlaces

ip = IndicPlaces()

text = "PONMINISSERY HOUSE PERAMBRA THRISSUR 680689"
places = ip.extract_places(text)

for p in places:
    print(p.name, p.state, p.district, p.pincode)
```

## Word Segmentation

```python
from indic_places import IndicPlaces

ip = IndicPlaces()

result = ip.segment("iliveinmumbaiorkerala")
print(result.segmented)
print(result.score)
```

## Data Files

Runtime package data:

```text
indic_places/data/address_terms.txt
indic_places/data/custom_places.txt
indic_places/data/places_index.json.gz
```

Supporting/reference data in repository:

```text
data/unique_place_names.txt
data/geonames_india_places_full.csv.gz
data/by_state_geonames/
```

## Data Sources and Attribution

This package includes place-name vocabulary derived from open geographical datasets, including GeoNames India gazetteer and postal data.

GeoNames data is licensed under Creative Commons Attribution 4.0. Please credit GeoNames when using data derived from GeoNames.

Suggested attribution:

```text
This product includes data derived from GeoNames (https://www.geonames.org/), licensed under CC BY 4.0.
```

The data is provided as-is and may contain spelling variants, alternate names, outdated entries, or OCR-specific aliases.

## Privacy and Project Neutrality

This package is public and project-neutral.

It does not include private project names, private customer data, private document text, or proprietary extraction logic. Use it as a reusable Indian place-name and OCR address cleanup utility.

## Troubleshooting

### Old version still installing

```bash
python -m pip uninstall indic-places -y
python -m pip install --no-cache-dir --upgrade --force-reinstall indic-places
```

### Check installed version

```bash
python -c "import importlib.metadata as m; print(m.version('indic-places'))"
```

### Command not found

```bash
python -m indic_places.cli stats
```

### Works locally but not after pip install

Make sure package data files are included in the published wheel:

```text
MANIFEST.in
pyproject.toml
indic_places/data/custom_places.txt
indic_places/data/address_terms.txt
indic_places/data/places_index.json.gz
```

## Source Code

GitHub repository:

```text
https://github.com/Tinku746286/indic_names_library
```

For normal users, install from PyPI:

```bash
pip install --upgrade indic-places
```

### All-India village vocabulary

The package can include village names imported from official/LGD-style village datasets.

The import script adds only unique village names to:

```text
indic_places/data/custom_places.txt
```

Duplicate protection uses a normalized key, so names already present with different case, spacing, or punctuation are not added again.

This improves village-level matching and correction, for example:

```python
ip.correct_place_name("DORA CHHAPR")
ip.correct_place_name("MOHAN CHHAPR")
```

### Fast correction index

`correct_place_name()` uses an in-memory candidate index so it does not scan every village/place name for every query.

This improves correction speed after adding large all-India village vocabulary data.

```python
from indic_places import IndicPlaces

ip = IndicPlaces()

print(ip.correct_place_name("DORA CHHAPR"))
print(ip.correction_candidate_count("DORA CHHAPR"))
```

### Faster and safer correction

`correct_place_name()` first checks a fast administrative-name index for common states/districts/cities, then falls back to the larger village/place index.

This prevents short local aliases like `Bhopa`, `Kera`, or `Jharka` from beating common outputs like `Bhopal`, `Kerala`, and `Jharkhand`.

```python
from indic_places import IndicPlaces

ip = IndicPlaces()

print(ip.correct_place_name("bhop"))       # Bhopal
print(ip.correct_place_name("kera"))       # Kerala
print(ip.correct_place_name("jhark"))      # Jharkhand
print(ip.correct_place_name("hrissu"))     # Thrissur
```
