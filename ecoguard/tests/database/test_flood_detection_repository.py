from sqlalchemy.dialects import postgresql

from ecoguard.collection.flood.hydrology_static import (
    INSERT_STREAM_NETWORK_EDGES,
    INSERT_STREAM_NETWORK_NODES,
    STREAM_NETWORK_CHECKSUM,
    UPSERT_STREAM_NETWORK_METADATA,
)
from ecoguard.database.repositories.flood_detection import (
    HYDROMETRIC_STATION_HISTORIES,
    LATEST_COLLECTOR_RUNS,
    STREAM_NETWORK,
)


def test_stream_candidates_are_limited_to_the_station_basin_and_radius():
    sql = str(
        HYDROMETRIC_STATION_HISTORIES.compile(
            dialect=postgresql.dialect()
        )
    )

    assert "ST_Intersects(stream.geometry, basin.basin_geometry)" in sql
    assert "ST_DWithin(" in sql
    assert "stream.geometry::geography" in sql
    assert "stream_candidate_radius_m" in sql
    assert "stream_candidate_limit" in sql


def test_stream_candidate_payload_contains_routing_identifiers():
    sql = str(
        HYDROMETRIC_STATION_HISTORIES.compile(
            dialect=postgresql.dialect()
        )
    )

    for field in (
        "water_source_id",
        "draining_water_id",
        "draining_water_name",
        "distance_m",
    ):
        assert f"'{field}'" in sql


def test_hydrometric_histories_are_bounded_by_as_of():
    sql = str(
        HYDROMETRIC_STATION_HISTORIES.compile(
            dialect=postgresql.dialect()
        )
    )

    assert sql.count("FROM hydrometric_observations AS observation") == 2
    assert sql.count("FROM rainfall_observations AS observation") == 2
    assert sql.count("observation.observed_at <=") == 4
    assert "observation.observed_at >=" in sql


def test_station_scope_keeps_active_stations_without_observations():
    sql = str(
        HYDROMETRIC_STATION_HISTORIES.compile(
            dialect=postgresql.dialect()
        )
    )

    assert "station_scope AS" in sql
    assert "WHERE station.is_active" in sql
    assert "UNION" in sql
    assert "WHERE latest.observed_at >=" in sql
    assert "FROM station_scope AS scope" in sql
    assert "LEFT JOIN latest_observation AS latest" in sql


def test_stream_network_query_loads_the_precomputed_topology():
    sql = str(STREAM_NETWORK.compile(dialect=postgresql.dialect()))

    assert "FROM stream_network_nodes AS node" in sql
    assert "LEFT JOIN stream_network_edges AS edge" in sql
    assert "edge.downstream_water_source_id AS draining_water_id" in sql
    assert "node.topology_conflict" in sql
    assert "ST_PointOnSurface" not in sql
    assert "ST_StartPoint" not in sql
    assert "ST_EndPoint" not in sql


def test_topology_rebuild_preserves_provider_direction_and_conflicts():
    nodes_sql = str(
        INSERT_STREAM_NETWORK_NODES.compile(
            dialect=postgresql.dialect()
        )
    )
    edges_sql = str(
        INSERT_STREAM_NETWORK_EDGES.compile(
            dialect=postgresql.dialect()
        )
    )

    assert "count(DISTINCT stream.draining_water_id)" in nodes_sql
    assert "bool_or(stream.draining_water_id IS NULL)" in nodes_sql
    assert "ST_PointOnSurface(ST_Collect(stream.geometry))" in nodes_sql
    assert "stream.water_source_id" in edges_sql
    assert "stream.draining_water_id" in edges_sql
    assert "ST_StartPoint" not in edges_sql
    assert "ST_EndPoint" not in edges_sql


def test_topology_metadata_tracks_the_source_checksum_and_counts():
    metadata_sql = str(
        UPSERT_STREAM_NETWORK_METADATA.compile(
            dialect=postgresql.dialect()
        )
    )
    checksum_sql = str(
        STREAM_NETWORK_CHECKSUM.compile(
            dialect=postgresql.dialect()
        )
    )

    assert "source_content_sha256" in metadata_sql
    assert "FROM stream_network_nodes" in metadata_sql
    assert "FROM stream_network_edges" in metadata_sql
    assert "ON CONFLICT (singleton) DO UPDATE" in metadata_sql
    assert "FROM stream_network_metadata" in checksum_sql


def test_latest_collector_runs_are_selected_per_requested_source():
    sql = str(
        LATEST_COLLECTOR_RUNS.compile(dialect=postgresql.dialect())
    )

    assert "DISTINCT ON (run.source)" in sql
    assert "run.source IN (__[POSTCOMPILE_sources])" in sql
    assert "run.started_at DESC, run.id DESC" in sql
    assert "run.rows_written" in sql
    assert "run.error" in sql
