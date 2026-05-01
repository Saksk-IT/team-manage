"""
数据库自动迁移模块
在应用启动时自动检测并执行必要的数据库迁移
"""
import logging
import sqlite3
import shutil
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)


def get_db_path():
    """获取数据库文件路径"""
    from app.config import settings
    db_file = settings.database_url.split("///")[-1]
    return Path(db_file)


def column_exists(cursor, table_name, column_name):
    """检查表中是否存在指定列"""
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = [row[1] for row in cursor.fetchall()]
    return column_name in columns


def table_exists(cursor, table_name):
    """检查表是否存在"""
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,)
    )
    return cursor.fetchone() is not None


def _index_columns(cursor, index_name: str) -> list[str]:
    cursor.execute(f"PRAGMA index_info({index_name})")
    return [row[2] for row in cursor.fetchall()]


def migrate_warranty_email_entries_duplicate_emails(cursor) -> list[str]:
    """质保邮箱列表升级为订单列表：允许同一邮箱存在多条来源/订单。"""
    if not table_exists(cursor, "warranty_email_entries"):
        return []

    cursor.execute("PRAGMA index_list(warranty_email_entries)")
    unique_email_indexes = [
        row[1]
        for row in cursor.fetchall()
        if row[2] and _index_columns(cursor, row[1]) == ["email"]
    ]

    migrations: list[str] = []
    if unique_email_indexes:
        logger.info("重建 warranty_email_entries 表，移除 email 唯一约束")
        cursor.execute("PRAGMA foreign_keys=OFF")
        cursor.execute("""
            CREATE TABLE warranty_email_entries_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email VARCHAR(255) NOT NULL,
                remaining_claims INTEGER NOT NULL DEFAULT 0,
                expires_at DATETIME,
                source VARCHAR(20) NOT NULL DEFAULT 'auto_redeem',
                last_redeem_code VARCHAR(32),
                last_warranty_team_id INTEGER,
                created_at DATETIME,
                updated_at DATETIME,
                FOREIGN KEY(last_redeem_code) REFERENCES redemption_codes(code),
                FOREIGN KEY(last_warranty_team_id) REFERENCES teams(id)
            )
        """)
        cursor.execute("""
            INSERT INTO warranty_email_entries_new (
                id, email, remaining_claims, expires_at, source,
                last_redeem_code, last_warranty_team_id, created_at, updated_at
            )
            SELECT
                id,
                LOWER(TRIM(email)),
                COALESCE(remaining_claims, 0),
                expires_at,
                COALESCE(NULLIF(TRIM(source), ''), 'auto_redeem'),
                last_redeem_code,
                last_warranty_team_id,
                created_at,
                updated_at
            FROM warranty_email_entries
        """)
        cursor.execute("DROP TABLE warranty_email_entries")
        cursor.execute("ALTER TABLE warranty_email_entries_new RENAME TO warranty_email_entries")
        cursor.execute("PRAGMA foreign_keys=ON")
        migrations.append("warranty_email_entries.email_unique_removed")

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_warranty_email_entries_email
        ON warranty_email_entries (email)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_warranty_email_entries_expires_at
        ON warranty_email_entries (expires_at)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_warranty_email_entries_source
        ON warranty_email_entries (source)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_warranty_email_entries_email_code_source
        ON warranty_email_entries (email, last_redeem_code, source)
    """)

    return migrations


def migrate_customer_service_upload_assets(cursor) -> list[str]:
    """
    将旧版客服二维码图片迁移到持久化目录，并更新配置地址。
    """
    from app.services.settings import SettingsService
    from app.utils.storage import (
        LEGACY_CUSTOMER_SERVICE_UPLOAD_ROUTE_PREFIX,
        build_customer_service_upload_url,
        get_customer_service_upload_dir,
        get_legacy_customer_service_upload_dir,
    )

    if not table_exists(cursor, "settings"):
        return []

    legacy_dir = get_legacy_customer_service_upload_dir()
    persistent_dir = get_customer_service_upload_dir()
    persistent_dir.mkdir(parents=True, exist_ok=True)

    copied_count = 0
    if legacy_dir.exists():
        for source_path in legacy_dir.iterdir():
            if not source_path.is_file():
                continue

            target_path = persistent_dir / source_path.name
            if target_path.exists():
                continue

            shutil.copy2(source_path, target_path)
            copied_count += 1

    cursor.execute(
        "SELECT value FROM settings WHERE key = ?",
        (SettingsService.CUSTOMER_SERVICE_QR_CODE_URL_KEY,)
    )
    qr_code_row = cursor.fetchone()
    if not qr_code_row:
        return [f"customer_service_assets_copied:{copied_count}"] if copied_count else []

    qr_code_url = (qr_code_row[0] or "").strip()
    if not qr_code_url.startswith(LEGACY_CUSTOMER_SERVICE_UPLOAD_ROUTE_PREFIX):
        return [f"customer_service_assets_copied:{copied_count}"] if copied_count else []

    filename = qr_code_url[len(LEGACY_CUSTOMER_SERVICE_UPLOAD_ROUTE_PREFIX):].strip()
    if not filename:
        return [f"customer_service_assets_copied:{copied_count}"] if copied_count else []

    persistent_path = persistent_dir / Path(filename).name
    if not persistent_path.exists():
        return [f"customer_service_assets_copied:{copied_count}"] if copied_count else []

    normalized_url = build_customer_service_upload_url(persistent_path.name)
    if normalized_url == qr_code_url:
        return [f"customer_service_assets_copied:{copied_count}"] if copied_count else []

    cursor.execute(
        "UPDATE settings SET value = ? WHERE key = ?",
        (normalized_url, SettingsService.CUSTOMER_SERVICE_QR_CODE_URL_KEY)
    )

    migration_names = ["customer_service_qr_code_url_persisted"]
    if copied_count:
        migration_names.insert(0, f"customer_service_assets_copied:{copied_count}")
    return migration_names


def migrate_unified_team_pool(cursor) -> list[str]:
    """统一 Team 池：历史质保 Team 迁入控制台，兑换码解除 Team 绑定。"""
    migration_names: list[str] = []

    if table_exists(cursor, "teams"):
        cursor.execute("""
            UPDATE teams
            SET team_type = 'standard'
            WHERE team_type IS NULL
               OR TRIM(team_type) = ''
               OR team_type NOT IN ('standard', 'number_pool')
        """)
        if cursor.rowcount:
            migration_names.append(f"teams.team_type_unified:{cursor.rowcount}")

        cursor.execute("""
            UPDATE teams
            SET bound_code_type = 'standard',
                bound_code_warranty_days = NULL
            WHERE bound_code_type IS NULL
               OR TRIM(bound_code_type) = ''
               OR bound_code_type != 'standard'
               OR bound_code_warranty_days IS NOT NULL
        """)
        if cursor.rowcount:
            migration_names.append(f"teams.bound_code_metadata_cleared:{cursor.rowcount}")

    if table_exists(cursor, "redemption_codes") and column_exists(cursor, "redemption_codes", "bound_team_id"):
        cursor.execute("""
            UPDATE redemption_codes
            SET bound_team_id = NULL
            WHERE bound_team_id IS NOT NULL
        """)
        if cursor.rowcount:
            migration_names.append(f"redemption_codes.bound_team_id_cleared:{cursor.rowcount}")

    return migration_names


def run_auto_migration():
    """
    自动运行数据库迁移
    检测缺失的列并自动添加
    """
    db_path = get_db_path()
    
    if not db_path.exists():
        logger.info("数据库文件不存在，跳过迁移")
        return
    
    logger.info("开始检查数据库迁移...")
    
    try:
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        
        migrations_applied = []
        migrations_applied.extend(migrate_warranty_email_entries_duplicate_emails(cursor))
        
        # 检查并添加质保相关字段
        if not column_exists(cursor, "redemption_codes", "has_warranty"):
            logger.info("添加 redemption_codes.has_warranty 字段")
            cursor.execute("""
                ALTER TABLE redemption_codes 
                ADD COLUMN has_warranty BOOLEAN DEFAULT 0
            """)
            migrations_applied.append("redemption_codes.has_warranty")
        
        if not column_exists(cursor, "redemption_codes", "warranty_expires_at"):
            logger.info("添加 redemption_codes.warranty_expires_at 字段")
            cursor.execute("""
                ALTER TABLE redemption_codes 
                ADD COLUMN warranty_expires_at DATETIME
            """)
            migrations_applied.append("redemption_codes.warranty_expires_at")
        
        if not column_exists(cursor, "redemption_codes", "warranty_days"):
            logger.info("添加 redemption_codes.warranty_days 字段")
            cursor.execute("""
                ALTER TABLE redemption_codes 
                ADD COLUMN warranty_days INTEGER DEFAULT 30
            """)
            migrations_applied.append("redemption_codes.warranty_days")

        if not column_exists(cursor, "redemption_codes", "warranty_claims"):
            logger.info("添加 redemption_codes.warranty_claims 字段")
            cursor.execute("""
                ALTER TABLE redemption_codes
                ADD COLUMN warranty_claims INTEGER DEFAULT 10
            """)
            migrations_applied.append("redemption_codes.warranty_claims")

        if not column_exists(cursor, "redemption_codes", "warranty_seconds"):
            logger.info("添加 redemption_codes.warranty_seconds 字段")
            cursor.execute("""
                ALTER TABLE redemption_codes
                ADD COLUMN warranty_seconds INTEGER
            """)
            migrations_applied.append("redemption_codes.warranty_seconds")

        if not column_exists(cursor, "redemption_codes", "bound_team_id"):
            logger.info("添加 redemption_codes.bound_team_id 字段")
            cursor.execute("""
                ALTER TABLE redemption_codes
                ADD COLUMN bound_team_id INTEGER
            """)
            migrations_applied.append("redemption_codes.bound_team_id")
        
        if not column_exists(cursor, "redemption_records", "is_warranty_redemption"):
            logger.info("添加 redemption_records.is_warranty_redemption 字段")
            cursor.execute("""
                ALTER TABLE redemption_records 
                ADD COLUMN is_warranty_redemption BOOLEAN DEFAULT 0
            """)
            migrations_applied.append("redemption_records.is_warranty_redemption")

        if not column_exists(cursor, "redemption_records", "warranty_super_code_type"):
            logger.info("添加 redemption_records.warranty_super_code_type 字段")
            cursor.execute("""
                ALTER TABLE redemption_records
                ADD COLUMN warranty_super_code_type VARCHAR(20)
            """)
            migrations_applied.append("redemption_records.warranty_super_code_type")

        # 检查并添加 Token 刷新相关字段
        if not column_exists(cursor, "teams", "refresh_token_encrypted"):
            logger.info("添加 teams.refresh_token_encrypted 字段")
            cursor.execute("ALTER TABLE teams ADD COLUMN refresh_token_encrypted TEXT")
            migrations_applied.append("teams.refresh_token_encrypted")

        if not column_exists(cursor, "teams", "session_token_encrypted"):
            logger.info("添加 teams.session_token_encrypted 字段")
            cursor.execute("ALTER TABLE teams ADD COLUMN session_token_encrypted TEXT")
            migrations_applied.append("teams.session_token_encrypted")

        if not column_exists(cursor, "teams", "client_id"):
            logger.info("添加 teams.client_id 字段")
            cursor.execute("ALTER TABLE teams ADD COLUMN client_id VARCHAR(100)")
            migrations_applied.append("teams.client_id")

        if not column_exists(cursor, "teams", "team_type"):
            logger.info("添加 teams.team_type 字段")
            cursor.execute("ALTER TABLE teams ADD COLUMN team_type VARCHAR(20) DEFAULT 'standard'")
            migrations_applied.append("teams.team_type")

        cursor.execute("""
            UPDATE teams
            SET team_type = 'standard'
            WHERE team_type IS NULL OR TRIM(team_type) = ''
        """)

        if not column_exists(cursor, "teams", "bound_code_type"):
            logger.info("添加 teams.bound_code_type 字段")
            cursor.execute("ALTER TABLE teams ADD COLUMN bound_code_type VARCHAR(20) DEFAULT 'standard'")
            migrations_applied.append("teams.bound_code_type")

        cursor.execute("""
            UPDATE teams
            SET bound_code_type = 'standard'
            WHERE bound_code_type IS NULL OR TRIM(bound_code_type) = ''
        """)

        if not column_exists(cursor, "teams", "bound_code_warranty_days"):
            logger.info("添加 teams.bound_code_warranty_days 字段")
            cursor.execute("ALTER TABLE teams ADD COLUMN bound_code_warranty_days INTEGER")
            migrations_applied.append("teams.bound_code_warranty_days")

        if table_exists(cursor, "redemption_codes"):
            cursor.execute("""
                UPDATE teams
                SET bound_code_type = 'warranty'
                WHERE EXISTS (
                    SELECT 1
                    FROM redemption_codes
                    WHERE redemption_codes.bound_team_id = teams.id
                      AND COALESCE(redemption_codes.has_warranty, 0) = 1
                )
            """)
            cursor.execute("""
                UPDATE teams
                SET bound_code_warranty_days = (
                    SELECT MAX(redemption_codes.warranty_days)
                    FROM redemption_codes
                    WHERE redemption_codes.bound_team_id = teams.id
                      AND COALESCE(redemption_codes.has_warranty, 0) = 1
                      AND redemption_codes.warranty_days > 0
                )
                WHERE (bound_code_warranty_days IS NULL OR bound_code_warranty_days <= 0)
                  AND EXISTS (
                    SELECT 1
                    FROM redemption_codes
                    WHERE redemption_codes.bound_team_id = teams.id
                      AND COALESCE(redemption_codes.has_warranty, 0) = 1
                      AND redemption_codes.warranty_days > 0
                  )
            """)

        cursor.execute("""
            UPDATE teams
            SET bound_code_warranty_days = NULL
            WHERE bound_code_type != 'warranty'
        """)

        if not column_exists(cursor, "teams", "error_count"):
            logger.info("添加 teams.error_count 字段")
            cursor.execute("ALTER TABLE teams ADD COLUMN error_count INTEGER DEFAULT 0")
            migrations_applied.append("teams.error_count")

        if not column_exists(cursor, "teams", "account_role"):
            logger.info("添加 teams.account_role 字段")
            cursor.execute("ALTER TABLE teams ADD COLUMN account_role VARCHAR(50)")
            migrations_applied.append("teams.account_role")

        if not column_exists(cursor, "teams", "device_code_auth_enabled"):
            logger.info("添加 teams.device_code_auth_enabled 字段")
            cursor.execute("ALTER TABLE teams ADD COLUMN device_code_auth_enabled BOOLEAN DEFAULT 0")
            migrations_applied.append("teams.device_code_auth_enabled")

        if not column_exists(cursor, "teams", "warranty_unavailable"):
            logger.info("添加 teams.warranty_unavailable 字段")
            cursor.execute("ALTER TABLE teams ADD COLUMN warranty_unavailable BOOLEAN DEFAULT 0")
            migrations_applied.append("teams.warranty_unavailable")

        if not column_exists(cursor, "teams", "warranty_unavailable_reason"):
            logger.info("添加 teams.warranty_unavailable_reason 字段")
            cursor.execute("ALTER TABLE teams ADD COLUMN warranty_unavailable_reason TEXT")
            migrations_applied.append("teams.warranty_unavailable_reason")

        if not column_exists(cursor, "teams", "warranty_unavailable_at"):
            logger.info("添加 teams.warranty_unavailable_at 字段")
            cursor.execute("ALTER TABLE teams ADD COLUMN warranty_unavailable_at DATETIME")
            migrations_applied.append("teams.warranty_unavailable_at")

        if not column_exists(cursor, "teams", "import_status"):
            logger.info("添加 teams.import_status 字段")
            cursor.execute("ALTER TABLE teams ADD COLUMN import_status VARCHAR(20) DEFAULT 'classified' NOT NULL")
            migrations_applied.append("teams.import_status")

        if not column_exists(cursor, "teams", "imported_by_user_id"):
            logger.info("添加 teams.imported_by_user_id 字段")
            cursor.execute("ALTER TABLE teams ADD COLUMN imported_by_user_id INTEGER")
            migrations_applied.append("teams.imported_by_user_id")

        if not column_exists(cursor, "teams", "imported_by_username"):
            logger.info("添加 teams.imported_by_username 字段")
            cursor.execute("ALTER TABLE teams ADD COLUMN imported_by_username VARCHAR(100)")
            migrations_applied.append("teams.imported_by_username")

        if not column_exists(cursor, "teams", "import_tag"):
            logger.info("添加 teams.import_tag 字段")
            cursor.execute("ALTER TABLE teams ADD COLUMN import_tag VARCHAR(20)")
            migrations_applied.append("teams.import_tag")

        if not column_exists(cursor, "teams", "last_refresh_at"):
            logger.info("添加 teams.last_refresh_at 字段")
            cursor.execute("ALTER TABLE teams ADD COLUMN last_refresh_at DATETIME")
            cursor.execute("""
                UPDATE teams
                SET last_refresh_at = last_sync
                WHERE last_refresh_at IS NULL
                  AND last_sync IS NOT NULL
            """)
            migrations_applied.append("teams.last_refresh_at")

        if not column_exists(cursor, "teams", "reserved_members"):
            logger.info("添加 teams.reserved_members 字段")
            cursor.execute("ALTER TABLE teams ADD COLUMN reserved_members INTEGER DEFAULT 0 NOT NULL")
            migrations_applied.append("teams.reserved_members")

        cursor.execute("""
            UPDATE teams
            SET reserved_members = 0
            WHERE reserved_members IS NULL OR reserved_members < 0
        """)

        cursor.execute("""
            UPDATE teams
            SET import_status = 'classified'
            WHERE import_status IS NULL OR TRIM(import_status) = ''
        """)

        cursor.execute("CREATE INDEX IF NOT EXISTS idx_team_type ON teams (team_type)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_team_import_tag ON teams (import_tag)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_team_created_at ON teams (created_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_team_last_refresh_at ON teams (last_refresh_at)")

        if not table_exists(cursor, "admin_users"):
            logger.info("创建 admin_users 表")
            cursor.execute("""
                CREATE TABLE admin_users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username VARCHAR(100) NOT NULL UNIQUE,
                    password_hash VARCHAR(255) NOT NULL,
                    role VARCHAR(30) NOT NULL DEFAULT 'import_admin',
                    is_active BOOLEAN NOT NULL DEFAULT 1,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL
                )
            """)
            cursor.execute("""
                CREATE UNIQUE INDEX idx_admin_users_username
                ON admin_users (username)
            """)
            cursor.execute("""
                CREATE INDEX idx_admin_users_role
                ON admin_users (role)
            """)
            migrations_applied.append("admin_users")

        cursor.execute("""
            UPDATE teams
            SET warranty_unavailable = 0
            WHERE warranty_unavailable IS NULL
        """)

        if not table_exists(cursor, "team_member_snapshots"):
            logger.info("创建 team_member_snapshots 表")
            cursor.execute("""
                CREATE TABLE team_member_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    team_id INTEGER NOT NULL,
                    email VARCHAR(255) NOT NULL,
                    member_state VARCHAR(20) NOT NULL DEFAULT 'joined',
                    created_at DATETIME,
                    updated_at DATETIME,
                    FOREIGN KEY(team_id) REFERENCES teams(id) ON DELETE CASCADE
                )
            """)
            cursor.execute("""
                CREATE UNIQUE INDEX idx_team_member_snapshot_team_email
                ON team_member_snapshots (team_id, email)
            """)
            cursor.execute("""
                CREATE INDEX idx_team_member_snapshot_email
                ON team_member_snapshots (email)
            """)
            migrations_applied.append("team_member_snapshots")

        if not table_exists(cursor, "invite_jobs"):
            logger.info("创建 invite_jobs 表")
            cursor.execute("""
                CREATE TABLE invite_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_type VARCHAR(20) NOT NULL,
                    status VARCHAR(20) NOT NULL DEFAULT 'queued',
                    email VARCHAR(255) NOT NULL,
                    code VARCHAR(32),
                    team_id INTEGER,
                    idempotency_key VARCHAR(255) NOT NULL,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL DEFAULT 5,
                    reservation_released BOOLEAN NOT NULL DEFAULT 0,
                    error TEXT,
                    result_payload TEXT,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL,
                    started_at DATETIME,
                    completed_at DATETIME,
                    FOREIGN KEY(team_id) REFERENCES teams(id)
                )
            """)
            cursor.execute("""
                CREATE INDEX idx_invite_jobs_status_created_at
                ON invite_jobs (status, created_at)
            """)
            cursor.execute("""
                CREATE INDEX idx_invite_jobs_type_email
                ON invite_jobs (job_type, email)
            """)
            cursor.execute("""
                CREATE INDEX idx_invite_jobs_code
                ON invite_jobs (code)
            """)
            cursor.execute("""
                CREATE INDEX idx_invite_jobs_team_status
                ON invite_jobs (team_id, status)
            """)
            cursor.execute("""
                CREATE INDEX idx_invite_jobs_idempotency
                ON invite_jobs (idempotency_key)
            """)
            migrations_applied.append("invite_jobs")

        if table_exists(cursor, "invite_jobs") and not column_exists(cursor, "invite_jobs", "warranty_entry_id"):
            logger.info("添加 invite_jobs.warranty_entry_id 字段")
            cursor.execute("ALTER TABLE invite_jobs ADD COLUMN warranty_entry_id INTEGER")
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_invite_jobs_warranty_entry
                ON invite_jobs (warranty_entry_id)
            """)
            migrations_applied.append("invite_jobs.warranty_entry_id")

        if not table_exists(cursor, "warranty_team_whitelist_entries"):
            logger.info("创建邮箱白名单表 warranty_team_whitelist_entries")
            cursor.execute("""
                CREATE TABLE warranty_team_whitelist_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email VARCHAR(255) NOT NULL UNIQUE,
                    source VARCHAR(30) NOT NULL DEFAULT 'manual',
                    is_active BOOLEAN NOT NULL DEFAULT 1,
                    note TEXT,
                    last_warranty_team_id INTEGER,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL,
                    FOREIGN KEY(last_warranty_team_id) REFERENCES teams(id)
                )
            """)
            cursor.execute("""
                CREATE UNIQUE INDEX idx_warranty_team_whitelist_email
                ON warranty_team_whitelist_entries (email)
            """)
            cursor.execute("""
                CREATE INDEX idx_warranty_team_whitelist_source
                ON warranty_team_whitelist_entries (source)
            """)
            cursor.execute("""
                CREATE INDEX idx_warranty_team_whitelist_active
                ON warranty_team_whitelist_entries (is_active)
            """)
            migrations_applied.append("warranty_team_whitelist_entries")

        cursor.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_warranty_team_whitelist_email
            ON warranty_team_whitelist_entries (email)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_warranty_team_whitelist_source
            ON warranty_team_whitelist_entries (source)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_warranty_team_whitelist_active
            ON warranty_team_whitelist_entries (is_active)
        """)

        if table_exists(cursor, "redemption_codes"):
            cursor.execute("""
                INSERT OR IGNORE INTO warranty_team_whitelist_entries (
                    email, source, is_active, note, last_warranty_team_id, created_at, updated_at
                )
                SELECT
                    LOWER(TRIM(used_by_email)),
                    'console_team',
                    1,
                    '自动同步自控制台 Team 兑换绑定邮箱',
                    used_team_id,
                    CURRENT_TIMESTAMP,
                    CURRENT_TIMESTAMP
                FROM redemption_codes
                WHERE used_by_email IS NOT NULL
                  AND TRIM(used_by_email) != ''
                  AND bound_team_id IS NOT NULL
                  AND used_team_id = bound_team_id
            """)

        if table_exists(cursor, "redemption_records"):
            cursor.execute("""
                INSERT OR IGNORE INTO warranty_team_whitelist_entries (
                    email, source, is_active, note, last_warranty_team_id, created_at, updated_at
                )
                SELECT
                    LOWER(TRIM(email)),
                    'console_team',
                    1,
                    '自动同步自控制台 Team 兑换绑定邮箱',
                    team_id,
                    CURRENT_TIMESTAMP,
                    CURRENT_TIMESTAMP
                FROM redemption_records
                WHERE email IS NOT NULL
                  AND TRIM(email) != ''
                  AND team_id IS NOT NULL
            """)

        if table_exists(cursor, "warranty_email_entries"):
            cursor.execute("""
                INSERT OR IGNORE INTO warranty_team_whitelist_entries (
                    email, source, is_active, note, last_warranty_team_id, created_at, updated_at
                )
                SELECT
                    LOWER(TRIM(email)),
                    'warranty_email',
                    1,
                    '自动同步自质保邮箱列表',
                    last_warranty_team_id,
                    CURRENT_TIMESTAMP,
                    CURRENT_TIMESTAMP
                FROM warranty_email_entries
                WHERE email IS NOT NULL
                  AND TRIM(email) != ''
                  AND COALESCE(remaining_claims, 0) > 0
                  AND expires_at IS NOT NULL
                  AND expires_at > CURRENT_TIMESTAMP
            """)
            cursor.execute("""
                INSERT OR IGNORE INTO warranty_team_whitelist_entries (
                    email, source, is_active, note, last_warranty_team_id, created_at, updated_at
                )
                SELECT
                    LOWER(TRIM(email)),
                    'manual_pull',
                    1,
                    '从历史手动拉入记录补写',
                    last_warranty_team_id,
                    CURRENT_TIMESTAMP,
                    CURRENT_TIMESTAMP
                FROM warranty_email_entries
                WHERE email IS NOT NULL
                  AND TRIM(email) != ''
                  AND COALESCE(source, '') = 'manual'
                  AND COALESCE(remaining_claims, 0) <= 0
                  AND expires_at IS NULL
                  AND last_warranty_team_id IS NOT NULL
            """)

        if not table_exists(cursor, "warranty_email_template_locks"):
            logger.info("创建 warranty_email_template_locks 表")
            cursor.execute("""
                CREATE TABLE warranty_email_template_locks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email VARCHAR(255) NOT NULL UNIQUE,
                    matched BOOLEAN NOT NULL DEFAULT 0,
                    template_key VARCHAR(100) NOT NULL,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL
                )
            """)
            cursor.execute("""
                CREATE UNIQUE INDEX idx_warranty_email_template_locks_email
                ON warranty_email_template_locks (email)
            """)
            cursor.execute("""
                CREATE INDEX idx_warranty_email_template_locks_matched
                ON warranty_email_template_locks (matched)
            """)
            migrations_applied.append("warranty_email_template_locks")

        cursor.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_warranty_email_template_locks_email
            ON warranty_email_template_locks (email)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_warranty_email_template_locks_matched
            ON warranty_email_template_locks (matched)
        """)

        migrations_applied.extend(migrate_unified_team_pool(cursor))

        if not table_exists(cursor, "warranty_claim_records"):
            logger.info("创建 warranty_claim_records 表")
            cursor.execute("""
                CREATE TABLE warranty_claim_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email VARCHAR(255) NOT NULL,
                    before_team_id INTEGER,
                    before_team_name VARCHAR(255),
                    before_team_email VARCHAR(255),
                    before_team_account_id VARCHAR(100),
                    before_team_status VARCHAR(20),
                    before_team_recorded_at DATETIME,
                    claim_status VARCHAR(20) NOT NULL,
                    failure_reason TEXT,
                    after_team_id INTEGER,
                    after_team_name VARCHAR(255),
                    after_team_email VARCHAR(255),
                    after_team_account_id VARCHAR(100),
                    after_team_recorded_at DATETIME,
                    submitted_at DATETIME NOT NULL,
                    completed_at DATETIME,
                    FOREIGN KEY(before_team_id) REFERENCES teams(id),
                    FOREIGN KEY(after_team_id) REFERENCES teams(id)
                )
            """)
            cursor.execute("""
                CREATE INDEX idx_warranty_claim_records_email
                ON warranty_claim_records (email)
            """)
            cursor.execute("""
                CREATE INDEX idx_warranty_claim_records_status
                ON warranty_claim_records (claim_status)
            """)
            cursor.execute("""
                CREATE INDEX idx_warranty_claim_records_submitted_at
                ON warranty_claim_records (submitted_at)
            """)
            migrations_applied.append("warranty_claim_records")

        if not table_exists(cursor, "team_cleanup_records"):
            logger.info("创建 team_cleanup_records 表")
            cursor.execute("""
                CREATE TABLE team_cleanup_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    team_id INTEGER,
                    team_email VARCHAR(255) NOT NULL,
                    team_name VARCHAR(255),
                    team_account_id VARCHAR(100),
                    cleanup_source VARCHAR(40) NOT NULL DEFAULT 'team_refresh',
                    cleanup_reason TEXT,
                    cleanup_status VARCHAR(20) NOT NULL DEFAULT 'success',
                    removed_member_count INTEGER NOT NULL DEFAULT 0,
                    revoked_invite_count INTEGER NOT NULL DEFAULT 0,
                    whitelist_deactivated_count INTEGER NOT NULL DEFAULT 0,
                    failed_count INTEGER NOT NULL DEFAULT 0,
                    removed_member_emails TEXT,
                    revoked_invite_emails TEXT,
                    whitelist_deactivated_emails TEXT,
                    failed_items TEXT,
                    created_at DATETIME NOT NULL,
                    FOREIGN KEY(team_id) REFERENCES teams(id)
                )
            """)
            cursor.execute("""
                CREATE INDEX idx_team_cleanup_records_team_id
                ON team_cleanup_records (team_id)
            """)
            cursor.execute("""
                CREATE INDEX idx_team_cleanup_records_source
                ON team_cleanup_records (cleanup_source)
            """)
            cursor.execute("""
                CREATE INDEX idx_team_cleanup_records_status
                ON team_cleanup_records (cleanup_status)
            """)
            cursor.execute("""
                CREATE INDEX idx_team_cleanup_records_created_at
                ON team_cleanup_records (created_at)
            """)
            migrations_applied.append("team_cleanup_records")

        if table_exists(cursor, "team_cleanup_records"):
            if not column_exists(cursor, "team_cleanup_records", "cleanup_source"):
                logger.info("添加 team_cleanup_records.cleanup_source 字段")
                cursor.execute("""
                    ALTER TABLE team_cleanup_records
                    ADD COLUMN cleanup_source VARCHAR(40) NOT NULL DEFAULT 'team_refresh'
                """)
                migrations_applied.append("team_cleanup_records.cleanup_source")

            if not column_exists(cursor, "team_cleanup_records", "cleanup_reason"):
                logger.info("添加 team_cleanup_records.cleanup_reason 字段")
                cursor.execute("""
                    ALTER TABLE team_cleanup_records
                    ADD COLUMN cleanup_reason TEXT
                """)
                migrations_applied.append("team_cleanup_records.cleanup_reason")

            if not column_exists(cursor, "team_cleanup_records", "whitelist_deactivated_count"):
                logger.info("添加 team_cleanup_records.whitelist_deactivated_count 字段")
                cursor.execute("""
                    ALTER TABLE team_cleanup_records
                    ADD COLUMN whitelist_deactivated_count INTEGER NOT NULL DEFAULT 0
                """)
                migrations_applied.append("team_cleanup_records.whitelist_deactivated_count")

            if not column_exists(cursor, "team_cleanup_records", "whitelist_deactivated_emails"):
                logger.info("添加 team_cleanup_records.whitelist_deactivated_emails 字段")
                cursor.execute("""
                    ALTER TABLE team_cleanup_records
                    ADD COLUMN whitelist_deactivated_emails TEXT
                """)
                migrations_applied.append("team_cleanup_records.whitelist_deactivated_emails")

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_team_cleanup_records_source
                ON team_cleanup_records (cleanup_source)
            """)

        if not table_exists(cursor, "team_refresh_records"):
            logger.info("创建 team_refresh_records 表")
            cursor.execute("""
                CREATE TABLE team_refresh_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    team_id INTEGER,
                    team_email VARCHAR(255) NOT NULL,
                    team_name VARCHAR(255),
                    team_account_id VARCHAR(100),
                    source VARCHAR(30) NOT NULL DEFAULT 'unknown',
                    refresh_status VARCHAR(20) NOT NULL DEFAULT 'success',
                    force_refresh BOOLEAN NOT NULL DEFAULT 0,
                    team_status VARCHAR(20),
                    current_members INTEGER,
                    max_members INTEGER,
                    message TEXT,
                    error TEXT,
                    error_code VARCHAR(100),
                    cleanup_record_id INTEGER,
                    cleanup_removed_member_count INTEGER NOT NULL DEFAULT 0,
                    cleanup_revoked_invite_count INTEGER NOT NULL DEFAULT 0,
                    cleanup_failed_count INTEGER NOT NULL DEFAULT 0,
                    created_at DATETIME NOT NULL,
                    FOREIGN KEY(team_id) REFERENCES teams(id),
                    FOREIGN KEY(cleanup_record_id) REFERENCES team_cleanup_records(id)
                )
            """)
            cursor.execute("""
                CREATE INDEX idx_team_refresh_records_team_id
                ON team_refresh_records (team_id)
            """)
            cursor.execute("""
                CREATE INDEX idx_team_refresh_records_source
                ON team_refresh_records (source)
            """)
            cursor.execute("""
                CREATE INDEX idx_team_refresh_records_status
                ON team_refresh_records (refresh_status)
            """)
            cursor.execute("""
                CREATE INDEX idx_team_refresh_records_team_status
                ON team_refresh_records (team_status)
            """)
            cursor.execute("""
                CREATE INDEX idx_team_refresh_records_cleanup_record_id
                ON team_refresh_records (cleanup_record_id)
            """)
            cursor.execute("""
                CREATE INDEX idx_team_refresh_records_created_at
                ON team_refresh_records (created_at)
            """)
            migrations_applied.append("team_refresh_records")

        migrations_applied.extend(migrate_customer_service_upload_assets(cursor))
        
        # 提交更改
        conn.commit()
        
        if migrations_applied:
            logger.info(f"数据库迁移完成，应用了 {len(migrations_applied)} 个迁移: {', '.join(migrations_applied)}")
        else:
            logger.info("数据库已是最新版本，无需迁移")
        
        conn.close()
        
    except Exception as e:
        logger.error(f"数据库迁移失败: {e}")
        raise


if __name__ == "__main__":
    # 允许直接运行此脚本进行迁移
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    run_auto_migration()
    print("迁移完成")
