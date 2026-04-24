# Indic Places Library

Indian place-name lookup, fuzzy matching, OCR address spacing, and merged-word segmentation for Python.

This library is mainly built for Indian OCR/address extraction work, especially sanction-letter extraction pipelines where borrower addresses often come from scanned PDFs and OCR output.

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
python -m pip install indic-places==1.1.4
```

Add to `requirements.txt`:

```text
indic-places>=1.1.4
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

OCR often returns Indian addresses like this:

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

## Use in Your Project: SureCreditSanction Engine

Your project is a sanction-letter extraction system. It extracts fields such as borrower address, borrower name, branch name/code, regional office, sanction date/reference, period of limit, and validity of sanction.

For this project, `indic-places` should be used at the final borrower-address cleanup stage.

### Install in SureCreditSanction Engine

```bash
cd "C:\Users\KUMAR TINKU\Downloads\SureCreditSanction-Engine\SureCreditSanction-Engine\sure_sanction"
.venv\Scripts\activate
python -m pip install --upgrade indic-places
```

Check installed version:

```bash
python -c "import importlib.metadata as m; print(m.version('indic-places'))"
```

### Add Import in Extractor File

Add this near the top of the file where borrower address extraction is implemented:

```python
try:
    from indic_places import IndicPlaces
except Exception:
    IndicPlaces = None
```

### Add Lazy Loader

Do not create `IndicPlaces()` inside every function call. Load it once.

```python
_INDIC_PLACE_ENGINE = None
_INDIC_PLACE_ENGINE_FAILED = False


def _get_indic_place_engine():
    global _INDIC_PLACE_ENGINE, _INDIC_PLACE_ENGINE_FAILED

    if _INDIC_PLACE_ENGINE_FAILED:
        return None

    if _INDIC_PLACE_ENGINE is None:
        if IndicPlaces is None:
            _INDIC_PLACE_ENGINE_FAILED = True
            return None

        try:
            _INDIC_PLACE_ENGINE = IndicPlaces()
        except Exception:
            _INDIC_PLACE_ENGINE_FAILED = True
            return None

    return _INDIC_PLACE_ENGINE


def _normalize_address_with_indic_places(address):
    s = str(address or "").strip()
    if not s:
        return ""

    engine = _get_indic_place_engine()
    if engine is None:
        return s

    try:
        fixed = engine.normalize_address_spacing(s)
        return " ".join(str(fixed or s).split())
    except Exception:
        return s
```

### Use in `_finalize_address`

Call the library during final address cleanup:

```python
def _finalize_address(s):
    if not s:
        return ""

    s = str(s).strip()
    s = _normalize_address_with_indic_places(s)

    return " ".join(s.split()).strip(" ,:-|")
```

### Important for `get_borrower_address()`

If your `get_borrower_address()` function has early returns, call `_finalize_address(cand)` inside `_evaluate_and_store()` before storing `best_address`.

```python
def _evaluate_and_store(cand, current_source):
    nonlocal best_address, source

    if not cand:
        return False

    cand = _clean_addr_value(cand)

    # Important: normalize before best_address is stored.
    cand = _finalize_address(cand)

    if _is_bad_borrower_address_text(cand) or len(cand.strip()) <= 8:
        return False

    if not best_address or len(cand) > len(best_address):
        best_address = cand
        source = current_source

    return bool(re.search(r"\b\d{6}\b", cand))
```

## Example: Borrower Address Cleanup

Input:

```python
borrower_address = "PILASSERYADIVARAMPUTHUPPADIADIVARAM PUDUPADIKATTIPARAADIVARAM THAMARASSERYKOZHIKODE - 673586"
```

Code:

```python
from indic_places import IndicPlaces

ip = IndicPlaces()
borrower_address = ip.normalize_address_spacing(borrower_address)

print(borrower_address)
```

Output:

```text
PILASSERY ADIVARAM PUTHUPPADI ADIVARAM PUDUPADI KATTIPARA ADIVARAM THAMARASSERY KOZHIKODE - 673586
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

This loads the place index once and is better for processing thousands or lakhs of documents.

## Troubleshooting

### Old version still installing

```bash
python -m pip uninstall indic-places -y
python -m pip install --no-cache-dir --upgrade --force-reinstall indic-places
```

### Check version

```bash
python -c "import importlib.metadata as m; print(m.version('indic-places'))"
```

### Command not found

```bash
python -m indic_places.cli stats
```

### Works locally but not after pip install

Make sure these package data files are included:

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
