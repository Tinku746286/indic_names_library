"""
indic_places.tagger
===================
PlaceTagger — extracts and tags Indian place names from free text.

Usage:
    from indic_places import PlaceTagger

    tagger = PlaceTagger()
    result = tagger.tag("I travelled from Mumbai to Banglore via Pune")
    print(result.places)
    # [TaggedPlace(text='Mumbai', ...), TaggedPlace(text='Banglore', ...), ...]
    print(result.annotated)
    # 'I travelled from [Mumbai|city|Maharashtra] to [Banglore→Bangalore|city|Karnataka] via [Pune|city|Maharashtra]'
"""

from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import List, Optional

from .core import IndicPlaces, PlaceResult, _normalize


@dataclass
class TaggedPlace:
    """A place mention found in text."""
    text: str                     # original text span
    start: int                    # character offset
    end: int                      # character offset (exclusive)
    matched: Optional[PlaceResult] = None   # best fuzzy match

    @property
    def canonical(self) -> str:
        return self.matched.name if self.matched else self.text

    @property
    def kind(self) -> Optional[str]:
        return self.matched.kind if self.matched else None

    @property
    def state(self) -> Optional[str]:
        return self.matched.state if self.matched else None

    @property
    def score(self) -> float:
        return self.matched.score if self.matched else 0.0

    def __repr__(self):
        return (f"<TaggedPlace text={self.text!r} → {self.canonical!r} "
                f"kind={self.kind!r} score={self.score:.1f}>")


@dataclass
class TagResult:
    """Result of tagging a piece of text."""
    text: str
    places: List[TaggedPlace] = field(default_factory=list)

    @property
    def annotated(self) -> str:
        """Return original text with place spans annotated inline."""
        if not self.places:
            return self.text
        out = []
        prev = 0
        for tp in sorted(self.places, key=lambda x: x.start):
            out.append(self.text[prev:tp.start])
            tag = f"[{tp.text}"
            if tp.matched and tp.canonical != tp.text:
                tag += f"→{tp.canonical}"
            tag += f"|{tp.kind or '?'}"
            if tp.state:
                tag += f"|{tp.state}"
            tag += "]"
            out.append(tag)
            prev = tp.end
        out.append(self.text[prev:])
        return "".join(out)

    @property
    def place_names(self) -> List[str]:
        """Return canonical names of all found places."""
        return [tp.canonical for tp in self.places]

    def __repr__(self):
        return f"<TagResult places={len(self.places)} text={self.text[:60]!r}>"


class PlaceTagger:
    """
    Tag Indian place mentions in free text.

    Parameters
    ----------
    max_edit_distance : int   — fuzzy tolerance (default 2)
    min_score         : float — minimum match score to accept (default 60)
    min_token_length  : int   — ignore tokens shorter than this (default 4)

    Example
    -------
    >>> tagger = PlaceTagger()
    >>> r = tagger.tag("Flight from Dilli to Chennnai via Hydrabad")
    >>> r.place_names
    ['Delhi', 'Chennai', 'Hyderabad']
    >>> print(r.annotated)
    """

    # Common English stop words + Indian prepositions to skip
    _STOPWORDS = {
        "the","a","an","is","are","was","were","be","been","being",
        "have","has","had","do","does","did","will","would","could",
        "should","may","might","shall","can","need","dare","used",
        "to","of","in","on","at","by","for","with","about","against",
        "between","into","through","during","before","after","above",
        "below","from","up","down","out","off","over","under","again",
        "then","once","here","there","when","where","why","how","all",
        "both","each","few","more","most","other","some","such","than",
        "too","very","just","not","no","nor","so","yet","but","and",
        "or","as","if","while","since","because","although","though",
        "i","you","he","she","it","we","they","me","him","her","us",
        "them","my","your","his","its","our","their","this","that",
        "these","those","what","which","who","whom","whose",
        # Indian common words
        "ji","bhai","behan","dada","nana","mama","chacha","tauji",
        "gaon","sheher","shahar","desh","pradesh","rajya",
        "near","beside","next","opposite","behind","front",
        "road","street","lane","marg","path","way","route",
        "north","south","east","west","central","upper","lower",
        "new","old","big","small","great","little","main","side",
    }

    def __init__(
        self,
        max_edit_distance: int = 2,
        min_score: float = 60.0,
        min_token_length: int = 4,
    ):
        self._ip = IndicPlaces(max_edit_distance=max_edit_distance)
        self.min_score = min_score
        self.min_token_length = min_token_length

    def tag(self, text: str) -> TagResult:
        """
        Find all place mentions in *text* and return a TagResult.

        Strategy:
        1. Tokenise into word spans (preserve offsets).
        2. Try multi-word windows (up to 4 words) first.
        3. Fall back to single words.
        4. Skip overlapping spans.
        """
        tokens = self._tokenize(text)
        if not tokens:
            return TagResult(text=text)

        used: set = set()          # character positions already claimed
        tagged: List[TaggedPlace] = []

        # Try windows of 4, 3, 2, 1 tokens
        for window in (4, 3, 2, 1):
            for i in range(len(tokens) - window + 1):
                chunk = tokens[i:i + window]
                start = chunk[0][1]
                end = chunk[-1][2]

                # Skip if any character in span already claimed
                span = set(range(start, end))
                if span & used:
                    continue

                phrase = text[start:end]
                norm_phrase = _normalize(phrase)

                # Skip too-short or stopword tokens
                if len(norm_phrase) < self.min_token_length:
                    continue
                if window == 1 and norm_phrase in self._STOPWORDS:
                    continue
                # Skip purely numeric
                if norm_phrase.replace(" ", "").isdigit():
                    continue

                # Multi-word windows need a stricter min_score to avoid false merges
                effective_min = self.min_score if window == 1 else max(self.min_score + 15, 75.0)
                hits = self._ip.lookup(phrase, top_n=1, min_score=effective_min)
                if hits:
                    tagged.append(TaggedPlace(
                        text=phrase,
                        start=start,
                        end=end,
                        matched=hits[0],
                    ))
                    used |= span

        tagged.sort(key=lambda tp: tp.start)
        return TagResult(text=text, places=tagged)

    def extract_places(self, text: str) -> List[str]:
        """Convenience method — return canonical place names found in text."""
        return self.tag(text).place_names

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _tokenize(self, text: str):
        """
        Return list of (token_str, start, end) tuples.
        Splits on whitespace and punctuation, preserving offsets.
        """
        pattern = re.compile(r"[A-Za-z\u0900-\u097F\u0980-\u09FF\u0A00-\u0A7F\u0A80-\u0AFF\u0B00-\u0B7F\u0C00-\u0C7F\u0C80-\u0CFF\u0D00-\u0D7F']+")
        return [(m.group(), m.start(), m.end()) for m in pattern.finditer(text)]
