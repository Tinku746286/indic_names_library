"""Indian place-name identifier and OCR word segmentation library."""

from .core import IndicPlaces, PlaceResult, SegmentResult, TaggedPlace, normalize_place_name, normalize_text

__version__ = "1.1.0"

__all__ = [
    "IndicPlaces",
    "PlaceResult",
    "SegmentResult",
    "TaggedPlace",
    "normalize_place_name",
    "normalize_text",
]
