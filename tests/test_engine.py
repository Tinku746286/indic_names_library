from indic_places import IndicPlaces


def test_segment_basic():
    ip = IndicPlaces(build_delete_index=False)
    assert ip.segment("iliveinmumbaiorkerala").segmented == "i live in mumbai or kerala"


def test_lookup_basic():
    ip = IndicPlaces()
    hits = ip.lookup("Bangalor", top_n=3, min_score=60)
    assert hits
