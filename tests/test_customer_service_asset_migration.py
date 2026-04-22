import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.db_migrations import migrate_customer_service_upload_assets


class CustomerServiceAssetMigrationTests(unittest.TestCase):
    def test_migrate_legacy_customer_service_assets_copies_file_and_updates_setting(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.db"
            legacy_dir = Path(temp_dir) / "legacy-customer-service"
            persistent_dir = Path(temp_dir) / "persistent-customer-service"

            legacy_dir.mkdir(parents=True, exist_ok=True)
            (legacy_dir / "qrcode.png").write_bytes(b"fake-image")

            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE settings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key TEXT UNIQUE NOT NULL,
                    value TEXT NOT NULL
                )
                """
            )
            cursor.execute(
                "INSERT INTO settings(key, value) VALUES (?, ?)",
                (
                    "customer_service_qr_code_url",
                    "/static/uploads/customer-service/qrcode.png"
                )
            )
            conn.commit()

            with patch(
                "app.utils.storage.get_legacy_customer_service_upload_dir",
                return_value=legacy_dir
            ), patch(
                "app.utils.storage.get_customer_service_upload_dir",
                return_value=persistent_dir
            ):
                migrations_applied = migrate_customer_service_upload_assets(cursor)
                conn.commit()

            stored_value = cursor.execute(
                "SELECT value FROM settings WHERE key = ?",
                ("customer_service_qr_code_url",)
            ).fetchone()[0]

            self.assertTrue((persistent_dir / "qrcode.png").exists())
            self.assertEqual(stored_value, "/uploads/customer-service/qrcode.png")
            self.assertIn("customer_service_qr_code_url_persisted", migrations_applied)

            conn.close()


if __name__ == "__main__":
    unittest.main()
