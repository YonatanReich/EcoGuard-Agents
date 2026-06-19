"""
Geospatial Context Agent

This agent is responsible for collecting basic geospatial context
around a given coordinate using OpenStreetMap through the Overpass API.
"""


class GeospatialContextAgent:
    """
    Collects nearby geographic objects around a given latitude and longitude.
    """

    def __init__(self):
        self.source_name = "OpenStreetMap / Overpass API"