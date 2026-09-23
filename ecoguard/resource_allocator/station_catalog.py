"""Load and normalize the emergency-station reference catalogs."""

from ecoguard.database.repositories.fire_stations import fire_stations_geojson
from ecoguard.database.repositories.mda_stations import mda_stations_geojson
from ecoguard.database.repositories.police_stations import police_stations_geojson
from ecoguard.resource_allocator.geo import coordinates


STATION_TYPES = {
    "fire_department": ("fire_station", "fire_stations"),
    "police": ("police_station", "police_stations"),
    "medical_services": ("mda_station", "mda_stations"),
}


def default_station_readers():
    """Return readers for the emergency-station tables already in the DB."""
    return {
        "fire_department": fire_stations_geojson,
        "police": police_stations_geojson,
        "medical_services": mda_stations_geojson,
    }


def resource_key(recommended_unit, properties):
    """Build the stable identity used for a station throughout allocation."""
    if recommended_unit not in STATION_TYPES:
        raise ValueError(f"unsupported resource type: {recommended_unit}")

    database_id = properties.get("database_id")
    if (
        not isinstance(database_id, int)
        or isinstance(database_id, bool)
        or database_id <= 0
    ):
        raise ValueError(f"{recommended_unit} database_id is missing")
    return recommended_unit, database_id


class StationCatalog:
    """Immutable-in-practice snapshot of all supported station rosters."""

    def __init__(self, station_readers=None):
        self.station_readers = (
            default_station_readers()
            if station_readers is None
            else station_readers
        )
        self.catalogs = {}
        self.errors = {}
        self.stations_by_key = {}
        self._load_catalogs()

    def _load_catalogs(self):
        """Load every roster once and build its stable-key lookup index."""
        for recommended_unit, (station_type, _) in STATION_TYPES.items():
            stations, error = self._load_catalog(
                recommended_unit,
                station_type,
            )
            self.catalogs[recommended_unit] = stations
            if error is not None:
                self.errors[recommended_unit] = error
            for station in stations:
                self.stations_by_key[station["resource_key"]] = station

    def _load_catalog(self, recommended_unit, station_type):
        """Read and normalize the located stations for one Planner unit type."""
        reader = self.station_readers.get(recommended_unit)
        if reader is None:
            return [], "station catalog reader is unavailable"
        try:
            return self._stations_from_geojson(
                reader(),
                recommended_unit,
                station_type,
            ), None
        except Exception as error:
            return [], str(error)

    @staticmethod
    def _stations_from_geojson(payload, recommended_unit, station_type):
        """Normalize one DB station catalog and ignore invalid rows."""
        if not isinstance(payload, dict) or not isinstance(
            payload.get("features"), list
        ):
            raise ValueError("station catalog must be a GeoJSON FeatureCollection")

        stations = []
        for feature in payload["features"]:
            if not isinstance(feature, dict):
                continue
            geometry = feature.get("geometry") or {}
            point_coordinates = geometry.get("coordinates") or []
            if geometry.get("type") != "Point" or len(point_coordinates) < 2:
                continue

            properties = feature.get("properties") or {}
            if not isinstance(properties, dict):
                continue
            try:
                station_key = resource_key(recommended_unit, properties)
            except ValueError:
                continue
            station = {
                **properties,
                "latitude": point_coordinates[1],
                "longitude": point_coordinates[0],
                "unit_type": station_type,
                "recommended_unit": recommended_unit,
                "resource_key": station_key,
            }
            try:
                coordinates(station)
            except ValueError:
                continue
            stations.append(station)

        return stations
