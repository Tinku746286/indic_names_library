# Indic Places Library

Indian place-name lookup, fuzzy matching, OCR address spacing, and merged-word segmentation for Python.

This package is designed for public use in Indian address processing, OCR cleanup, place-name identification, and document extraction workflows.

## Install from PyPI

Install the latest version:

```bash
pip install --upgrade indic-places
```

Clean reinstall without cache:

```bash
python -m pip install --no-cache-dir --upgrade --force-reinstall indic-places
```

Install a specific version:

```bash
python -m pip install indic-places==1.1.5
```

Add to `requirements.txt`:

```text
indic-places>=1.1.5
```

## Import

The PyPI package name is:

```text
indic-places
```

The Python import is:

```python
from indic_places import IndicPlaces
```

## Data Stats

| Metric | Count |
|---|---:|
| Structured GeoNames + postal records | 815,477 |
| Unique place names | 817,641 |
| Runtime OCR/custom place aliases | 652,331 |
| Coverage | India-wide |

## Quick Usage

```python
from indic_places import IndicPlaces

ip = IndicPlaces()

address = "PILASSERYADIVARAMPUTHUPPADIADIVARAM PUDUPADIKATTIPARAADIVARAM THAMARASSERYKOZHIKODE - 673586"
print(ip.normalize_address_spacing(address))
```

Expected output:

```text
PILASSERY ADIVARAM PUTHUPPADI ADIVARAM PUDUPADI KATTIPARA ADIVARAM THAMARASSERY KOZHIKODE - 673586
```

## What This Library Solves

OCR often returns Indian addresses as merged text:

```text
PILASSERYADIVARAMPUTHUPPADIADIVARAM
KUNNUMPURATHHOUSEKALLARAP.O
THAMARASSERYKOZHIKODE
```

`indic-places` uses Indian place vocabulary and address terms to safely space merged OCR tokens.

## Main Features

- Indian place-name lookup
- OCR merged-address spacing
- SymSpell-style fuzzy lookup
- Word segmentation
- Place extraction from text
- India-wide GeoNames and postal vocabulary
- Runtime OCR/custom place aliases from `indic_places/data/custom_places.txt`

## Use in Any Python Project

### 1. Install

```bash
python -m pip install --upgrade indic-places
```

### 2. Create the Engine Once

```python
from indic_places import IndicPlaces

place_engine = IndicPlaces()
```

### 3. Normalize an OCR Address

```python
raw_address = "PILASSERYADIVARAMPUTHUPPADIADIVARAM PUDUPADIKATTIPARAADIVARAM THAMARASSERYKOZHIKODE - 673586"

clean_address = place_engine.normalize_address_spacing(raw_address)

print(clean_address)
```

Output:

```text
PILASSERY ADIVARAM PUTHUPPADI ADIVARAM PUDUPADI KATTIPARA ADIVARAM THAMARASSERY KOZHIKODE - 673586
```

## Recommended Integration Pattern for OCR Pipelines

Use the library at the final address-cleanup stage, after your extraction logic has already identified the address candidate.

```python
from indic_places import IndicPlaces

_PLACE_ENGINE = None


def get_place_engine():
    global _PLACE_ENGINE

    if _PLACE_ENGINE is None:
        _PLACE_ENGINE = IndicPlaces()

    return _PLACE_ENGINE


def normalize_address(address: str) -> str:
    address = " ".join(str(address or "").split()).strip(" ,:-|")

    if not address:
        return ""

    engine = get_place_engine()
    return engine.normalize_address_spacing(address)
```

## Use with an Existing Extractor Function

If your project has a final address cleanup function, call `normalize_address_spacing()` inside that final cleanup function.

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

If your extraction function stores the best address candidate before returning, normalize before storing the final value.

```python
def evaluate_and_store_address(candidate: str):
    candidate = finalize_address(candidate)

    if not candidate:
        return False

    # Store candidate in your output dictionary/model.
    return True
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

## CLI Usage

Show stats:

```bash
indic-places stats
```

Lookup:

```bash
indic-places lookup Bangalor
```

Segment text:

```bash
indic-places segment iliveinmumbaiorkerala
```

Extract places:

```bash
indic-places extract "PONMINISSERY HOUSE PERAMBRA THRISSUR 680689"
```

## Recommended Pattern for Large OCR Pipelines

Bad:

```python
def clean_address(address):
    ip = IndicPlaces()
    return ip.normalize_address_spacing(address)
```

Good:

```python
from indic_places import IndicPlaces

_PLACE_ENGINE = IndicPlaces()

def clean_address(address):
    return _PLACE_ENGINE.normalize_address_spacing(address)
```

This loads the place index once and is better for large document batches.

## Data Files

The package includes runtime data files:

```text
indic_places/data/address_terms.txt
indic_places/data/custom_places.txt
indic_places/data/places_index.json.gz
```

The repository also contains supporting/reference data:

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
