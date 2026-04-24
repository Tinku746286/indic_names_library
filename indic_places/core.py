"""
indic_places.core
=================

Fast Indian place-name lookup, fuzzy correction, tagging support, and
SymSpell-style word segmentation for OCR/address text.

No runtime dependencies.
"""
from __future__ import annotations

import csv
import gzip
import json
import math
import re
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

try:
    from importlib import resources
except ImportError:  # pragma: no cover
    import importlib_resources as resources  # type: ignore


_WORD_RE = re.compile(r"[A-Za-z0-9\u0900-\u097F\u0980-\u09FF\u0A00-\u0A7F\u0A80-\u0AFF\u0B00-\u0B7F\u0C00-\u0C7F\u0C80-\u0CFF\u0D00-\u0D7F]+")
_NON_WORD_RE = re.compile(r"[^A-Za-z0-9\u0900-\u097F\u0980-\u09FF\u0A00-\u0A7F\u0A80-\u0AFF\u0B00-\u0B7F\u0C00-\u0C7F\u0C80-\u0CFF]+")
_OFFICE_SUFFIX_RE = re.compile(
    r"\b(?:B\s*\.?\s*O|S\s*\.?\s*O|H\s*\.?\s*O|G\s*\.?\s*P\s*\.?\s*O|M\s*\.?\s*D\s*\.?\s*G|BO|SO|HO|GPO|MDG)\b\.?$",
    re.IGNORECASE,
)
_PIN_RE = re.compile(r"\b\d{6}\b")
_SPACE_RE = re.compile(r"\s+")

_COMMON_SEGMENT_WORDS: Dict[str, int] = {
    # Address/document words
    "i": 9000,
    "am": 8000,
    "live": 8000,
    "in": 12000,
    "at": 9000,
    "from": 9000,
    "to": 9000,
    "and": 12000,
    "or": 9000,
    "near": 9000,
    "via": 7000,
    "post": 7000,
    "po": 7000,
    "p": 2000,
    "o": 2000,
    "house": 9000,
    "nivas": 6500,
    "bhavan": 6500,
    "villa": 5500,
    "road": 10000,
    "rd": 5000,
    "street": 8000,
    "st": 3000,
    "lane": 8000,
    "marg": 6000,
    "colony": 6500,
    "nagar": 7000,
    "puram": 6000,
    "pura": 5000,
    "gram": 4500,
    "village": 9000,
    "taluk": 7000,
    "taluka": 7000,
    "tk": 5000,
    "dist": 8000,
    "district": 9000,
    "dt": 5000,
    "state": 7000,
    "city": 7000,
    "pin": 8000,
    "pincode": 8000,
    "branch": 7000,
    "office": 6500,
    "regional": 5500,
    "north": 4000,
    "south": 4000,
    "east": 4000,
    "west": 4000,
    "central": 3500,
    "main": 6500,
    "cross": 4500,
    "bazaar": 4500,
    "bazar": 4500,
    "old": 3000,
    "new": 3000,
    "upper": 2500,
    "lower": 2500,
}


@dataclass(frozen=True)
class PlaceResult:
    """One fuzzy lookup result."""

    name: str
    normalized: str
    kind: str = "place"
    state: str = ""
    district: str = ""
    pincode: str = ""
    score: float = 0.0
    edit_distance: int = 0
    source: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TaggedPlace:
    text: str
    start: int
    end: int
    match: PlaceResult

    @property
    def canonical(self) -> str:
        return self.match.name

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["canonical"] = self.canonical
        return d


@dataclass(frozen=True)
class SegmentResult:
    original: str
    segmented: str
    tokens: List[str]
    known_tokens: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def normalize_text(text: Any) -> str:
    """Normalize text for indexing and matching."""
    if text is None:
        return ""
    s = str(text).strip().lower()
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.replace("&", " and ")
    s = _NON_WORD_RE.sub(" ", s)
    return _SPACE_RE.sub(" ", s).strip()


def normalize_place_name(text: Any) -> str:
    """Normalize Indian post-office/place names for lookup.

    Examples:
        "Bangalore H.O" -> "bangalore"
        "Kothimir B.O" -> "kothimir"
    """
    if text is None:
        return ""
    s = str(text).strip()
    s = _PIN_RE.sub(" ", s)
    s = _OFFICE_SUFFIX_RE.sub("", s).strip(" .,-:/|\t\n")
    return normalize_text(s)


def _compact(text: str) -> str:
    return normalize_text(text).replace(" ", "")


def _levenshtein(a: str, b: str, max_distance: Optional[int] = None) -> int:
    """Levenshtein distance with optional early cutoff."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    if len(a) > len(b):
        a, b = b, a
    if max_distance is not None and len(b) - len(a) > max_distance:
        return max_distance + 1

    prev = list(range(len(a) + 1))
    for j, cb in enumerate(b, 1):
        curr = [j]
        row_min = curr[0]
        for i, ca in enumerate(a, 1):
            val = min(
                prev[i] + 1,          # deletion
                curr[i - 1] + 1,      # insertion
                prev[i - 1] + (ca != cb),
            )
            curr.append(val)
            if val < row_min:
                row_min = val
        if max_distance is not None and row_min > max_distance:
            return max_distance + 1
        prev = curr
    return prev[-1]


def _delete_variants(word: str, max_distance: int) -> set[str]:
    """Generate SymSpell delete variants."""
    variants = {word}
    frontier = {word}
    for _ in range(max_distance):
        nxt = set()
        for item in frontier:
            if len(item) <= 1:
                continue
            for i in range(len(item)):
                deleted = item[:i] + item[i + 1 :]
                if deleted not in variants:
                    variants.add(deleted)
                    nxt.add(deleted)
        frontier = nxt
        if not frontier:
            break
    return variants


def _score(query: str, candidate: str, distance: int) -> float:
    max_len = max(len(query), len(candidate), 1)
    base = 100.0 * (1.0 - (distance / max_len))
    if candidate.startswith(query):
        base += 8.0
    if query in candidate:
        base += 4.0
    return round(max(0.0, min(100.0, base)), 2)


def _record_from_row(row: Dict[str, Any]) -> Optional[Dict[str, str]]:
    name = (
        row.get("place_name")
        or row.get("officename")
        or row.get("office_name")
        or row.get("name")
        or row.get("Place Name")
        or row.get("OfficeName")
        or ""
    )
    norm = normalize_place_name(name)
    if not norm:
        return None

    office_type = str(row.get("office_type") or row.get("officetype") or row.get("OfficeType") or "").strip()
    kind = "post_office"
    if office_type.upper() in {"BO", "B.O"}:
        kind = "village_or_branch_office"
    elif office_type.upper() in {"SO", "S.O"}:
        kind = "sub_office"
    elif office_type.upper() in {"HO", "H.O", "GPO"}:
        kind = "head_office"

    return {
        "name": str(name).strip(),
        "normalized": norm,
        "kind": kind,
        "state": str(row.get("state") or row.get("StateName") or row.get("circle") or "").strip(),
        "district": str(row.get("district") or row.get("District") or row.get("districtname") or "").strip(),
        "pincode": str(row.get("pincode") or row.get("Pincode") or row.get("pin") or "").strip(),
        "source": "india_places_full.csv",
    }


class IndicPlaces:
    """Indian place-name lookup + word segmentation engine.

    Typical usage:
        ip = IndicPlaces()
        ip.lookup("Bangalor")
        ip.is_place("Perambra")
        ip.segment("iliveinmumbaiorkerala").segmented
        ip.extract_places("PONMINISSERY HOUSE PERAMBRA THRISSUR")
    """

    def __init__(
        self,
        max_edit_distance: int = 2,
        prefix_length: int = 10,
        build_delete_index: bool = True,
    ) -> None:
        self.max_edit_distance = int(max_edit_distance)
        self.prefix_length = int(prefix_length)
        self.records: List[Dict[str, str]] = []
        self._exact: Dict[str, List[int]] = {}
        self._delete_index: Dict[str, List[int]] = {}
        self._word_freq: Dict[str, int] = dict(_COMMON_SEGMENT_WORDS)
        self._max_word_len = max(map(len, self._word_freq))

        self._load_data()
        self._build_exact_index()
        if build_delete_index:
            self._build_delete_index()
        self._build_word_dictionary()

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------
    def _load_data(self) -> None:
        loaded = self._load_compiled_package_index()
        if loaded:
            return
        loaded = self._load_repo_csv_fallback()
        if loaded:
            return
        loaded = self._load_unique_names_fallback()
        if loaded:
            return
        raise FileNotFoundError(
            "No IndicPlaces data found. Run: python scripts/build_index.py "
            "and commit indic_places/data/places_index.json.gz"
        )

    def _load_compiled_package_index(self) -> bool:
        try:
            data_root = resources.files("indic_places").joinpath("data")
            index_path = data_root.joinpath("places_index.json.gz")
            if not index_path.is_file():
                return False
            with gzip.open(str(index_path), "rt", encoding="utf-8") as f:
                payload = json.load(f)
            self.records = payload.get("records", [])
            self._word_freq.update({str(k): int(v) for k, v in payload.get("word_freq", {}).items()})
            return bool(self.records)
        except Exception:
            return False

    def _load_repo_csv_fallback(self) -> bool:
        here = Path(__file__).resolve()
        candidates = [
            here.parents[1] / "data" / "india_places_full.csv",
            here.parent / "data" / "india_places_full.csv",
        ]
        for path in candidates:
            if not path.exists():
                continue
            with path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                self.records = [r for row in reader if (r := _record_from_row(row))]
            return bool(self.records)
        return False

    def _load_unique_names_fallback(self) -> bool:
        here = Path(__file__).resolve()
        candidates = [
            here.parents[1] / "data" / "unique_place_names.txt",
            here.parent / "data" / "unique_place_names.txt",
        ]
        for path in candidates:
            if not path.exists():
                continue
            records = []
            with path.open("r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    name = line.strip()
                    norm = normalize_place_name(name)
                    if norm:
                        records.append(
                            {
                                "name": name,
                                "normalized": norm,
                                "kind": "place",
                                "state": "",
                                "district": "",
                                "pincode": "",
                                "source": "unique_place_names.txt",
                            }
                        )
            self.records = records
            return bool(self.records)
        return False

    # ------------------------------------------------------------------
    # Indexes
    # ------------------------------------------------------------------
    def _build_exact_index(self) -> None:
        exact: Dict[str, List[int]] = {}
        for i, rec in enumerate(self.records):
            norm = rec.get("normalized") or normalize_place_name(rec.get("name", ""))
            if not norm:
                continue
            rec["normalized"] = norm
            exact.setdefault(norm, []).append(i)
            compact = norm.replace(" ", "")
            if compact != norm:
                exact.setdefault(compact, []).append(i)
        self._exact = exact

    def _build_delete_index(self) -> None:
        idx: Dict[str, List[int]] = {}
        for i, rec in enumerate(self.records):
            norm = rec["normalized"].replace(" ", "")[: self.prefix_length]
            if not norm:
                continue
            for d in _delete_variants(norm, self.max_edit_distance):
                idx.setdefault(d, []).append(i)
        self._delete_index = idx

    def _build_word_dictionary(self) -> None:
        for rec in self.records:
            norm = rec.get("normalized", "")
            if not norm:
                continue
            compact = norm.replace(" ", "")
            if compact:
                self._word_freq[compact] = self._word_freq.get(compact, 0) + 20
                self._max_word_len = max(self._max_word_len, len(compact))
            for token in norm.split():
                if len(token) >= 2:
                    self._word_freq[token] = self._word_freq.get(token, 0) + 50
                    self._max_word_len = max(self._max_word_len, len(token))
            for field, weight in (("district", 80), ("state", 100)):
                val = normalize_place_name(rec.get(field, ""))
                for token in val.split():
                    if len(token) >= 2:
                        self._word_freq[token] = self._word_freq.get(token, 0) + weight
                        self._max_word_len = max(self._max_word_len, len(token))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def lookup(
        self,
        query: str,
        *,
        top_n: int = 5,
        min_score: float = 70.0,
        kind: Optional[str] = None,
        state: Optional[str] = None,
        district: Optional[str] = None,
    ) -> List[PlaceResult]:
        """Fuzzy lookup for a place name.

        Works like a lightweight SymSpell lookup:
        - exact normalized lookup first
        - delete-neighbourhood candidate generation
        - Levenshtein scoring on compact normalized form
        """
        norm_q = normalize_place_name(query)
        if not norm_q:
            return []
        compact_q = norm_q.replace(" ", "")
        candidates: set[int] = set()

        # Exact / compact exact hits first.
        candidates.update(self._exact.get(norm_q, []))
        candidates.update(self._exact.get(compact_q, []))

        # SymSpell delete-neighbourhood hits.
        prefix = compact_q[: self.prefix_length]
        if self._delete_index:
            for d in _delete_variants(prefix, self.max_edit_distance):
                candidates.update(self._delete_index.get(d, []))

        # Small fallback: prefix contains query, helpful for suffix variations.
        if not candidates and len(compact_q) >= 4:
            for i, rec in enumerate(self.records):
                c = rec["normalized"].replace(" ", "")
                if c.startswith(compact_q) or compact_q in c:
                    candidates.add(i)
                    if len(candidates) >= 2000:
                        break

        state_norm = normalize_place_name(state or "")
        district_norm = normalize_place_name(district or "")

        results: List[PlaceResult] = []
        seen: set[Tuple[str, str, str, str]] = set()
        for i in candidates:
            rec = self.records[i]
            if kind and rec.get("kind") != kind:
                continue
            if state_norm and normalize_place_name(rec.get("state", "")) != state_norm:
                continue
            if district_norm and normalize_place_name(rec.get("district", "")) != district_norm:
                continue

            cand = rec["normalized"].replace(" ", "")
            if not cand:
                continue

            # If one side contains the other, compare against nearest substring length.
            if cand.startswith(compact_q):
                dist = 0 if cand == compact_q else max(0, len(cand) - len(compact_q)) // 4
            elif compact_q in cand:
                dist = 1
            else:
                allowed = max(self.max_edit_distance, len(compact_q) // 4)
                dist = _levenshtein(compact_q, cand, max_distance=allowed + 1)
                if dist > allowed:
                    continue

            sc = _score(compact_q, cand, dist)
            if sc < min_score:
                continue

            key = (rec.get("normalized", ""), rec.get("state", ""), rec.get("district", ""), rec.get("pincode", ""))
            if key in seen:
                continue
            seen.add(key)
            results.append(
                PlaceResult(
                    name=rec.get("name", ""),
                    normalized=rec.get("normalized", ""),
                    kind=rec.get("kind", "place"),
                    state=rec.get("state", ""),
                    district=rec.get("district", ""),
                    pincode=rec.get("pincode", ""),
                    score=sc,
                    edit_distance=dist,
                    source=rec.get("source", ""),
                )
            )

        results.sort(key=lambda r: (-r.score, r.edit_distance, len(r.normalized), r.name))
        return results[:top_n]

    def is_place(self, text: str, *, min_score: float = 82.0) -> bool:
        return bool(self.lookup(text, top_n=1, min_score=min_score))

    def best(self, text: str, *, min_score: float = 70.0) -> Optional[PlaceResult]:
        hits = self.lookup(text, top_n=1, min_score=min_score)
        return hits[0] if hits else None

    def extract_places(
        self,
        text: str,
        *,
        max_window: int = 5,
        min_score: float = 85.0,
    ) -> List[TaggedPlace]:
        """Extract place mentions from normal or OCR text.

        It checks 5-word, 4-word, ... 1-word spans and keeps non-overlapping
        best matches.
        """
        spans = [(m.group(), m.start(), m.end()) for m in _WORD_RE.finditer(str(text or ""))]
        if not spans:
            return []

        found: List[TaggedPlace] = []
        used: set[int] = set()
        max_window = max(1, int(max_window))

        for win in range(min(max_window, len(spans)), 0, -1):
            for i in range(0, len(spans) - win + 1):
                start = spans[i][1]
                end = spans[i + win - 1][2]
                if any(pos in used for pos in range(start, end)):
                    continue
                phrase = str(text)[start:end]
                if len(normalize_text(phrase).replace(" ", "")) < 3:
                    continue
                # Multi-word spans need stricter score.
                threshold = min_score if win == 1 else max(min_score, 90.0)
                hit = self.best(phrase, min_score=threshold)
                if hit:
                    found.append(TaggedPlace(text=phrase, start=start, end=end, match=hit))
                    used.update(range(start, end))

        found.sort(key=lambda x: x.start)
        return found

    def segment(self, text: str, *, keep_unknown_chunks: bool = True) -> SegmentResult:
        """Split merged OCR/address text into words using a DP dictionary.

        Example:
            iliveinmumbaiorkerala -> i live in mumbai or kerala
        """
        original = str(text or "")
        compact = _compact(original)
        if not compact:
            return SegmentResult(original=original, segmented="", tokens=[], known_tokens=[])

        n = len(compact)
        max_len = min(max(self._max_word_len, 20), 64)
        total = float(sum(self._word_freq.values()) or 1)
        unknown_cost = 9.5

        # dp[i] = (cost, token-list, known-token-list)
        dp: List[Tuple[float, List[str], List[str]]] = [(float("inf"), [], []) for _ in range(n + 1)]
        dp[n] = (0.0, [], [])

        for i in range(n - 1, -1, -1):
            # Unknown char fallback.
            best_cost = unknown_cost + dp[i + 1][0]
            best_tokens = [compact[i]] + dp[i + 1][1]
            best_known = dp[i + 1][2]

            for j in range(i + 1, min(n, i + max_len) + 1):
                w = compact[i:j]
                freq = self._word_freq.get(w)
                if not freq:
                    continue
                # Prefer common and longer dictionary words.
                cost = -math.log(freq / total) - (len(w) * 0.22) + dp[j][0]
                if cost < best_cost:
                    best_cost = cost
                    best_tokens = [w] + dp[j][1]
                    best_known = [w] + dp[j][2]

            dp[i] = (best_cost, best_tokens, best_known)

        tokens = dp[0][1]
        if keep_unknown_chunks:
            tokens = self._merge_unknown_chars(tokens)
        segmented = " ".join(tokens)
        return SegmentResult(original=original, segmented=segmented, tokens=tokens, known_tokens=dp[0][2])

    def normalize_address_spacing(self, text: str) -> str:
        """Convenience wrapper for OCR address spacing."""
        return self.segment(text).segmented.upper()

    def stats(self) -> Dict[str, int]:
        by_kind: Dict[str, int] = {}
        for rec in self.records:
            k = rec.get("kind", "place")
            by_kind[k] = by_kind.get(k, 0) + 1
        by_kind["total"] = len(self.records)
        by_kind["delete_keys"] = len(self._delete_index)
        by_kind["word_dictionary"] = len(self._word_freq)
        return by_kind

    def _merge_unknown_chars(self, tokens: Sequence[str]) -> List[str]:
        out: List[str] = []
        buf: List[str] = []

        def flush() -> None:
            if buf:
                out.append("".join(buf))
                buf.clear()

        for token in tokens:
            if token in self._word_freq or len(token) > 1:
                flush()
                out.append(token)
            else:
                buf.append(token)
        flush()
        return out

    def __len__(self) -> int:
        return len(self.records)

    def __contains__(self, item: str) -> bool:
        return self.is_place(item)
