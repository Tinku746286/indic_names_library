# Indic Places Library — Installation & Usage Guide

This package provides an Indian place-name dictionary and SymSpell-style lookup/segmentation engine for OCR cleanup, address spacing, and place-name identification.

It is useful for cases like:

```text
iliveinmumbaiorkerala
# -> i live in mumbai or kerala

PONMINISSERYHOUSEPERAMBRAPERAMBRAKANAKAMALACHIRAKAZHATHRISSUR
# -> PONMINISSERY HOUSE PERAMBRA PERAMBRA KANAKAMALA CHIRAKA ZHA THRISSUR
```

The package contains a compiled Indian place index generated from the repository data.

---

## 1. Install from GitHub

Use this command in any Python project:

```cmd
python -m pip install "indic-places @ git+https://github.com/Tinku746286/indic_names_library.git"
```

If `python` is not detected, use:

```cmd
py -m pip install "indic-places @ git+https://github.com/Tinku746286/indic_names_library.git"
```

---

## 2. Upgrade to latest GitHub version

When new changes are pushed to GitHub, update the installed package using:

```cmd
python -m pip install --upgrade --force-reinstall "indic-places @ git+https://github.com/Tinku746286/indic_names_library.git"
```

---

## 3. Uninstall

```cmd
python -m pip uninstall indic-places -y
```

---

## 4. Verify installation

Run:

```cmd
python -c "from indic_places import IndicPlaces; ip=IndicPlaces(); print(ip.segment('iliveinmumbaiorkerala').segmented)"
```

Expected output:

```text
i live in mumbai or kerala
```

You can also test the CLI:

```cmd
indic-places stats
indic-places lookup Bangalor
indic-places segment iliveinmumbaiorkerala
indic-places extract "PONMINISSERY HOUSE PERAMBRA THRISSUR 680689"
```

---

## 5. Basic Python usage

```python
from indic_places import IndicPlaces

ip = IndicPlaces()

print(ip.segment("iliveinmumbaiorkerala").segmented)
print(ip.lookup("Bangalor"))
print(ip.extract_places("PONMINISSERY HOUSE PERAMBRA THRISSUR 680689"))
```

---

## 6. Use for OCR address spacing

This is the most common use case for sanction-letter OCR output.

```python
from indic_places import IndicPlaces

_PLACE_ENGINE = IndicPlaces()


def fix_merged_address_spacing(address: str) -> str:
    if not address:
        return ""

    return _PLACE_ENGINE.normalize_address_spacing(address)


addr = "PONMINISSERYHOUSEPERAMBRAPERAMBRAKANAKAMALACHIRAKAZHATHRISSUR"
print(fix_merged_address_spacing(addr))
```

Use this after OCR extraction and before final output cleaning.

Example integration:

```python
def clean_borrower_address(raw_address: str) -> str:
    raw_address = str(raw_address or "").strip()

    if not raw_address:
        return ""

    spaced = _PLACE_ENGINE.normalize_address_spacing(raw_address)

    return " ".join(spaced.split())
```

---

## 7. Place lookup

```python
from indic_places import IndicPlaces

ip = IndicPlaces()

results = ip.lookup("Perambra", top_n=5)

for r in results:
    print(r.name, r.state, r.district, r.pincode, r.score)
```

Each result contains:

```python
r.name
r.normalized
r.kind
r.state
r.district
r.pincode
r.score
r.edit_distance
r.source
```

---

## 8. Check whether a word is an Indian place

```python
from indic_places import IndicPlaces

ip = IndicPlaces()

print(ip.is_place("Mumbai"))
print(ip.is_place("Perambra"))
print(ip.is_place("Randomword"))
```

---

## 9. Extract places from text

```python
from indic_places import IndicPlaces

ip = IndicPlaces()

text = "PONMINISSERY HOUSE PERAMBRA THRISSUR 680689"

places = ip.extract_places(text)

for p in places:
    print(p.name, p.state, p.district, p.pincode)
```

---

## 10. Word segmentation

Use this when OCR merges words.

```python
from indic_places import IndicPlaces

ip = IndicPlaces()

result = ip.segment("iliveinmumbaiorkerala")

print(result.segmented)
print(result.score)
```

Output:

```text
i live in mumbai or kerala
```

---

## 11. CLI commands

Show package stats:

```cmd
indic-places stats
```

Lookup a place:

```cmd
indic-places lookup Bangalor
```

Segment merged text:

```cmd
indic-places segment iliveinmumbaiorkerala
```

Extract places from a sentence/address:

```cmd
indic-places extract "PONMINISSERY HOUSE PERAMBRA THRISSUR 680689"
```

---

## 12. Local development setup

Clone the repo:

```cmd
cd /d "C:\Users\KUMAR TINKU\Downloads"
git clone https://github.com/Tinku746286/indic_names_library.git
cd indic_names_library
```

Install in editable mode:

```cmd
python -m pip install -e .
```

Rebuild the compiled index after changing source CSV/data files:

```cmd
python scripts\build_index.py
python -m pip install -e .
```

Run tests:

```cmd
python -m pytest
```

---

## 13. Push changes to GitHub

```cmd
git status
git add .
git commit -m "Update usage documentation"
git push origin main
```

---

## 14. Recommended use in large OCR pipeline

Do not create `IndicPlaces()` inside every function call.

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

This loads the place index only once and is better for processing thousands or lakhs of documents.

---

## 15. Suggested integration in sanction extraction project

```python
from indic_places import IndicPlaces

_PLACE_ENGINE = IndicPlaces()


def normalize_ocr_address(address: str) -> str:
    address = str(address or "").strip()

    if not address:
        return ""

    # Fix merged OCR tokens using Indian place vocabulary.
    address = _PLACE_ENGINE.normalize_address_spacing(address)

    # Final whitespace cleanup.
    address = " ".join(address.split())

    return address
```

Then call it before final output:

```python
borrower_address = normalize_ocr_address(borrower_address)
```

---

## 16. Troubleshooting

### Problem: `indic-places` command not found

Try:

```cmd
python -m indic_places.cli stats
```

Or reinstall:

```cmd
python -m pip install --upgrade --force-reinstall "indic-places @ git+https://github.com/Tinku746286/indic_names_library.git"
```

### Problem: old version is still running

Uninstall and reinstall:

```cmd
python -m pip uninstall indic-places -y
python -m pip install "indic-places @ git+https://github.com/Tinku746286/indic_names_library.git"
```

### Problem: package works locally but not after pip install

Make sure these files are committed and pushed:

```text
MANIFEST.in
pyproject.toml
indic_places/data/places_index.json.gz
indic_places/core.py
indic_places/cli.py
indic_places/__init__.py
scripts/build_index.py
```

### Problem: lookup result is not the expected famous city

The engine uses fuzzy edit-distance matching from the available dataset. Some famous city aliases may need alias boosting, for example:

```text
bangalor -> bangalore / bengaluru
bombay -> mumbai
calcutta -> kolkata
madras -> chennai
```

This can be improved by adding an alias dictionary in future versions.

---

## 17. Current install command to remember

```cmd
python -m pip install "indic-places @ git+https://github.com/Tinku746286/indic_names_library.git"
```
