"""003_sessions_device_id_not_null

Upgrade path for databases that already ran the old 001 (nullable device_id + SET NULL FK).

Steps:
  1. Check for sessions with device_id IS NULL
  2. Backfill: find virtual_phone_mic device per user and assign
  3. If any session can't be backfilled (no virtual_phone_mic), fail with clear error
  4. ALTER COLUMN device_id SET NOT NULL
  5. Drop old FK (ON DELETE SET NULL) → recreate FK (ON DELETE RESTRICT)

For fresh installs: 001 already creates device_id NOT NULL + RESTRICT, this migration
is a no-op for the column (just skips the ALTER if already NOT NULL).
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Step 1: Find sessions with NULL device_id ────────────────────
    conn = op.get_bind()

    null_count = conn.execute(
        sa.text("SELECT count(*) FROM sessions WHERE device_id IS NULL")
    ).scalar()

    if null_count > 0:
        print(f"\n⚠️  Found {null_count} session(s) with device_id IS NULL — attempting backfill...")

        # ── Step 2a: Backfill via virtual_phone_mic ──────────────────
        # virtual_phone_mic device_key = 'virtual-{user_id}'
        backfilled = conn.execute(
            sa.text("""
                UPDATE sessions s
                SET device_id = d.id
                FROM devices d
                WHERE s.device_id IS NULL
                  AND s.user_id = d.user_id
                  AND d.device_key = 'virtual-' || s.user_id::text
            """)
        ).rowcount
        print(f"   ✅ Backfilled {backfilled} session(s) using virtual_phone_mic")

        # ── Step 2b: Check remaining NULLs ───────────────────────────
        remaining = conn.execute(
            sa.text("SELECT count(*) FROM sessions WHERE device_id IS NULL")
        ).scalar()

        if remaining > 0:
            # Show details for manual fix
            rows = conn.execute(
                sa.text("""
                    SELECT s.id, s.user_id, s.title, s.created_at
                    FROM sessions s
                    WHERE s.device_id IS NULL
                    ORDER BY s.created_at
                """)
            ).fetchall()
            detail = "\n".join(
                f"   session={r[0]} user={r[1]} title={r[2]} created={r[3]}" for r in rows
            )
            raise RuntimeError(
                f"Cannot backfill {remaining} session(s) with device_id IS NULL. "
                f"No virtual_phone_mic device found for these users.\n\n"
                f"Affected sessions:\n{detail}\n\n"
                f"Manual fix needed:\n"
                f"  1. Find the user and check if virtual_phone_mic device exists\n"
                f"  2. If not, register the user again or create a device manually\n"
                f"  3. Re-run this migration\n"
            )

    # ── Step 3: ALTER COLUMN SET NOT NULL ────────────────────────────
    # Check if already NOT NULL (fresh install from fixed 001)
    col_info = conn.execute(
        sa.text("""
            SELECT is_nullable
            FROM information_schema.columns
            WHERE table_name = 'sessions' AND column_name = 'device_id'
        """)
    ).scalar()

    if col_info == "YES":
        op.alter_column("sessions", "device_id", nullable=False)
        print("   ✅ device_id SET NOT NULL")
    else:
        print("   ℹ️  device_id already NOT NULL (fresh install), skipping ALTER")

    # ── Step 4: Fix FK ondelete ──────────────────────────────────────
    # Drop the old FK (SET NULL) and recreate with RESTRICT
    # The FK constraint name follows Alembic naming convention
    fk_name = conn.execute(
        sa.text("""
            SELECT conname
            FROM pg_constraint
            WHERE conrelid = 'sessions'::regclass
              AND conname LIKE '%device_id%'
              AND contype = 'f'
        """)
    ).scalar()

    if fk_name:
        op.drop_constraint(fk_name, "sessions", type_="foreignkey")
        op.create_foreign_key(
            fk_name,
            "sessions", "devices",
            ["device_id"], ["id"],
            ondelete="RESTRICT",
        )
        print(f"   ✅ FK {fk_name} recreated with ON DELETE RESTRICT")
    else:
        print("   ℹ️  No FK found (already RESTRICT?), skipping")


def downgrade() -> None:
    # Not reversible — data integrity improvement
    pass
