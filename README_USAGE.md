# Indic Places SymSpell-style engine patch

## After copying these files into your repo

```bash
cd indic_names_library
python -m pip install -U pip build
python scripts/build_index.py
python -m pip install -e .
```

## Use in Python

```python
from indic_places import IndicPlaces

ip = IndicPlaces()

print(ip.lookup("Bangalor", top_n=3))
print(ip.is_place("Perambra"))
print(ip.segment("iliveinmumbaiorkerala").segmented)
print(ip.normalize_address_spacing("PONMINISSERYHOUSEPERAMBRAPERAMBRAKANAKAMALACHIRAKAZHATHRISSUR"))
print([x.to_dict() for x in ip.extract_places("PONMINISSERY HOUSE PERAMBRA THRISSUR 680689")])
```

## Use from command line

```bash
indic-places lookup Bangalor
indic-places segment iliveinmumbaiorkerala
indic-places extract "PONMINISSERY HOUSE PERAMBRA THRISSUR 680689"
indic-places stats
```

## Install from GitHub after pushing generated index

```bash
pip install "indic-places @ git+https://github.com/Tinku746286/indic_names_library.git"
```

Then import with:

```python
from indic_places import IndicPlaces
```
