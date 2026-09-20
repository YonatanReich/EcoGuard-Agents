"""firms_baselines gains a per-cell detection signature, so a persistent cell is not blind

Revision ID: firms_signatures
Revises: event_projections_towns_merge

Non-numeric identifier for the same reason as the ones before it: sibling
branches claim numeric ids and alembic resolves stored revisions by prefix.

Attached to the existing merge head rather than to `resource_allocations`, so
the repository keeps the two heads it already had rather than gaining a third.
"""

from alembic import op

revision = "firms_signatures"
down_revision = "event_projections_towns_merge"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # `detection_days / days_observed` answers "does this cell light up often?"
    # It cannot answer "is this particular detection the thing it normally
    # does?", and that second question is the one that decides whether a fire
    # in an industrial cell is ever reported.
    #
    # Measured over a full year: 1,157 of 1,174 cells light on under 5% of
    # days, and the 17 that do not are suppressed permanently. The worst lights
    # on 71% of them. Without these columns a wildfire in that cell can never
    # reach the queue, which is the failure repositories/fire_history.py
    # already warns about and had no way to fix.
    #
    # Nullable throughout, because a cell with too few overpasses has no
    # profile and must stay distinguishable from one whose profile says it is
    # quiet. "Not enough history to judge" and "judged and unremarkable" are
    # different facts and a zero would collapse them.
    #
    # These are fitted by scripts/build_firms_baselines.py from the same year
    # of pixels it already downloads to count days, so they cost no extra
    # request. See detectors/fire/signature.py for what each one means.
    op.execute(
        """
        ALTER TABLE firms_baselines
          ADD COLUMN IF NOT EXISTS signature_samples    integer,
          ADD COLUMN IF NOT EXISTS hour_mean            real,
          ADD COLUMN IF NOT EXISTS hour_concentration   real,
          ADD COLUMN IF NOT EXISTS log_frp_mean         real,
          ADD COLUMN IF NOT EXISTS log_frp_sd           real,
          ADD COLUMN IF NOT EXISTS pixels_mean          real,
          ADD COLUMN IF NOT EXISTS pixels_sd            real,
          ADD COLUMN IF NOT EXISTS scatter_mean_m       real,
          ADD COLUMN IF NOT EXISTS scatter_sd_m         real
        """
    )
    # A fitted spread of zero would make every reading infinitely surprising,
    # so the fitter floors them. Asserting it here as well keeps a hand-written
    # row or a future fitter from reintroducing the division by zero.
    op.execute(
        """
        ALTER TABLE firms_baselines
          DROP CONSTRAINT IF EXISTS firms_baselines_signature_sane,
          ADD CONSTRAINT firms_baselines_signature_sane
          CHECK (
            signature_samples IS NULL
            OR (signature_samples > 0
                AND hour_concentration BETWEEN 0 AND 1
                AND log_frp_sd > 0 AND pixels_sd > 0 AND scatter_sd_m > 0)
          )
        """
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE firms_baselines "
        "DROP CONSTRAINT IF EXISTS firms_baselines_signature_sane"
    )
    op.execute(
        """
        ALTER TABLE firms_baselines
          DROP COLUMN IF EXISTS signature_samples,
          DROP COLUMN IF EXISTS hour_mean,
          DROP COLUMN IF EXISTS hour_concentration,
          DROP COLUMN IF EXISTS log_frp_mean,
          DROP COLUMN IF EXISTS log_frp_sd,
          DROP COLUMN IF EXISTS pixels_mean,
          DROP COLUMN IF EXISTS pixels_sd,
          DROP COLUMN IF EXISTS scatter_mean_m,
          DROP COLUMN IF EXISTS scatter_sd_m
        """
    )
