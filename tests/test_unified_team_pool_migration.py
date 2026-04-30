import sqlite3

from app.db_migrations import migrate_unified_team_pool


def test_migrate_unified_team_pool_normalizes_legacy_team_and_unbinds_codes():
    conn = sqlite3.connect(":memory:")
    try:
        cursor = conn.cursor()
        cursor.executescript(
            """
            CREATE TABLE teams (
                id INTEGER PRIMARY KEY,
                team_type VARCHAR(20),
                bound_code_type VARCHAR(20),
                bound_code_warranty_days INTEGER
            );
            CREATE TABLE redemption_codes (
                id INTEGER PRIMARY KEY,
                code VARCHAR(100),
                bound_team_id INTEGER
            );
            INSERT INTO teams (id, team_type, bound_code_type, bound_code_warranty_days)
            VALUES (1, 'warranty', 'warranty', 45), (2, 'standard', 'standard', NULL), (3, 'number_pool', 'standard', NULL);
            INSERT INTO redemption_codes (id, code, bound_team_id)
            VALUES (1, 'LEGACY-BOUND', 1), (2, 'PLAIN', NULL);
            """
        )

        migrations = migrate_unified_team_pool(cursor)

        teams = cursor.execute(
            "SELECT id, team_type, bound_code_type, bound_code_warranty_days FROM teams ORDER BY id"
        ).fetchall()
        codes = cursor.execute(
            "SELECT code, bound_team_id FROM redemption_codes ORDER BY id"
        ).fetchall()

        assert any(item.startswith("teams.team_type_unified") for item in migrations)
        assert any(item.startswith("teams.bound_code_metadata_cleared") for item in migrations)
        assert any(item.startswith("redemption_codes.bound_team_id_cleared") for item in migrations)
        assert teams == [(1, "standard", "standard", None), (2, "standard", "standard", None), (3, "number_pool", "standard", None)]
        assert codes == [("LEGACY-BOUND", None), ("PLAIN", None)]
    finally:
        conn.close()
