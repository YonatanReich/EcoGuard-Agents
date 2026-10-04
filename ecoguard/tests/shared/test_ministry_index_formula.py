import pytest

from ecoguard.shared.ministry_index_formula import index


# (pollutant, the Ministry's published 24 h mean, the index it published),
# from indexFastSrv on 4 Oct 2026, stations 60, 86, 81 and 337.
PUBLISHED = [
    ("PM10", 42.7, 68), ("PM10", 46.1, 66), ("PM2.5", 7.8, 79), ("PM10", 15.0, 89),
    ("PM2.5", 9.2, 76), ("PM10", 40.4, 70), ("PM2.5", 7.07, 81), ("PM10", 14.9, 89),
]


@pytest.mark.parametrize("pollutant,mean,published", PUBLISHED)
def test_reproduces_the_index_the_ministry_published(pollutant, mean, published):
    assert abs(index(pollutant, mean) - published) <= 1


def test_the_bands_land_where_the_method_document_says():
    # Table 1: 0..50 moderate, -1..-200 low, -201..-400 very low air quality.
    assert index("PM10", 129) == 0          # the environment value
    assert -200 <= index("PM10", 250) < 0   # high pollution
    assert index("PM10", 400) < -200        # very high pollution
