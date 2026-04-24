"""
indic_places.core
=================
Core IndicPlaces class — loads the place dictionary and provides
SymSpellPy-style fuzzy lookup, search, and info methods.
"""

from __future__ import annotations
import json
import os
import unicodedata
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class PlaceResult:
    """A single lookup result."""
    name: str
    kind: str          # city | state | village | road | area | landmark | district | union_territory
    state: Optional[str] = None
    edit_distance: int = 0
    score: float = 100.0  # 0-100, higher is better

    def __repr__(self):
        s = f"<PlaceResult name={self.name!r} kind={self.kind!r}"
        if self.state:
            s += f" state={self.state!r}"
        s += f" score={self.score:.1f}>"
        return s


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize(text: str) -> str:
    """Lowercase, strip accents, collapse whitespace."""
    text = text.strip().lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(text.split())


def _edit_distance(a: str, b: str) -> int:
    """Standard Levenshtein distance (Wagner-Fischer)."""
    if a == b:
        return 0
    if len(a) == 0:
        return len(b)
    if len(b) == 0:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i]
        for j, cb in enumerate(b, 1):
            curr.append(min(
                prev[j] + 1,
                curr[j - 1] + 1,
                prev[j - 1] + (0 if ca == cb else 1)
            ))
        prev = curr
    return prev[len(b)]


def _score(query: str, candidate: str, dist: int) -> float:
    """
    Similarity score 0–100.
    Penalises edit distance relative to the longer string.
    Bonus if the candidate starts with the query.
    """
    max_len = max(len(query), len(candidate), 1)
    base = max(0.0, 100.0 * (1.0 - dist / max_len))
    if candidate.startswith(query):
        base = min(100.0, base + 10.0)
    return round(base, 2)


# ---------------------------------------------------------------------------
# Delete-neighbourhood (SymSpell-lite) index
# ---------------------------------------------------------------------------

def _deletes(word: str, max_dist: int) -> set:
    """Generate all delete variants up to max_dist edits."""
    result = {word}
    queue = {word}
    for _ in range(max_dist):
        next_q = set()
        for w in queue:
            for i in range(len(w)):
                deleted = w[:i] + w[i+1:]
                if deleted not in result:
                    result.add(deleted)
                    next_q.add(deleted)
        queue = next_q
    return result


# ---------------------------------------------------------------------------
# IndicPlaces
# ---------------------------------------------------------------------------

class IndicPlaces:
    """
    Indian place name identifier with fuzzy (SymSpell-style) lookup.

    Parameters
    ----------
    max_edit_distance : int
        Maximum edit distance for fuzzy matches (default 2).
    prefix_length : int
        Prefix length for the delete-neighbourhood index (default 7).

    Examples
    --------
    >>> ip = IndicPlaces()
    >>> ip.lookup("Bangalor")
    [<PlaceResult name='Bangalore' kind='city' state='Karnataka' score=94.4>]
    >>> ip.lookup("mumbai", kind="city")
    [<PlaceResult name='Mumbai' kind='city' state='Maharashtra' score=100.0>]
    >>> ip.search("Nagar")
    [...]
    >>> ip.info("Delhi")
    {'name': 'Delhi', 'kind': 'state', ...}
    """

    _KIND_ORDER = ["city", "state", "district", "union_territory", "area", "landmark", "village", "road"]

    def __init__(self, max_edit_distance: int = 2, prefix_length: int = 7):
        self.max_edit_distance = max_edit_distance
        self.prefix_length = prefix_length

        self._data: Dict[str, Any] = {}          # raw JSON data
        self._entries: List[Dict] = []            # flat list of {name, kind, state, norm}
        self._index: Dict[str, List[int]] = {}   # delete-variant → entry indices
        self._state_map: Dict[str, List[str]] = {}  # state → list of city names

        self._load()
        self._build_index()

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def _load(self):
        data_path = os.path.join(os.path.dirname(__file__), "data", "places.json")
        with open(data_path, encoding="utf-8") as f:
            self._data = json.load(f)

        entries = []

        def add(name, kind, state=None):
            entries.append({"name": name, "kind": kind, "state": state, "norm": _normalize(name)})

        for name in self._data.get("states", []):
            add(name, "state")

        for name in self._data.get("union_territories", []):
            add(name, "union_territory")

        for state, cities in self._data.get("cities_by_state", {}).items():
            self._state_map[state] = cities
            for city in cities:
                add(city, "city", state=state)

        for name in self._data.get("districts", []):
            add(name, "district")

        for name in self._data.get("areas", []):
            add(name, "area")

        for name in self._data.get("landmarks", []):
            add(name, "landmark")

        for name in self._data.get("villages", []):
            add(name, "village")

        for name in self._data.get("roads", []):
            add(name, "road")

        self._entries = entries

    # ------------------------------------------------------------------
    # Index
    # ------------------------------------------------------------------

    def _build_index(self):
        index: Dict[str, List[int]] = {}
        for i, entry in enumerate(self._entries):
            norm = entry["norm"]
            prefix = norm[:self.prefix_length]
            for variant in _deletes(prefix, self.max_edit_distance):
                index.setdefault(variant, []).append(i)
        self._index = index

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def lookup(
        self,
        query: str,
        kind: Optional[str] = None,
        top_n: int = 5,
        min_score: float = 50.0,
    ) -> List[PlaceResult]:
        """
        Fuzzy-match *query* against the place dictionary.

        Parameters
        ----------
        query    : str  — the place name to look up (possibly misspelled)
        kind     : str  — filter to a specific category:
                         'city' | 'state' | 'village' | 'road' | 'area' |
                         'landmark' | 'district' | 'union_territory'
        top_n    : int  — maximum results to return (default 5)
        min_score: float — minimum similarity score 0-100 (default 50)

        Returns
        -------
        List[PlaceResult] sorted by score descending.
        """
        norm_q = _normalize(query)
        prefix_q = norm_q[:self.prefix_length]

        # Collect candidate indices via delete-neighbourhood
        candidate_idx: set = set()
        for variant in _deletes(prefix_q, self.max_edit_distance):
            for idx in self._index.get(variant, []):
                candidate_idx.add(idx)

        results = []
        for idx in candidate_idx:
            entry = self._entries[idx]
            if kind and entry["kind"] != kind:
                continue
            dist = _edit_distance(norm_q, entry["norm"])
            if dist > self.max_edit_distance + len(norm_q) // 3:
                continue
            sc = _score(norm_q, entry["norm"], dist)
            if sc >= min_score:
                results.append(PlaceResult(
                    name=entry["name"],
                    kind=entry["kind"],
                    state=entry.get("state"),
                    edit_distance=dist,
                    score=sc,
                ))

        results.sort(key=lambda r: (-r.score, r.edit_distance, self._KIND_ORDER.index(r.kind) if r.kind in self._KIND_ORDER else 99))
        return results[:top_n]

    def search(self, substring: str, kind: Optional[str] = None, top_n: int = 20) -> List[PlaceResult]:
        """
        Substring / prefix search — returns all entries whose normalised
        name *contains* the query string.

        Parameters
        ----------
        substring : str  — substring to search for
        kind      : str  — optional category filter
        top_n     : int  — max results (default 20)
        """
        norm_q = _normalize(substring)
        results = []
        for entry in self._entries:
            if kind and entry["kind"] != kind:
                continue
            if norm_q in entry["norm"]:
                results.append(PlaceResult(
                    name=entry["name"],
                    kind=entry["kind"],
                    state=entry.get("state"),
                    edit_distance=0,
                    score=100.0 if entry["norm"] == norm_q else 80.0,
                ))
        results.sort(key=lambda r: (-r.score, r.name))
        return results[:top_n]

    def is_place(self, query: str, min_score: float = 70.0) -> bool:
        """Return True if *query* matches any known place at >= min_score."""
        hits = self.lookup(query, top_n=1, min_score=min_score)
        return len(hits) > 0

    def info(self, name: str) -> Optional[Dict[str, Any]]:
        """
        Return metadata for an exact (case-insensitive) place name.

        Returns a dict with keys: name, kind, state, cities (if state).
        Returns None if not found.
        """
        norm_q = _normalize(name)
        for entry in self._entries:
            if entry["norm"] == norm_q:
                result = {"name": entry["name"], "kind": entry["kind"]}
                if entry.get("state"):
                    result["state"] = entry["state"]
                if entry["kind"] == "state" and entry["name"] in self._state_map:
                    result["cities"] = self._state_map[entry["name"]]
                return result
        return None

    def cities_in_state(self, state: str) -> List[str]:
        """Return list of cities for the given state name."""
        norm_q = _normalize(state)
        for s, cities in self._state_map.items():
            if _normalize(s) == norm_q:
                return cities
        return []

    def all_states(self) -> List[str]:
        """Return all state names."""
        return list(self._data.get("states", []))

    def all_kinds(self) -> List[str]:
        """Return all supported place kinds/categories."""
        return list(self._KIND_ORDER)

    def stats(self) -> Dict[str, int]:
        """Return count of entries per kind."""
        counts: Dict[str, int] = {}
        for entry in self._entries:
            counts[entry["kind"]] = counts.get(entry["kind"], 0) + 1
        return counts

    # ------------------------------------------------------------------
    # Dictionary-style access  (like SymSpellPy word dict)
    # ------------------------------------------------------------------

    def __contains__(self, name: str) -> bool:
        return self.is_place(name)

    def __len__(self) -> int:
        return len(self._entries)

    def __repr__(self):
        return f"<IndicPlaces entries={len(self._entries)} max_edit_distance={self.max_edit_distance}>"
