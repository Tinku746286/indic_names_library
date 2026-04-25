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
from difflib import SequenceMatcher

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

_COMMON_SEGMENT_WORDS: Dict[str, int] = {}


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
        self._max_word_len = max(map(len, self._word_freq), default=1)

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

    def _lookup_admin_name_set(self) -> set[str]:
        cached = getattr(self, "_lookup_admin_names_cache", None)
        if cached is not None:
            return cached

        names: set[str] = set()

        for rec in self.records:
            for field in ("state", "district"):
                val = normalize_place_name(rec.get(field, ""))
                if val:
                    names.add(val.replace(" ", ""))

            kind = str(rec.get("kind", "")).lower()
            norm = normalize_place_name(rec.get("name", "")).replace(" ", "")

            if kind in {"place", "city", "town", "village", "district", "state"} and norm:
                names.add(norm)

        setattr(self, "_lookup_admin_names_cache", names)
        return names

    def _lookup_sort_key(self, result: PlaceResult, compact_q: str) -> tuple:
        name = str(result.name or "")
        norm = normalize_place_name(result.normalized or result.name).replace(" ", "")
        kind = str(result.kind or "").lower()

        office_suffix_penalty = 1 if _OFFICE_SUFFIX_RE.search(name) else 0
        post_office_kind_penalty = 1 if kind in {
            "post_office",
            "sub_office",
            "head_office",
            "village_or_branch_office",
        } else 0

        admin_names = self._lookup_admin_name_set()
        admin_bonus = 1 if norm in admin_names else 0

        exact_prefix_bonus = 1 if norm.startswith(compact_q) and len(norm) > len(compact_q) else 0
        exact_same_penalty = 1 if norm == compact_q else 0

        return (
            -result.score,
            -admin_bonus,
            office_suffix_penalty,
            post_office_kind_penalty,
            exact_same_penalty,
            -exact_prefix_bonus,
            result.edit_distance,
            len(norm),
            name.lower(),
        )



    def _strip_office_suffix_for_correction(self, value: str) -> str:
        s = str(value or "").strip(" ,:-|")
        if not s:
            return ""

        s = re.sub(
            r"(?i)\\b(?:G\\.?P\\.?O\\.?|H\\.?O\\.?|S\\.?O\\.?|B\\.?O\\.?|P\\.?O\\.?|GPO|HO|SO|BO|PO)$",
            "",
            s,
        )
        return re.sub(r"\\s+", " ", s).strip(" ,:-|")

    def _correction_state_set(self) -> set[str]:
        cached = getattr(self, "_correction_state_set_cache", None)
        if cached is not None:
            return cached

        states: set[str] = set()
        for rec in self.records:
            state = normalize_place_name(rec.get("state", "")).replace(" ", "")
            if state:
                states.add(state)

        setattr(self, "_correction_state_set_cache", states)
        return states

    def _correction_candidate_rows(self, target: str, state_hint: str = "") -> list[tuple]:
        q = normalize_place_name(target).replace(" ", "")
        state_q = normalize_place_name(state_hint).replace(" ", "")

        if not q:
            return []

        rows: list[tuple] = []
        seen: set[tuple] = set()

        try:
            lookup_results = self.lookup(target, top_n=80)
        except Exception:
            lookup_results = []

        for r in lookup_results:
            for source_name in (
                getattr(r, "district", ""),
                self._strip_office_suffix_for_correction(getattr(r, "name", "")),
                getattr(r, "state", ""),
            ):
                name = str(source_name or "").strip()
                norm = normalize_place_name(name).replace(" ", "")
                if len(norm) < 4:
                    continue

                state = str(getattr(r, "state", "") or "").strip()
                district = str(getattr(r, "district", "") or "").strip()
                key = (norm, normalize_place_name(state), normalize_place_name(district))

                if key in seen:
                    continue

                seen.add(key)
                rows.append((name, state, district, "lookup"))

        for rec in self.records:
            state = str(rec.get("state", "") or "").strip()
            district = str(rec.get("district", "") or "").strip()

            if state_q and normalize_place_name(state).replace(" ", "") != state_q:
                continue

            raw_names = [
                rec.get("name", ""),
                district,
                state,
                self._strip_office_suffix_for_correction(rec.get("name", "")),
            ]

            for raw_name in raw_names:
                name = str(raw_name or "").strip()
                norm = normalize_place_name(name).replace(" ", "")

                if len(norm) < 4:
                    continue

                key = (norm, normalize_place_name(state), normalize_place_name(district))
                if key in seen:
                    continue

                sim = SequenceMatcher(None, q, norm).ratio()
                useful = (
                    norm.startswith(q)
                    or q.startswith(norm)
                    or q in norm
                    or sim >= 0.72
                    or (len(q) >= 4 and len(norm) > 1 and norm[1:].startswith(q[: min(len(q), len(norm) - 1)]))
                )

                if useful:
                    seen.add(key)
                    rows.append((name, state, district, "records"))

        return rows

    def _clean_display_place_name(self, value: str) -> str:
        s = str(value or "").strip(" ,:-|")
        if not s:
            return ""

        s = re.sub(
            r"(?i)\s+\b(?:G\.?P\.?O\.?|H\.?O\.?|S\.?O\.?|B\.?O\.?|P\.?O\.?|GPO|HO|SO|BO|PO)$",
            "",
            s,
        )
        return re.sub(r"\s+", " ", s).strip(" ,:-|")

    def _known_state_display_map(self) -> dict:
        cached = getattr(self, "_known_state_display_map_cache", None)
        if cached is not None:
            return cached

        out = {}
        for rec in self.records:
            state = str(rec.get("state", "") or "").strip()
            if state:
                out[normalize_place_name(state).replace(" ", "")] = state.upper()

        out.setdefault("MADHYAPRADESH", "MADHYA PRADESH")
        out.setdefault("UTTARPRADESH", "UTTAR PRADESH")
        out.setdefault("ANDHRAPRADESH", "ANDHRA PRADESH")
        out.setdefault("ARUNACHALPRADESH", "ARUNACHAL PRADESH")
        out.setdefault("HIMACHALPRADESH", "HIMACHAL PRADESH")
        out.setdefault("KERALA", "KERALA")
        out.setdefault("KERA", "KERALA")
        out.setdefault("JHARKHAND", "JHARKHAND")
        out.setdefault("JHARK", "JHARKHAND")
        out.setdefault("JHURKHUND", "JHARKHAND")
        out.setdefault("JHURKHAND", "JHARKHAND")
        out.setdefault("JHARKHUND", "JHARKHAND")

        setattr(self, "_known_state_display_map_cache", out)
        return out

    def _normalize_joined_state_tokens(self, clean_address: str) -> str:
        out = str(clean_address or "")
        states = self._known_state_display_map()

        for compact, display in sorted(states.items(), key=lambda kv: len(kv[0]), reverse=True):
            if len(compact) < 4:
                continue
            out = re.sub(rf"(?i)\b{re.escape(compact)}\b", display.upper(), out)

        return re.sub(r"\s+", " ", out).strip()

    def _candidate_from_token(self, token: str, state_hint: str = "") -> dict | None:
        token = str(token or "").strip(" ,:-|.")
        token_key = normalize_place_name(token).replace(" ", "")
        if not token_key or len(token_key) < 4:
            return None

        states = self._known_state_display_map()
        if token_key in states:
            return {
                "name": states[token_key],
                "state": states[token_key],
                "district": "",
                "pincode": "",
                "score": 100.0,
            }

        state_hint_key = normalize_place_name(state_hint).replace(" ", "")

        try:
            results = self.lookup(token, top_n=80)
        except Exception:
            results = []

        best = None
        best_rank = -10**9

        for r in results:
            raw_name = str(getattr(r, "name", "") or "")
            clean_name = self._clean_display_place_name(raw_name)
            name_key = normalize_place_name(clean_name).replace(" ", "")
            district = str(getattr(r, "district", "") or "")
            state = str(getattr(r, "state", "") or "")
            district_key = normalize_place_name(district).replace(" ", "")
            state_key = normalize_place_name(state).replace(" ", "")
            score = float(getattr(r, "score", 0) or 0)

            rank = score

            if name_key == token_key:
                rank += 100
            if district_key == token_key:
                rank += 140
            if state_key == token_key:
                rank += 160

            if name_key.startswith(token_key) and len(name_key) > len(token_key):
                rank += 50
            if district_key.startswith(token_key) and len(district_key) > len(token_key):
                rank += 80
            if state_key.startswith(token_key) and len(state_key) > len(token_key):
                rank += 90

            if state_hint_key and state_key == state_hint_key:
                rank += 35

            if re.search(r"(?i)\b(?:G\.?P\.?O\.?|H\.?O\.?|S\.?O\.?|B\.?O\.?|P\.?O\.?|GPO|HO|SO|BO|PO)$", raw_name):
                rank -= 45

            if token_key not in {name_key, district_key, state_key}:
                if not (
                    name_key.startswith(token_key)
                    or district_key.startswith(token_key)
                    or state_key.startswith(token_key)
                    or token_key.startswith(name_key)
                ):
                    rank -= 70

            if rank > best_rank:
                best_rank = rank

                display_name = clean_name
                if district_key == token_key or (district_key.startswith(token_key) and len(district_key) > len(token_key)):
                    display_name = district.upper()
                elif state_key == token_key or (state_key.startswith(token_key) and len(state_key) > len(token_key)):
                    display_name = state.upper()

                best = {
                    "name": display_name,
                    "state": state,
                    "district": district,
                    "pincode": str(getattr(r, "pincode", "") or ""),
                    "score": getattr(r, "score", ""),
                }

        return best

    def _repair_ocr_state_variants(self, value: str) -> str:
        """Repair common OCR noise around Indian state names before address analysis."""
        s = str(value or "")
        if not s:
            return ""

        s = re.sub(r"\\s+", " ", s).strip()

        one_word_states = [
            "MAHARASHTRA", "KARNATAKA", "TELANGANA", "JHARKHAND",
            "RAJASTHAN", "GUJARAT", "HARYANA", "ODISHA", "PUNJAB",
            "KERALA", "BIHAR", "ASSAM", "GOA", "SIKKIM",
        ]

        for state in sorted(one_word_states, key=len, reverse=True):
            s = re.sub(
                rf"(?i)({state})(?=[A-Z])",
                lambda m: m.group(1).upper() + " ",
                s,
            )

        replacements = [
            # Jharkhand OCR/vowel variants.
            (r"(?i)JHURKHUND", "JHARKHAND"),
            (r"(?i)JHURKHAND", "JHARKHAND"),
            (r"(?i)JHARKHUND", "JHARKHAND"),
            (r"(?i)JHARKHAND", "JHARKHAND"),
            (r"(?i)JHARKAND", "JHARKHAND"),
            (r"(?i)JHARHAND", "JHARKHAND"),
            (r"(?i)\\bT[A-Z]{0,4}MIL\\s*NADU\\b", "TAMIL NADU"),
            (r"(?i)T[A-Z]{0,4}MILNADU", "TAMIL NADU"),
            (r"(?i)TAMILNADU", "TAMIL NADU"),
            (r"(?i)TMLNADU", "TAMIL NADU"),
            (r"(?i)MADHYAPRADESH", "MADHYA PRADESH"),
            (r"(?i)UTTARPRADESH", "UTTAR PRADESH"),
            (r"(?i)ANDHRAPRADESH", "ANDHRA PRADESH"),
            (r"(?i)ARUNACHALPRADESH", "ARUNACHAL PRADESH"),
            (r"(?i)HIMACHALPRADESH", "HIMACHAL PRADESH"),
        ]

        for pattern, repl in replacements:
            s = re.sub(pattern, repl, s)

        for state in sorted(one_word_states, key=len, reverse=True):
            s = re.sub(
                rf"(?i)({state})(?=[A-Z])",
                lambda m: m.group(1).upper() + " ",
                s,
            )

        return re.sub(r"\\s+", " ", s).strip()



    def _repair_strip_office_suffix(self, value: str) -> str:
        s = str(value or "").strip(" ,:-|")
        if not s:
            return ""
        s = re.sub(
            r"(?i)\s+\b(?:G\.?P\.?O\.?|H\.?O\.?|S\.?O\.?|B\.?O\.?|P\.?O\.?|GPO|HO|SO|BO|PO)$",
            "",
            s,
        )
        return re.sub(r"\s+", " ", s).strip(" ,:-|")

    def _repair_norm(self, value: str) -> str:
        return normalize_place_name(value).replace(" ", "")

    def _edit_distance_limited(self, a: str, b: str, limit: int = 2) -> int:
        a = str(a or "")
        b = str(b or "")

        if a == b:
            return 0

        if abs(len(a) - len(b)) > limit:
            return limit + 1

        if len(a) > len(b):
            a, b = b, a

        prev = list(range(len(b) + 1))

        for i, ca in enumerate(a, 1):
            cur = [i]
            row_min = i

            for j, cb in enumerate(b, 1):
                cost = 0 if ca == cb else 1
                val = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
                cur.append(val)
                row_min = min(row_min, val)

            if row_min > limit:
                return limit + 1

            prev = cur

        return prev[-1]

    def _repair_candidate_rows(self) -> list[dict]:
        cached = getattr(self, "_repair_candidate_rows_cache", None)
        if cached is not None:
            return cached

        rows = []
        seen = set()

        for rec in getattr(self, "records", []):
            state = str(rec.get("state", "") or "").strip()
            district = str(rec.get("district", "") or "").strip()
            pincode = str(rec.get("pincode", "") or "").strip()

            candidates = [
                ("name", self._repair_strip_office_suffix(rec.get("name", "")), 20),
                ("district", district, 70),
                ("state", state, 90),
            ]

            for kind, name, base_weight in candidates:
                name = str(name or "").strip()
                norm = self._repair_norm(name)

                if len(norm) < 4:
                    continue

                if norm in {"NONE", "NULL", "NIL", "NAN", "NA"}:
                    continue

                key = (norm, self._repair_norm(state), self._repair_norm(district), kind)

                if key in seen:
                    continue

                seen.add(key)
                rows.append({
                    "name": name,
                    "norm": norm,
                    "kind": kind,
                    "state": state,
                    "district": district,
                    "pincode": pincode,
                    "base_weight": base_weight,
                })

        aliases = [
            ("Kerala", "KERALA", "", "", "state", 120),
            ("Jharkhand", "JHARKHAND", "", "", "state", 120),
            ("Maharashtra", "MAHARASHTRA", "", "", "state", 120),
            ("Tamil Nadu", "TAMIL NADU", "", "", "state", 120),
            ("Madhya Pradesh", "MADHYA PRADESH", "", "", "state", 120),
            ("Uttar Pradesh", "UTTAR PRADESH", "", "", "state", 120),
            ("Andhra Pradesh", "ANDHRA PRADESH", "", "", "state", 120),
        ]

        for name, state, district, pincode, kind, base_weight in aliases:
            norm = self._repair_norm(name)
            key = (norm, self._repair_norm(state), self._repair_norm(district), kind)
            if key not in seen:
                seen.add(key)
                rows.append({
                    "name": name,
                    "norm": norm,
                    "kind": kind,
                    "state": state,
                    "district": district,
                    "pincode": pincode,
                    "base_weight": base_weight,
                })


        # Include user/package custom places in correction candidates.
        # This allows missing villages/localities to participate in correct_place_name().
        try:
            from importlib import resources as _indic_places_resources
            _custom_file = _indic_places_resources.files("indic_places").joinpath("data/custom_places.txt")
            _custom_text = _custom_file.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            _custom_text = ""

        for _line in _custom_text.splitlines():
            _name = _line.split("#", 1)[0].strip()
            if not _name:
                continue

            _norm = self._repair_norm(_name)
            if len(_norm) < 4:
                continue

            _key = (_norm, "", "", "custom")
            if _key in seen:
                continue

            seen.add(_key)
            rows.append({
                "name": _name,
                "norm": _norm,
                "kind": "custom",
                "state": "",
                "district": "",
                "pincode": "",
                "base_weight": 85,
            })


        setattr(self, "_repair_candidate_rows_cache", rows)
        return rows


    def _repair_consonant_key(self, value: str) -> str:
        s = self._repair_norm(value)
        return re.sub(r"[AEIOU]", "", s)

    def _repair_candidate_index(self) -> dict:
        cached = getattr(self, "_repair_candidate_index_cache", None)
        if cached is not None:
            return cached

        rows = self._repair_candidate_rows()

        index = {
            "exact": {},
            "p1": {},
            "p2": {},
            "p3": {},
            "skip1p3": {},
            "consonant": {},
            "consonant_p6": {},
        }

        def add(bucket: dict, key: str, row: dict) -> None:
            if not key:
                return
            bucket.setdefault(key, []).append(row)

        for row in rows:
            norm = row.get("norm", "")
            if not norm:
                continue

            add(index["exact"], norm, row)
            add(index["p1"], norm[:1], row)
            add(index["p2"], norm[:2], row)
            add(index["p3"], norm[:3], row)

            if len(norm) > 3:
                add(index["skip1p3"], norm[1:4], row)

            ckey = self._repair_consonant_key(norm)
            add(index["consonant"], ckey, row)
            add(index["consonant_p6"], ckey[:6], row)

        setattr(self, "_repair_candidate_index_cache", index)
        return index


    def _fast_sqlite_index_path(self):
        from pathlib import Path
        return Path(__file__).resolve().parent / "data" / "fast_places.sqlite"

    def has_fast_search_index(self) -> bool:
        return self._fast_sqlite_index_path().exists()

    def _fast_sqlite_connection(self):
        import sqlite3

        cached = getattr(self, "_fast_sqlite_conn", None)
        if cached is not None:
            return cached

        path = self._fast_sqlite_index_path()
        if not path.exists():
            return None

        conn = sqlite3.connect(str(path), check_same_thread=False)
        setattr(self, "_fast_sqlite_conn", conn)
        return conn

    def _fast_sqlite_candidates(self, query_norm: str, max_candidates: int = 8000) -> list[dict]:
        """
        Accuracy-safe SQLite candidate retrieval.

        It mirrors the old in-memory candidate buckets:
        exact, p3, skip1p3, p2, consonant, consonant_p6, p1 fallback.

        Scoring still uses the existing Python scorer, so this should not
        change ranking logic; it only avoids building/scanning the huge
        in-memory index.
        """
        query_norm = str(query_norm or "")

        if not query_norm:
            return []

        max_candidates = min(int(max_candidates or 8000), 8000)

        conn = self._fast_sqlite_connection()
        if conn is None:
            return []

        cons = re.sub(r"[AEIOU]", "", query_norm)
        selected = []
        seen = set()

        def add_rows(sql: str, params: tuple) -> None:
            if len(selected) >= max_candidates:
                return

            try:
                rows = conn.execute(sql, params).fetchall()
            except Exception:
                return

            for norm, name in rows:
                if norm in seen:
                    continue
                seen.add(norm)
                selected.append({"norm": norm, "name": name, "state": "", "district": "", "kind": "sqlite"})
                if len(selected) >= max_candidates:
                    return

        # Same bucket order as old _repair_candidate_subset.
        add_rows("SELECT norm,name FROM places WHERE norm=? LIMIT 100", (query_norm,))

        if len(query_norm) >= 3:
            add_rows(
                "SELECT norm,name FROM places WHERE p3=? ORDER BY length LIMIT ?",
                (query_norm[:3], max_candidates - len(selected)),
            )
            add_rows(
                "SELECT norm,name FROM places WHERE skip1p3=? ORDER BY length LIMIT ?",
                (query_norm[:3], max_candidates - len(selected)),
            )

        if len(query_norm) >= 2:
            add_rows(
                "SELECT norm,name FROM places WHERE p2=? ORDER BY length LIMIT ?",
                (query_norm[:2], max_candidates - len(selected)),
            )

        if cons:
            add_rows(
                "SELECT norm,name FROM places WHERE cons=? ORDER BY length LIMIT ?",
                (cons, max_candidates - len(selected)),
            )

            if len(cons) >= 6:
                add_rows(
                    "SELECT norm,name FROM places WHERE cons6=? ORDER BY length LIMIT ?",
                    (cons[:6], max_candidates - len(selected)),
                )

        if len(selected) < 200 and query_norm[:1]:
            add_rows(
                "SELECT norm,name FROM places WHERE p1=? ORDER BY length LIMIT ?",
                (query_norm[:1], max_candidates - len(selected)),
            )

        return selected[:max_candidates]


    def _repair_candidate_subset(
        self,
        query_norm: str,
        max_edit: int = 2,
        max_candidates: int = 25000,
    ) -> list[dict]:
        query_norm = str(query_norm or "")
        if not query_norm:
            return []

        fast_rows = self._fast_sqlite_candidates(query_norm, max_candidates=max_candidates)
        if fast_rows:
            return fast_rows

        index = self._repair_candidate_index()
        selected = []
        seen_ids = set()

        def add_rows(rows) -> None:
            for row in rows or []:
                rid = id(row)
                if rid in seen_ids:
                    continue
                seen_ids.add(rid)
                selected.append(row)

        add_rows(index["exact"].get(query_norm, []))

        if len(query_norm) >= 3:
            add_rows(index["p3"].get(query_norm[:3], []))
            add_rows(index["skip1p3"].get(query_norm[:3], []))

        if len(query_norm) >= 2:
            add_rows(index["p2"].get(query_norm[:2], []))

        ckey = self._repair_consonant_key(query_norm)
        if ckey:
            add_rows(index["consonant"].get(ckey, []))
            if len(ckey) >= 6:
                add_rows(index["consonant_p6"].get(ckey[:6], []))

        if len(selected) < 200 and query_norm[:1]:
            add_rows(index["p1"].get(query_norm[:1], [])[:max_candidates])

        if len(selected) > max_candidates:
            selected = selected[:max_candidates]

        return selected


    def _repair_candidate_score(
        self,
        query_norm: str,
        row: dict,
        state_hint: str = "",
        district_hint: str = "",
        max_edit: int = 2,
    ) -> float:
        cand_norm = row["norm"]

        if not query_norm or not cand_norm:
            return -1

        sim = SequenceMatcher(None, query_norm, cand_norm).ratio()
        edit = self._edit_distance_limited(query_norm, cand_norm, limit=max_edit)

        is_prefix = cand_norm.startswith(query_norm)
        is_reverse_prefix = query_norm.startswith(cand_norm)
        is_contains = query_norm in cand_norm or cand_norm in query_norm
        is_close_edit = edit <= max_edit
        is_similar = sim >= 0.72

        if not (is_prefix or is_reverse_prefix or is_contains or is_close_edit or is_similar):
            return -1

        score = 0.0
        score += sim * 100
        score += float(row.get("base_weight", 0) or 0)

        if cand_norm == query_norm:
            score += 80

        if is_prefix and len(cand_norm) > len(query_norm):
            missing = len(cand_norm) - len(query_norm)
            score += max(10, 90 - missing * 8)

        if is_close_edit:
            score += 75 - edit * 18

        if is_contains:
            score += 20

        if len(cand_norm) > 1 and cand_norm[1:].startswith(query_norm[: min(len(query_norm), len(cand_norm) - 1)]):
            score += 35

        state_hint_norm = self._repair_norm(state_hint)
        district_hint_norm = self._repair_norm(district_hint)

        if state_hint_norm and self._repair_norm(row.get("state", "")) == state_hint_norm:
            score += 35

        if district_hint_norm and self._repair_norm(row.get("district", "")) == district_hint_norm:
            score += 50

        name = str(row.get("name", "") or "")
        if re.search(r"(?i)\b(?:G\.?P\.?O\.?|H\.?O\.?|S\.?O\.?|B\.?O\.?|P\.?O\.?|GPO|HO|SO|BO|PO)$", name):
            score -= 60

        return score



    def _preferred_admin_rows(self) -> list[dict]:
        cached = getattr(self, "_preferred_admin_rows_cache", None)
        if cached is not None:
            return cached

        rows = []
        seen = set()

        def add(name: str, state: str = "", district: str = "", kind: str = "admin", weight: int = 0) -> None:
            name = str(name or "").strip()
            norm = self._repair_norm(name)
            if len(norm) < 4:
                return

            key = (norm, self._repair_norm(state), self._repair_norm(district), kind)
            if key in seen:
                return

            seen.add(key)
            rows.append({
                "name": name,
                "norm": norm,
                "state": state,
                "district": district,
                "kind": kind,
                "weight": weight,
            })

        aliases = [
            ("Bhopal", "MADHYA PRADESH", "BHOPAL", "district", 360),
            ("Kerala", "KERALA", "", "state", 380),
            ("Jharkhand", "JHARKHAND", "", "state", 380),
            ("Thrissur", "KERALA", "THRISSUR", "district", 360),
            ("Muzaffarnagar", "UTTAR PRADESH", "MUZAFFARNAGAR", "district", 350),
            ("Muzaffarpur", "BIHAR", "MUZAFFARPUR", "district", 340),
            ("Maharashtra", "MAHARASHTRA", "", "state", 380),
            ("Tamil Nadu", "TAMIL NADU", "", "state", 380),
            ("Madhya Pradesh", "MADHYA PRADESH", "", "state", 380),
            ("Uttar Pradesh", "UTTAR PRADESH", "", "state", 380),
            ("Andhra Pradesh", "ANDHRA PRADESH", "", "state", 380),
            ("Karnataka", "KARNATAKA", "", "state", 380),
            ("Telangana", "TELANGANA", "", "state", 380),
            ("Puducherry", "PUDUCHERRY", "", "state", 380),
            ("Alappuzha", "KERALA", "ALAPPUZHA", "district", 350),
            ("Kozhikode", "KERALA", "KOZHIKODE", "district", 350),
            ("Kottayam", "KERALA", "KOTTAYAM", "district", 350),
            ("Ernakulam", "KERALA", "ERNAKULAM", "district", 350),
            ("Thiruvananthapuram", "KERALA", "THIRUVANANTHAPURAM", "district", 350),
            ("Trivandrum", "KERALA", "THIRUVANANTHAPURAM", "district", 350),
        ]

        for name, state, district, kind, weight in aliases:
            add(name, state, district, kind, weight)

        setattr(self, "_preferred_admin_rows_cache", rows)
        return rows



    def _try_admin_correction(
        self,
        query: str,
        state_hint: str = "",
        district_hint: str = "",
        top_n: int = 1,
        max_edit: int = 2,
    ):
        query = str(query or "").strip()
        query_norm = self._repair_norm(query)

        if len(query_norm) < 4:
            return [] if top_n != 1 else ""

        multi_word_admin = {
            "TAMILNADU",
            "MADHYAPRADESH",
            "UTTARPRADESH",
            "ANDHRAPRADESH",
            "ARUNACHALPRADESH",
            "HIMACHALPRADESH",
            "JAMMUANDKASHMIR",
            "DADRAANDNAGARHAVELI",
            "DAMANANDDIU",
        }

        if " " in query and query_norm not in multi_word_admin:
            return [] if top_n != 1 else ""

        state_hint_norm = self._repair_norm(state_hint)
        district_hint_norm = self._repair_norm(district_hint)

        scored = []

        for row in self._preferred_admin_rows():
            cand_norm = row["norm"]
            sim = SequenceMatcher(None, query_norm, cand_norm).ratio()
            edit = self._edit_distance_limited(query_norm, cand_norm, limit=max_edit)

            is_prefix = cand_norm.startswith(query_norm)
            is_reverse_prefix = query_norm.startswith(cand_norm)
            is_contains = query_norm in cand_norm or cand_norm in query_norm
            is_close_edit = edit <= max_edit
            missing_first = len(cand_norm) > 1 and cand_norm[1:].startswith(query_norm[: min(len(query_norm), len(cand_norm) - 1)])

            if not (is_prefix or is_reverse_prefix or is_contains or is_close_edit or missing_first or sim >= 0.76):
                continue

            score = float(row.get("weight", 0) or 0)
            score += sim * 100

            if cand_norm == query_norm:
                score += 160

            if is_prefix:
                missing = len(cand_norm) - len(query_norm)
                score += max(40, 160 - max(missing, 0) * 8)

            if is_close_edit:
                score += 120 - edit * 30

            if missing_first:
                score += 100

            if state_hint_norm and self._repair_norm(row.get("state", "")) == state_hint_norm:
                score += 60

            if district_hint_norm and self._repair_norm(row.get("district", "")) == district_hint_norm:
                score += 80

            if len(query_norm) <= 5 and score < 430:
                continue

            if len(query_norm) > 5 and score < 350:
                continue

            scored.append((score, len(cand_norm), row["name"], row))

        scored.sort(key=lambda x: (-x[0], x[1], x[2].lower()))

        out = []
        seen = set()

        for _score, _length, _name, row in scored:
            name = str(row["name"]).strip()
            key = self._repair_norm(name)
            if key in seen:
                continue
            seen.add(key)
            out.append(name)
            if len(out) >= max(int(top_n or 1), 1):
                break

        if top_n == 1:
            return out[0] if out else ""

        return out


    def warmup_correction_index(self) -> int:
        if self.has_fast_search_index():
            conn = self._fast_sqlite_connection()
            if conn is not None:
                try:
                    return int(conn.execute("SELECT COUNT(*) FROM places").fetchone()[0])
                except Exception:
                    pass
        return len(self._repair_candidate_rows())


    def _fast_sqlite_prefix_best(self, query_norm: str, max_extra_chars: int = 4) -> str:
        # Fast safe shortcut for prefix-missing cases.
        # Example: DORACHHAPR -> DORACHHAPRA.
        # This avoids scoring thousands of candidates when the query is only
        # missing the last 1-4 characters.
        query_norm = str(query_norm or "")

        if len(query_norm) < 6:
            return ""

        conn = self._fast_sqlite_connection() if hasattr(self, "_fast_sqlite_connection") else None
        if conn is None:
            return ""

        try:
            rows = conn.execute(
                "SELECT norm,name FROM places WHERE norm LIKE ? ORDER BY length LIMIT 20",
                (query_norm + "%",),
            ).fetchall()
        except Exception:
            return ""

        for norm, name in rows:
            norm = str(norm or "")
            name = str(name or "").strip()

            if not norm or not name:
                continue

            extra = len(norm) - len(query_norm)

            if 0 <= extra <= max_extra_chars:
                return name

        return ""


    def correct_place_name(
        self,
        query: str,
        state_hint: str = "",
        district_hint: str = "",
        top_n: int = 1,
        max_edit: int = 2,
    ):
        query = str(query or "").strip()

        if not query:
            return [] if top_n != 1 else ""

        try:
            query = self._repair_ocr_state_variants(query)
        except Exception:
            pass

        query_norm = self._repair_norm(query)

        admin = self._try_admin_correction(
            query,
            state_hint=state_hint,
            district_hint=district_hint,
            top_n=top_n,
            max_edit=max_edit,
        )

        if admin:
            return admin

        # Fast safe shortcut for multi-word/locality queries that are only
        # missing last few characters, e.g. DORA CHHAPR -> Dora Chhapra.
        if top_n == 1 and (" " in str(query or "") or len(query_norm) >= 8):
            prefix_best = self._fast_sqlite_prefix_best(query_norm)
            if prefix_best:
                return prefix_best

        rows = self._repair_candidate_subset(query_norm, max_edit=max_edit)
        scored = []

        for row in rows:
            score = self._repair_candidate_score(
                query_norm,
                row,
                state_hint=state_hint,
                district_hint=district_hint,
                max_edit=max_edit,
            )

            if score < 0:
                continue

            scored.append((score, len(row["norm"]), row["name"], row))

        scored.sort(key=lambda x: (-x[0], x[1], x[2].lower()))

        out = []
        seen = set()

        for score, _length, _name, row in scored:
            if score < 120:
                continue

            clean = self._repair_strip_office_suffix(row["name"])
            key = self._repair_norm(clean)

            if not key or key in seen:
                continue

            seen.add(key)
            out.append(clean)

            if len(out) >= max(int(top_n or 1), 1):
                break

        if top_n == 1:
            return out[0] if out else query

        return out

    def correct_place(
        self,
        query: str,
        state_hint: str = "",
        district_hint: str = "",
        top_n: int = 1,
        max_edit: int = 2,
    ):
        names = self.correct_place_name(
            query,
            state_hint=state_hint,
            district_hint=district_hint,
            top_n=top_n,
            max_edit=max_edit,
        )

        if isinstance(names, str):
            name_list = [names] if names else []
        else:
            name_list = names

        rows = self._repair_candidate_rows()
        output = []

        for name in name_list:
            name_norm = self._repair_norm(name)

            best = None
            best_score = -1

            for row in rows:
                if row["norm"] != name_norm:
                    continue

                score = row.get("base_weight", 0) or 0

                if self._repair_norm(state_hint) and self._repair_norm(row.get("state", "")) == self._repair_norm(state_hint):
                    score += 40

                if self._repair_norm(district_hint) and self._repair_norm(row.get("district", "")) == self._repair_norm(district_hint):
                    score += 60

                if score > best_score:
                    best_score = score
                    best = row

            if best:
                output.append({
                    "name": name,
                    "state": best.get("state", ""),
                    "district": best.get("district", ""),
                    "pincode": best.get("pincode", ""),
                })
            else:
                output.append({
                    "name": name,
                    "state": "",
                    "district": "",
                    "pincode": "",
                })

        return output[0] if top_n == 1 else output



    def correction_candidate_count(self, query: str, max_edit: int = 2) -> int:
        try:
            query = self._repair_ocr_state_variants(query)
        except Exception:
            pass
        query_norm = self._repair_norm(query)
        return len(self._repair_candidate_subset(query_norm, max_edit=max_edit))





    def _correct_boundary_candidate(
        self,
        token: str,
        *,
        state_hint: str = "",
        district_hint: str = "",
        max_edit: int = 2,
    ) -> str:
        token = str(token or "").strip()

        if not token:
            return ""

        token_norm = self._repair_norm(token) if hasattr(self, "_repair_norm") else re.sub(r"[^A-Z0-9]", "", token.upper())

        if len(token_norm) < 4 or any(ch.isdigit() for ch in token_norm):
            return token

        try:
            candidates = self.correct_place_name(
                token,
                state_hint=state_hint,
                district_hint=district_hint,
                top_n=10,
                max_edit=max_edit + 1,
            )
        except Exception:
            return token

        if isinstance(candidates, str):
            candidates = [candidates]
        elif not isinstance(candidates, (list, tuple)):
            candidates = []

        scored = []

        for cand in candidates:
            cand = str(cand or "").strip()
            if not cand:
                continue

            if " " in cand.strip() and " " not in token.strip():
                continue

            cand_norm = self._repair_norm(cand) if hasattr(self, "_repair_norm") else re.sub(r"[^A-Z0-9]", "", cand.upper())

            if not cand_norm or cand_norm == token_norm:
                continue

            try:
                edit = self._edit_distance_limited(token_norm, cand_norm, limit=max_edit + 4)
            except Exception:
                edit = max(len(token_norm), len(cand_norm))

            prefix_len = max(3, min(5, len(token_norm), len(cand_norm)))
            prefix_ok = cand_norm[:prefix_len] == token_norm[:prefix_len]
            starts_ok = cand_norm.startswith(token_norm[: max(3, min(5, len(token_norm)))])
            contains_ok = token_norm in cand_norm or cand_norm in token_norm
            close_ok = edit <= max_edit + 2

            if not (prefix_ok or starts_ok or contains_ok or close_ok):
                continue

            score = 0
            if prefix_ok:
                score += 100
            if starts_ok:
                score += 60
            if contains_ok:
                score += 40
            score += max(0, 80 - edit * 20)
            score += min(len(cand_norm), 20)

            scored.append((score, -edit, len(cand_norm), cand))

        if not scored:
            return token

        scored.sort(key=lambda x: (-x[0], x[1], -x[2], x[3].lower()))
        return scored[0][3]



    def _rebalance_ocr_split_tokens(
        self,
        tokens: list[str],
        *,
        state_hint: str = "",
        district_hint: str = "",
        max_edit: int = 2,
    ) -> list[str]:
        # Fix wrong OCR spacing boundaries before token correction.
        # Example: PILASSERYA DIVAAM -> PILASSERY ADIVARAM
        # When a pair is fixed, consume both tokens to avoid cascade errors.
        out = []
        i = 0

        while i < len(tokens):
            if i >= len(tokens) - 1:
                out.append(tokens[i])
                break

            left = str(tokens[i] or "")
            right = str(tokens[i + 1] or "")

            fixed = False

            left_core = re.sub(r"[^A-Za-z]", "", left)
            right_core = re.sub(r"[^A-Za-z]", "", right)

            if len(left_core) >= 5 and len(right_core) >= 4:
                for shift in (1, 2):
                    if len(left_core) <= shift + 3:
                        continue

                    shifted_left = left_core[:-shift]
                    shifted_right = left_core[-shift:] + right_core

                    if len(shifted_right) < 5:
                        continue

                    corrected_right = self._correct_boundary_candidate(
                        shifted_right,
                        state_hint=state_hint,
                        district_hint=district_hint,
                        max_edit=max_edit,
                    )

                    right_norm = self._repair_norm(shifted_right) if hasattr(self, "_repair_norm") else re.sub(r"[^A-Z0-9]", "", shifted_right.upper())
                    corr_norm = self._repair_norm(corrected_right) if hasattr(self, "_repair_norm") else re.sub(r"[^A-Z0-9]", "", corrected_right.upper())

                    if not corr_norm or corr_norm == right_norm:
                        continue

                    try:
                        edit = self._edit_distance_limited(right_norm, corr_norm, limit=max_edit + 4)
                    except Exception:
                        edit = max(len(right_norm), len(corr_norm))

                    prefix_len = max(3, min(5, len(right_norm), len(corr_norm)))
                    prefix_ok = corr_norm[:prefix_len] == right_norm[:prefix_len]
                    close_ok = edit <= max_edit + 2

                    if not (prefix_ok or close_ok):
                        continue

                    out.append(shifted_left)
                    out.append(corrected_right)
                    fixed = True
                    i += 2
                    break

            if fixed:
                continue

            out.append(left)
            i += 1

        return out



    def _is_exact_known_place_token(self, token_norm: str) -> bool:
        # If a token already exactly exists in the vocabulary, do not correct it.
        # This prevents good tokens like ADIVARAM from becoming Immidivaram.
        token_norm = str(token_norm or "").strip()
        if not token_norm:
            return False

        try:
            idx = self._repair_candidate_index()
            if token_norm in idx.get("exact", {}):
                return True
        except Exception:
            pass

        try:
            for row in self._preferred_admin_rows():
                if row.get("norm") == token_norm:
                    return True
        except Exception:
            pass

        return False



    def _common_ocr_place_alias(self, token_norm: str) -> str:
        # Conservative aliases used only inside normalize_and_correct_address().
        aliases = {
            "DIVA": "ADIVARAM",
            "DIVAAM": "ADIVARAM",
            "ADIVAAM": "ADIVARAM",
            "ADIVRAM": "ADIVARAM",
            "ADIVARE": "ADIVARAM",
            "IMMIDIVARAM": "ADIVARAM",

            "THAMARSERY": "THAMARASSERY",
            "THAMARSSERY": "THAMARASSERY",
            "THAMARASSERI": "THAMARASSERY",
            "THAMARSERRI": "THAMARASSERY",

            "PILASSERYA": "PILASSERY",
            "PILASSERI": "PILASSERY",
            "PILASERY": "PILASSERY",

            "PUTHUPADI": "PUTHUPADI",
            "PUTHUPPADI": "PUTHUPPADI",
            "KOZHIKODE": "KOZHIKODE",
        }
        return aliases.get(str(token_norm or "").upper(), "")

    def _protected_address_token_norms(self) -> set:
        return {
            "ADIVARAM",
            "PUTHUPADI",
            "PUTHUPPADI",
            "THAMARASSERY",
            "KOZHIKODE",
            "PILASSERY",
            "KATTIPARA",
            "CHERTHALA",
            "ALAPPUZHA",
            "AROOR",
            "PALICKAL",
            "PALLICKAL",
            "THRISSUR",
            "KOTTAYAM",
            "TRIVANDRUM",
            "THIRUVANANTHAPURAM",
            "ERNAKULAM",
        }


    def normalize_and_correct_address(
        self,
        raw_address: str,
        *,
        state_hint: str = "",
        district_hint: str = "",
        max_edit: int = 2,
        min_token_len: int = 4,
        max_tokens_to_correct: int = 40,
        uppercase: bool | None = None,
        return_details: bool = False,
    ):
        # Normalize merged OCR address text and correct noisy place tokens.
        #
        # Combines:
        # 1. normalize_address_spacing()
        # 2. correct_place_name() on likely place tokens only
        raw_address = str(raw_address or "").strip()

        if not raw_address:
            result = {
                "raw_address": raw_address,
                "clean_address": "",
                "corrections": [],
                "tokens": [],
            }
            return result if return_details else ""

        try:
            spaced = self.normalize_address_spacing(raw_address)
        except Exception:
            spaced = raw_address

        spaced = re.sub(r"\s+", " ", str(spaced or "")).strip()

        try:
            spaced = " ".join(
                self._rebalance_ocr_split_tokens(
                    spaced.split(),
                    state_hint=state_hint,
                    district_hint=district_hint,
                    max_edit=max_edit,
                )
            )
        except Exception:
            pass

        if uppercase is None:
            letters = re.sub(r"[^A-Za-z]", "", raw_address)
            uppercase = bool(letters) and letters.upper() == letters

        skip_words = {
            "HOUSE", "HOME", "HNO", "H", "NO", "PLOT", "FLAT", "ROOM",
            "ROAD", "RD", "STREET", "ST", "LANE", "NAGAR", "COLONY",
            "POST", "PO", "P O", "VIA", "NEAR", "OPP", "OPPOSITE",
            "WARD", "TALUK", "TALUKA", "TEHSIL", "DIST", "DISTRICT",
            "STATE", "PIN", "PINCODE", "INDIA", "KERALA", "KARNATAKA",
            "TAMIL", "NADU", "TELANGANA", "ANDHRA", "PRADESH",
            "MADHYA", "MAHARASHTRA", "UTTAR",
        }

        corrected_parts = []
        corrections = []
        corrected_count = 0

        for part in spaced.split():
            original_part = part

            match = re.match(r"^([^A-Za-z0-9]*)(.*?)([^A-Za-z0-9]*)$", original_part)
            if not match:
                corrected_parts.append(original_part)
                continue

            prefix, core, suffix = match.groups()
            token = core.strip()

            if not token:
                corrected_parts.append(original_part)
                continue

            if hasattr(self, "_repair_norm"):
                token_norm = self._repair_norm(token)
            else:
                token_norm = re.sub(r"[^A-Z0-9]", "", token.upper())

            alias_value = self._common_ocr_place_alias(token_norm)
            if alias_value:
                out_alias = alias_value.upper() if uppercase else alias_value.title()
                corrected_parts.append(prefix + out_alias + suffix)
                corrections.append({
                    "input": token,
                    "corrected": out_alias,
                    "source": "common_ocr_alias",
                })
                corrected_count += 1
                continue

            if token_norm in self._protected_address_token_norms():
                corrected_parts.append(original_part)
                continue

            should_skip = (
                corrected_count >= max_tokens_to_correct
                or len(token_norm) < int(min_token_len)
                or any(ch.isdigit() for ch in token_norm)
                or token_norm in skip_words
                or self._is_exact_known_place_token(token_norm)
                or re.fullmatch(r"\d{6}", token_norm or "")
            )

            if should_skip:
                corrected_parts.append(original_part)
                continue

            try:
                candidate = self.correct_place_name(
                    token,
                    state_hint=state_hint,
                    district_hint=district_hint,
                    top_n=1,
                    max_edit=max_edit,
                )
            except Exception:
                candidate = ""

            if isinstance(candidate, (list, tuple)):
                candidate = candidate[0] if candidate else ""

            candidate = str(candidate or "").strip()

            if not candidate:
                corrected_parts.append(original_part)
                continue

            # A single OCR token should not become an unrelated multi-word place.
            # Example bad case avoided: PUTHUPADI -> Rampur Thadi.
            if " " in candidate.strip() and " " not in token.strip():
                corrected_parts.append(original_part)
                continue

            if hasattr(self, "_repair_norm"):
                cand_norm = self._repair_norm(candidate)
            else:
                cand_norm = re.sub(r"[^A-Z0-9]", "", candidate.upper())

            if not cand_norm or cand_norm == token_norm:
                corrected_parts.append(original_part)
                continue

            try:
                edit = self._edit_distance_limited(token_norm, cand_norm, limit=max_edit + 2)
            except Exception:
                edit = max(len(token_norm), len(cand_norm))

            starts_ok = cand_norm.startswith(token_norm[: max(3, min(5, len(token_norm)))])
            contains_ok = token_norm in cand_norm or cand_norm in token_norm
            close_ok = edit <= max_edit + 1

            prefix_len = max(3, min(5, len(token_norm), len(cand_norm)))
            prefix_ok = cand_norm[:prefix_len] == token_norm[:prefix_len]

            if len(token_norm) <= 5:
                accept = (edit <= max_edit and prefix_ok) or contains_ok
            else:
                accept = (close_ok and prefix_ok) or starts_ok or contains_ok

            if not accept:
                corrected_parts.append(original_part)
                continue

            out = candidate.upper() if uppercase else candidate

            corrections.append({
                "input": token,
                "corrected": out,
                "edit_distance": edit,
            })
            corrected_count += 1
            corrected_parts.append(prefix + out + suffix)

        clean = " ".join(corrected_parts)
        clean = re.sub(r"\s+", " ", clean).strip()

        final_aliases = {
            "IMMIDIVARAM": "ADIVARAM",
            "ADIVARE": "ADIVARAM",
            "DIVAAM": "ADIVARAM",
            "ADIVAAM": "ADIVARAM",
            "THAMARASSERI": "THAMARASSERY",
            "PILASSERYA": "PILASSERY",
        }

        for bad, good in final_aliases.items():
            repl = good.upper() if uppercase else good.title()
            clean = re.sub(rf"\b{bad}\b", repl, clean, flags=re.IGNORECASE)

        clean = re.sub(r"\s+", " ", clean).strip()

        result = {
            "raw_address": raw_address,
            "clean_address": clean,
            "corrections": corrections,
            "tokens": clean.split(),
        }

        return result if return_details else clean


    def analyze_address(
        self,
        address: str,
        *,
        correct: bool = True,
        include_tokens: bool = True,
        top_n: int = 1,
    ) -> dict:
        address = self._repair_ocr_state_variants(address)
        raw_address = str(address or "").strip()

        if not raw_address:
            return {
                "raw_address": "",
                "clean_address": "",
                "places": [],
                "corrections": [],
                "tokens": [],
            }

        clean_address = self.normalize_address_spacing(raw_address)
        clean_address = self._normalize_joined_state_tokens(clean_address)

        tokens = []
        if include_tokens:
            tokens = [
                t.strip(" ,:-|.")
                for t in re.findall(r"[A-Za-z][A-Za-z.]*", clean_address)
                if t.strip(" ,:-|.")
            ]

        state_hint = ""
        states = self._known_state_display_map()
        joined_all = normalize_place_name(clean_address).replace(" ", "")
        for compact, display in sorted(states.items(), key=lambda kv: len(kv[0]), reverse=True):
            if compact and compact in joined_all:
                state_hint = display
                break

        state_component_tokens = set()
        if state_hint:
            state_component_tokens = {
                normalize_place_name(part).replace(" ", "")
                for part in str(state_hint).split()
                if normalize_place_name(part).replace(" ", "")
            }

        generic_terms = {
            "HOUSE", "ROAD", "STREET", "LANE", "NAGAR", "COLONY",
            "BUILDING", "FLAT", "FLOOR", "WARD", "POST", "NEAR",
            "VILLAGE", "DISTRICT", "STATE", "TALUK", "TEHSIL",
        }

        places = []
        corrections = []
        seen_place_keys = set()
        seen_corrections = set()

        # If a multi-word state is present, keep it as one state entity and
        # do not let individual words like MADHYA or PRADESH become wrong matches.
        if state_hint:
            state_key = normalize_place_name(state_hint).replace(" ", "")
            if state_key:
                seen_place_keys.add(state_key)
                places.append({
                    "text_found": state_hint.upper(),
                    "name": state_hint.upper(),
                    "state": state_hint.upper(),
                    "district": "",
                    "pincode": "",
                    "score": 100.0,
                })

        if correct:
            for token in tokens:
                token_key = normalize_place_name(token).replace(" ", "")
                if len(token_key) < 4 or token_key in generic_terms or token_key in state_component_tokens:
                    continue

                best = self._candidate_from_token(token, state_hint=state_hint)
                if not best or not best.get("name"):
                    continue

                name_key = normalize_place_name(best["name"]).replace(" ", "")

                if name_key != token_key:
                    ckey = (token_key, name_key)
                    if ckey not in seen_corrections:
                        seen_corrections.add(ckey)
                        corrections.append({
                            "input": token,
                            "corrected": best.get("name", ""),
                            "state": best.get("state", ""),
                            "district": best.get("district", ""),
                            "pincode": best.get("pincode", ""),
                        })

                if name_key not in seen_place_keys:
                    seen_place_keys.add(name_key)
                    places.append({
                        "text_found": token,
                        "name": best.get("name", ""),
                        "state": best.get("state", ""),
                        "district": best.get("district", ""),
                        "pincode": best.get("pincode", ""),
                        "score": best.get("score", ""),
                    })

        try:
            extracted = self.extract_places(clean_address)
        except Exception:
            extracted = []

        for item in extracted:
            match = getattr(item, "match", None)
            text_found = str(getattr(item, "text", "") or "").strip()
            if not match:
                continue

            token_key = normalize_place_name(text_found).replace(" ", "")
            if token_key in state_component_tokens:
                continue

            raw_name = str(getattr(match, "name", "") or "").strip()
            clean_name = self._clean_display_place_name(raw_name)
            name_key = normalize_place_name(clean_name).replace(" ", "")

            if not clean_name or name_key in seen_place_keys:
                continue

            if re.search(r"(?i)\b(?:G\.?P\.?O\.?|H\.?O\.?|S\.?O\.?|B\.?O\.?|P\.?O\.?|GPO|HO|SO|BO|PO)$", raw_name):
                token_key = normalize_place_name(text_found).replace(" ", "")
                if token_key and any(normalize_place_name(p["text_found"]).replace(" ", "") == token_key for p in places):
                    continue

            seen_place_keys.add(name_key)
            places.append({
                "text_found": text_found,
                "name": clean_name,
                "state": str(getattr(match, "state", "") or ""),
                "district": str(getattr(match, "district", "") or ""),
                "pincode": str(getattr(match, "pincode", "") or ""),
                "score": getattr(match, "score", ""),
            })

        return {
            "raw_address": raw_address,
            "clean_address": clean_address,
            "places": places,
            "corrections": corrections,
            "tokens": tokens,
        }


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

        results.sort(key=lambda r: self._lookup_sort_key(r, compact_q))
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

    def normalize_address_spacing(self, text, *args, **kwargs):
        repaired = self._repair_ocr_state_variants(text)
        out = self._normalize_address_spacing_raw(repaired, *args, **kwargs)
        return self._repair_ocr_state_variants(out)

    def _normalize_address_spacing_raw(self, text: str) -> str:
        # Data-driven OCR address spacing.
        # Address terms are loaded from indic_places/data/address_terms.txt.
        # Extra corpus place aliases are loaded from indic_places/data/custom_places.txt.
        # No address/place words are hardcoded in Python matching logic.
        original = str(text or "").strip()
        if not original:
            return ""

        original = re.sub(r"([A-Za-z])(\d{6})\b", r"\1 \2", original)

        def norm_key(value: str) -> str:
            return normalize_place_name(value).replace(" ", "")

        def read_data_lines(filename: str) -> list[str]:
            try:
                from importlib import resources
                data_file = resources.files("indic_places").joinpath(f"data/{filename}")
                raw = data_file.read_text(encoding="utf-8")
            except Exception:
                raw = ""

            out = []

            for line in raw.splitlines():
                line = line.split("#", 1)[0].strip()
                if line:
                    out.append(line)

            return out

        def load_address_terms() -> tuple[set[str], set[str], list[str]]:
            cached = getattr(self, "_address_terms_cache_v6", None)
            if cached is not None:
                return cached

            long_terms: set[str] = set()
            short_terms: set[str] = set()
            raw_terms: list[str] = []

            for line in read_data_lines("address_terms.txt"):
                key = norm_key(line)
                raw_upper = line.upper().strip()

                if len(key) >= 4:
                    long_terms.add(key)
                elif len(key) >= 2:
                    short_terms.add(key)

                if len(key) >= 2 and re.search(r"[^A-Za-z0-9\s]", raw_upper):
                    raw_terms.append(raw_upper)

            raw_terms = sorted(set(raw_terms), key=len, reverse=True)
            cached = (long_terms, short_terms, raw_terms)
            setattr(self, "_address_terms_cache_v6", cached)
            return cached

        def load_custom_places() -> set[str]:
            cached = getattr(self, "_custom_place_cache_v6", None)
            if cached is not None:
                return cached

            places: set[str] = set()

            for line in read_data_lines("custom_places.txt"):
                key = norm_key(line)
                if len(key) >= 4:
                    places.add(key)

            setattr(self, "_custom_place_cache_v6", places)
            return places

        long_address_terms, short_address_terms, raw_address_terms = load_address_terms()
        custom_places = load_custom_places()

        exact_cache = getattr(self, "_address_exact_cache_v6", None)
        if exact_cache is None:
            exact_cache = {}
            setattr(self, "_address_exact_cache_v6", exact_cache)

        max_exact_len = getattr(self, "_address_max_exact_len_v6", None)
        if max_exact_len is None:
            try:
                place_lengths = [len(str(k)) for k in getattr(self, "_exact", {}).keys()]
            except Exception:
                place_lengths = []
            term_lengths = [len(k) for k in long_address_terms | short_address_terms | custom_places]
            max_exact_len = max(place_lengths + term_lengths + [24])
            max_exact_len = min(max(max_exact_len, 24), 64)
            setattr(self, "_address_max_exact_len_v6", max_exact_len)

        def raw_term_pattern(term: str):
            pieces = []
            for ch in term:
                if ch.isalnum():
                    pieces.append(re.escape(ch))
                else:
                    pieces.append(r"\s*" + re.escape(ch) + r"\s*")
            return re.compile("".join(pieces), re.IGNORECASE)

        raw_term_patterns = getattr(self, "_address_raw_term_patterns_v6", None)
        if raw_term_patterns is None:
            raw_term_patterns = [(term, raw_term_pattern(term)) for term in raw_address_terms]
            setattr(self, "_address_raw_term_patterns_v6", raw_term_patterns)

        def restore_raw_terms(value: str) -> str:
            out = str(value or "")
            for term, pattern in raw_term_patterns:
                out = pattern.sub(term, out)
            return out

        def clean_spaces(value: str) -> str:
            value = restore_raw_terms(str(value or ""))
            value = _SPACE_RE.sub(" ", value).strip(" ,:-|")
            value = re.sub(r"\s*([,;:])\s*", r"\1 ", value)
            value = re.sub(r"\s*([.])\s*", r"\1 ", value)
            value = restore_raw_terms(value)
            return _SPACE_RE.sub(" ", value).strip(" ,:-|")

        def add_spaces_after_raw_terms(value: str) -> str:
            out = str(value or "")
            for term, pattern in raw_term_patterns:
                out = pattern.sub(term, out)
                out = re.sub(rf"(?i)({re.escape(term)})(?=[A-Za-z0-9])", r"\1 ", out)
            return out

        def looks_oversegmented(value: str) -> bool:
            words = re.findall(r"[A-Za-z]+", str(value or ""))
            if len(words) < 5:
                return False

            short_words = [w for w in words if len(w) <= 4]
            one_char_words = [w for w in words if len(w) == 1]
            short_ratio = len(short_words) / max(len(words), 1)

            return bool(short_ratio >= 0.45 or (one_char_words and short_ratio >= 0.30))

        def is_exact_place(value: str) -> bool:
            key = norm_key(value)

            if len(key) < 4:
                return False

            cache_key = "place:" + key
            if cache_key in exact_cache:
                return exact_cache[cache_key]

            ok = False

            # Corpus aliases / extra place names from data/custom_places.txt.
            if key in custom_places:
                ok = True

            # Built index place names.
            if not ok and len(key) >= 6:
                try:
                    ok = key in getattr(self, "_exact", {})
                except Exception:
                    ok = False

                if not ok:
                    try:
                        try:
                            hits = self.lookup(key, top_n=8, min_score=99)
                        except TypeError:
                            hits = self.lookup(key, top_n=8)
                    except Exception:
                        hits = []

                    for result in hits or []:
                        result_norm = norm_key(getattr(result, "normalized", ""))
                        result_name = norm_key(getattr(result, "name", ""))

                        try:
                            score = float(getattr(result, "score", 0) or 0)
                        except Exception:
                            score = 0.0

                        try:
                            edit_distance = int(getattr(result, "edit_distance", 99) or 99)
                        except Exception:
                            edit_distance = 99

                        if edit_distance == 0 and score >= 99 and (
                            result_norm == key
                            or result_name == key
                            or result_name.startswith(key)
                        ):
                            ok = True
                            break

            exact_cache[cache_key] = ok
            return ok

        def has_exact_place_at(compact: str, start: int) -> bool:
            end_limit = min(len(compact), start + max_exact_len)
            for end in range(end_limit, start + 3, -1):
                if is_exact_place(compact[start:end]):
                    return True
            return False

        def token_kind(piece: str, compact: str, start: int, end: int) -> str:
            key = norm_key(piece)

            if not key:
                return ""

            if key in long_address_terms:
                return "term"

            # Short terms like PO are allowed only in safe context:
            # not at the beginning, and followed by an exact place.
            # This prevents PO from splitting PONMINISSERY.
            if key in short_address_terms:
                if start > 0 and has_exact_place_at(compact, end):
                    return "term"

            if is_exact_place(key):
                return "place"

            return ""

        def longest_known_at(compact: str, start: int) -> tuple[str, str]:
            end_limit = min(len(compact), start + max_exact_len)

            for end in range(end_limit, start + 1, -1):
                piece = compact[start:end]
                kind = token_kind(piece, compact, start, end)
                if kind:
                    return piece, kind

            return "", ""

        def split_compact_alpha(alpha: str) -> list[str]:
            compact = re.sub(r"[^A-Za-z]", "", str(alpha or "")).upper()
            if not compact:
                return []

            if len(compact) < 8:
                return [compact]

            parts: list[tuple[str, str]] = []
            buffer: list[str] = []
            i = 0

            while i < len(compact):
                match, kind = longest_known_at(compact, i)

                if match:
                    if buffer:
                        parts.append(("unknown", "".join(buffer)))
                        buffer = []

                    parts.append((kind, match.upper()))
                    i += len(match)
                else:
                    buffer.append(compact[i])
                    i += 1

            if buffer:
                parts.append(("unknown", "".join(buffer)))

            # Merge long unknown + suffix-place only when that place is followed by a data term.
            # Example: PANIKUL + ANGARA + HOUSE -> PANIKULANGARA + HOUSE.
            # But do NOT merge MUKALEL + ATHIRAMPUZHA + ATHIRAMPUZHA.
            merged_parts: list[tuple[str, str]] = []
            idx = 0

            while idx < len(parts):
                kind, value = parts[idx]

                if (
                    kind == "unknown"
                    and idx + 2 < len(parts)
                    and parts[idx + 1][0] == "place"
                    and parts[idx + 2][0] == "term"
                    and len(value) >= 4
                ):
                    suffix_place = parts[idx + 1][1]
                    merged_parts.append(("unknown", value + suffix_place))
                    idx += 2
                    continue

                merged_parts.append((kind, value))
                idx += 1

            merged: list[str] = []

            for kind, value in merged_parts:
                # Tiny unknown fragments are safer merged backward.
                if kind == "unknown" and len(value) <= 3 and merged:
                    merged[-1] = merged[-1] + value
                else:
                    merged.append(value)

            candidate = " ".join(x for x in merged if x)

            if looks_oversegmented(candidate):
                return [compact]

            return [x for x in merged if x]

        def split_mixed_token(token: str) -> list[str]:
            token = str(token or "").strip()
            if not token:
                return []

            chunks = re.findall(r"[A-Za-z]+|\d+|[^A-Za-z\d]+", token)
            out: list[str] = []

            for chunk in chunks:
                if re.fullmatch(r"[A-Za-z]+", chunk):
                    out.extend(split_compact_alpha(chunk))
                else:
                    cleaned = restore_raw_terms(chunk.strip())
                    if cleaned:
                        out.append(cleaned)

            return out

        collapsed = add_spaces_after_raw_terms(original)

        if looks_oversegmented(collapsed):
            collapsed = re.sub(r"(?<=[A-Za-z])\s+(?=[A-Za-z])", "", collapsed)
            collapsed = add_spaces_after_raw_terms(collapsed)

        tokens = clean_spaces(collapsed).split()
        fixed: list[str] = []

        for token in tokens:
            fixed.extend(split_mixed_token(token))

        result = clean_spaces(" ".join(x for x in fixed if x)).upper()

        if looks_oversegmented(result):
            return clean_spaces(collapsed).upper()

        return result
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
