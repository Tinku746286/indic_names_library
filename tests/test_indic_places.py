"""
Tests for indic_places library.
Run with: pytest tests/ -v
"""
import pytest
from indic_places import IndicPlaces, PlaceTagger


@pytest.fixture(scope="module")
def ip():
    return IndicPlaces()


@pytest.fixture(scope="module")
def tagger():
    return PlaceTagger()


# ---------------------------------------------------------------------------
# IndicPlaces — lookup
# ---------------------------------------------------------------------------

class TestLookup:
    def test_exact_city(self, ip):
        results = ip.lookup("Mumbai")
        assert results, "Should find Mumbai"
        assert results[0].name == "Mumbai"
        assert results[0].score == 100.0

    def test_fuzzy_city(self, ip):
        results = ip.lookup("Bangalor")
        assert results, "Should fuzzy-match Bangalore"
        assert results[0].name == "Bangalore"

    def test_fuzzy_city2(self, ip):
        results = ip.lookup("Chennnai")
        assert results, "Should fuzzy-match Chennai"
        assert any(r.name == "Chennai" for r in results)

    def test_state(self, ip):
        results = ip.lookup("Maharashtra")
        assert results[0].kind == "state"

    def test_kind_filter(self, ip):
        results = ip.lookup("Delhi", kind="state")
        assert all(r.kind == "state" for r in results)

    def test_case_insensitive(self, ip):
        r1 = ip.lookup("MUMBAI")
        r2 = ip.lookup("mumbai")
        assert r1[0].name == r2[0].name

    def test_no_match(self, ip):
        results = ip.lookup("zzzzzzxxx", min_score=90.0)
        assert results == []

    def test_top_n(self, ip):
        results = ip.lookup("Nagar", top_n=3)
        assert len(results) <= 3


# ---------------------------------------------------------------------------
# IndicPlaces — search
# ---------------------------------------------------------------------------

class TestSearch:
    def test_substring(self, ip):
        results = ip.search("Nagar")
        assert len(results) > 5, "Many places contain 'Nagar'"

    def test_search_kind_filter(self, ip):
        results = ip.search("pur", kind="village")
        assert all(r.kind == "village" for r in results)


# ---------------------------------------------------------------------------
# IndicPlaces — info
# ---------------------------------------------------------------------------

class TestInfo:
    def test_state_info(self, ip):
        info = ip.info("Karnataka")
        assert info is not None
        assert info["kind"] == "state"
        assert "cities" in info
        assert "Bangalore" in info["cities"]

    def test_city_info(self, ip):
        info = ip.info("Hyderabad")
        assert info is not None
        assert info["kind"] == "city"
        assert info["state"] in ("Telangana", "Andhra Pradesh")

    def test_not_found(self, ip):
        assert ip.info("zznotaplace") is None


# ---------------------------------------------------------------------------
# IndicPlaces — helpers
# ---------------------------------------------------------------------------

class TestHelpers:
    def test_contains(self, ip):
        assert "Mumbai" in ip
        assert "zzzzzzz" not in ip

    def test_len(self, ip):
        assert len(ip) > 3000

    def test_all_states(self, ip):
        states = ip.all_states()
        assert "Maharashtra" in states
        assert "Kerala" in states
        assert len(states) >= 28

    def test_cities_in_state(self, ip):
        cities = ip.cities_in_state("Tamil Nadu")
        assert "Chennai" in cities
        assert "Madurai" in cities

    def test_stats(self, ip):
        stats = ip.stats()
        assert "city" in stats
        assert "village" in stats
        assert stats["city"] > 100


# ---------------------------------------------------------------------------
# PlaceTagger
# ---------------------------------------------------------------------------

class TestTagger:
    def test_simple(self, tagger):
        r = tagger.tag("I live in Mumbai")
        names = [tp.canonical for tp in r.places]
        assert "Mumbai" in names

    def test_fuzzy_tag(self, tagger):
        r = tagger.tag("flight from Dilli to Chennnai")
        canonical = [tp.canonical for tp in r.places]
        assert any("Delhi" in c or "Dilli" in c for c in canonical)

    def test_annotated(self, tagger):
        r = tagger.tag("I am from Pune going to Nagpur")
        ann = r.annotated
        assert "[" in ann  # at least one annotation

    def test_extract_places(self, tagger):
        places = tagger.extract_places("Office is in Bengaluru, home in Mysore")
        assert len(places) >= 1

    def test_no_places(self, tagger):
        r = tagger.tag("The sky is blue and the sea is green")
        # should find zero or very few matches
        assert len(r.places) == 0
