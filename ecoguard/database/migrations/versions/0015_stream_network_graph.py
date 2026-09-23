"""Materialized topology derived from the Water Authority stream layer.

Revision ID: stream_network_graph
Revises: hydrology_observations
Create Date: 2026-09-15
"""

from alembic import op


revision = "stream_network_graph"
down_revision = "hydrology_observations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add materialized topology derived from the Water Authority stream layer."""
    op.execute(
        """
        CREATE TABLE stream_network_metadata (
          singleton             boolean PRIMARY KEY DEFAULT true,
          source_content_sha256 text        NOT NULL,
          source_feature_count  integer     NOT NULL,
          node_count            integer     NOT NULL,
          edge_count            integer     NOT NULL,
          built_at              timestamptz NOT NULL,
          CONSTRAINT stream_network_metadata_single_row CHECK (singleton),
          CONSTRAINT stream_network_metadata_nonnegative_counts CHECK (
            source_feature_count >= 0
            AND node_count >= 0
            AND edge_count >= 0
          )
        )
        """
    )
    op.execute(
        """
        CREATE TABLE stream_network_nodes (
          water_source_id       bigint PRIMARY KEY,
          name_he               text,
          object_ids            integer[]   NOT NULL,
          feature_count         integer     NOT NULL,
          main_catchment_code   text,
          main_catchment_name   text,
          representative_location geometry(Point, 4326),
          topology_conflict     boolean     NOT NULL,
          CONSTRAINT stream_network_nodes_has_features
            CHECK (feature_count > 0 AND cardinality(object_ids) > 0)
        )
        """
    )
    op.execute(
        "CREATE INDEX stream_network_nodes_location_idx "
        "ON stream_network_nodes USING GIST (representative_location)"
    )
    op.execute(
        "CREATE INDEX stream_network_nodes_catchment_idx "
        "ON stream_network_nodes (main_catchment_code)"
    )

    # The downstream id intentionally has no FK. A provider-declared target can
    # be absent from the current file, and retaining that edge lets detection
    # report an incomplete route rather than silently treating it as an outlet.
    op.execute(
        """
        CREATE TABLE stream_network_edges (
          upstream_water_source_id   bigint      NOT NULL
            REFERENCES stream_network_nodes(water_source_id)
            ON DELETE CASCADE,
          downstream_water_source_id bigint      NOT NULL,
          downstream_water_name      text,
          source_feature_count       integer     NOT NULL,
          CONSTRAINT stream_network_edges_identity
            PRIMARY KEY (
              upstream_water_source_id,
              downstream_water_source_id
            ),
          CONSTRAINT stream_network_edges_has_features
            CHECK (source_feature_count > 0)
        )
        """
    )
    op.execute(
        "CREATE INDEX stream_network_edges_downstream_idx "
        "ON stream_network_edges (downstream_water_source_id)"
    )


def downgrade() -> None:
    """Remove materialized topology derived from the Water Authority stream layer."""
    op.execute("DROP TABLE IF EXISTS stream_network_edges")
    op.execute("DROP TABLE IF EXISTS stream_network_nodes")
    op.execute("DROP TABLE IF EXISTS stream_network_metadata")
