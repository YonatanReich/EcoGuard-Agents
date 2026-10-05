"""Isfiya answers to its own local council, not to "no jurisdiction"

Revision ID: isfiya_local_council
Revises: incident_flood_merge
Create Date: 2026-10-04

The seed matched Isfiya to the unincorporated Mount Carmel polygon
("ללא שיפוט - אזור הר הכרמל"), probably from boundaries drawn before the
2008 split that dissolved Carmel City back into Isfiya and Daliyat al-Karmel.
Found by the historical fire demo: Isfiya was the ignition site of the 2010
Carmel fire, and the plan's evacuation line for it named no one to call.

VERIFY BEFORE APPLYING. 04-8391678 comes from one directory listing (Dapei
Zahav / B144) and could not be confirmed from a second source; the seed's
previous number was 04-9122640. Kafr Yasif, Sawa and one more town carry the
same "ללא שיפוט" mismatch and are left for a separate, checked fix.
"""

from alembic import op

revision = "isfiya_local_council"
down_revision = "incident_flood_merge"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Point Isfiya at its local council."""
    op.execute(
        """
        UPDATE towns
        SET authority = 'עספיא',
            authority_type = 'מועצה מקומית',
            authority_phone = '04-8391678'
        WHERE town_id = 'isfiya'
        """
    )


def downgrade() -> None:
    """Restore the seed's values."""
    op.execute(
        """
        UPDATE towns
        SET authority = 'ללא שיפוט - אזור הר הכרמל',
            authority_type = 'ללא שיפוט',
            authority_phone = '04-9122640'
        WHERE town_id = 'isfiya'
        """
    )
