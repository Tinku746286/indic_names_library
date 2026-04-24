# Indic Places Library

A Python library for Indian place-name lookup, fuzzy matching, OCR address cleanup, and merged-word address segmentation.

It helps normalize Indian OCR addresses by identifying place names, address terms, districts, states, towns, villages, and postal-place aliases.

## Install

```bash
pip install --upgrade indic-places
```

## Usage

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

## Data

- 817,641 unique Indian place names
- 652,331 runtime OCR/custom place aliases
- India-wide GeoNames and postal vocabulary

## Attribution

This package includes data derived from GeoNames, licensed under CC BY 4.0.

Source: https://github.com/Tinku746286/indic_names_library
