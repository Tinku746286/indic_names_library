"""
indic_places — Indian Place Name Identifier & Fuzzy Lookup Library
==================================================================
Usage:
    from indic_places import IndicPlaces

    ip = IndicPlaces()
    results = ip.lookup("Bangalor")          # fuzzy match
    results = ip.lookup("Mumbai", kind="city")
    tags    = ip.tag("I live in Banglore near Koramanagala")
    info    = ip.info("Maharashtra")
"""

from .core import IndicPlaces
from .tagger import PlaceTagger

__version__ = "1.0.0"
__all__ = ["IndicPlaces", "PlaceTagger"]
