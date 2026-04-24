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

    def correct_place_name(self, query: str, state_hint: str = "", top_n: int = 1):
        original = str(query or "").strip()
        if not original:
            return [] if top_n != 1 else ""

        tokens = re.findall(r"[A-Za-z]+", original)
        states = self._correction_state_set()

        inferred_state = state_hint
        place_tokens: list[str] = []

        for token in tokens:
            nt = normalize_place_name(token).replace(" ", "")
            if nt in states:
                inferred_state = token
            else:
                place_tokens.append(token)

        target = max(place_tokens, key=len) if place_tokens else original
        rows = self._correction_candidate_rows(target, inferred_state)

        q = normalize_place_name(target).replace(" ", "")
        state_q = normalize_place_name(inferred_state).replace(" ", "")

        scored = []
        for name, state, district, source in rows:
            norm = normalize_place_name(name).replace(" ", "")
            if not norm:
                continue

            sim = SequenceMatcher(None, q, norm).ratio()

            prefix_bonus = 25 if norm.startswith(q) and len(norm) > len(q) else 0
            contains_bonus = 8 if q in norm else 0
            missing_first_bonus = 12 if len(norm) > 1 and norm[1:].startswith(q[: min(len(q), len(norm) - 1)]) else 0
            exact_same_penalty = 30 if norm == q else 0

            office_penalty = 20 if re.search(
                r"(?i)\\b(?:G\\.?P\\.?O\\.?|H\\.?O\\.?|S\\.?O\\.?|B\\.?O\\.?|P\\.?O\\.?|GPO|HO|SO|BO|PO)$",
                name,
            ) else 0

            admin_bonus = 15 if norm in {
                normalize_place_name(state).replace(" ", ""),
                normalize_place_name(district).replace(" ", ""),
            } else 0

            state_bonus = 20 if state_q and normalize_place_name(state).replace(" ", "") == state_q else 0

            score = (
                (sim * 100)
                + prefix_bonus
                + contains_bonus
                + missing_first_bonus
                + admin_bonus
                + state_bonus
                - exact_same_penalty
                - office_penalty
            )

            scored.append((score, len(norm), name, state, district, source))

        scored.sort(key=lambda x: (-x[0], x[1], x[2].lower()))

        names: list[str] = []
        seen_names: set[str] = set()

        for score, _length, name, _state, _district, _source in scored:
            clean = self._strip_office_suffix_for_correction(name)
            key = normalize_place_name(clean).replace(" ", "")
            if not key or key in seen_names:
                continue

            if key == q and len(scored) > 1:
                continue

            names.append(clean)
            seen_names.add(key)

            if len(names) >= max(int(top_n or 1), 1):
                break

        if top_n == 1:
            return names[0] if names else original

        return names

    def correct_place(self, query: str, state_hint: str = "", top_n: int = 1):
        names = self.correct_place_name(query, state_hint=state_hint, top_n=top_n)
        if isinstance(names, str):
            names_list = [names] if names else []
        else:
            names_list = names

        out = []
        for name in names_list:
            details = {"name": name, "state": "", "district": "", "pincode": ""}

            try:
                matches = self.lookup(name, top_n=20)
            except Exception:
                matches = []

            name_key = normalize_place_name(name).replace(" ", "")
            for m in matches:
                m_name = self._strip_office_suffix_for_correction(getattr(m, "name", ""))
                m_key = normalize_place_name(m_name).replace(" ", "")
                district_key = normalize_place_name(getattr(m, "district", "")).replace(" ", "")

                if m_key == name_key or district_key == name_key:
                    details = {
                        "name": name,
                        "state": getattr(m, "state", "") or "",
                        "district": getattr(m, "district", "") or "",
                        "pincode": getattr(m, "pincode", "") or "",
                    }
                    break

            out.append(details)

        return out[0] if top_n == 1 else out





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

    def analyze_address(
        self,
        address: str,
        *,
        correct: bool = True,
        include_tokens: bool = True,
        top_n: int = 1,
    ) -> dict:
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

    def normalize_address_spacing(self, text: str) -> str:
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
