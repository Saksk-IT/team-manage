"""
数据库模型定义
定义所有数据库表的 SQLAlchemy 模型
"""
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
from app.utils.time_utils import get_now


class AdminUser(Base):
    """后台用户表（子管理员）"""
    __tablename__ = "admin_users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(100), unique=True, nullable=False, comment="登录用户名")
    password_hash = Column(String(255), nullable=False, comment="密码哈希")
    role = Column(String(30), nullable=False, default="import_admin", comment="角色: import_admin")
    is_active = Column(Boolean, nullable=False, default=True, comment="是否启用")
    created_at = Column(DateTime, default=get_now, nullable=False, comment="创建时间")
    updated_at = Column(DateTime, default=get_now, onupdate=get_now, nullable=False, comment="更新时间")

    __table_args__ = (
        Index("idx_admin_users_username", "username", unique=True),
        Index("idx_admin_users_role", "role"),
    )


class Team(Base):
    """Team 信息表"""
    __tablename__ = "teams"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(255), nullable=False, comment="Team 管理员邮箱")
    access_token_encrypted = Column(Text, nullable=False, comment="加密存储的 AT")
    refresh_token_encrypted = Column(Text, comment="加密存储的 RT")
    session_token_encrypted = Column(Text, comment="加密存储的 Session Token")
    client_id = Column(String(100), comment="OAuth Client ID")
    encryption_key_id = Column(String(50), comment="加密密钥 ID")
    account_id = Column(String(100), comment="当前使用的 account-id")
    team_type = Column(String(20), nullable=False, default="standard", comment="Team 类型: standard/number_pool")
    bound_code_type = Column(String(20), nullable=False, default="standard", comment="绑定兑换码类型: standard/warranty(历史兼容)")
    bound_code_warranty_days = Column(Integer, comment="绑定质保兑换码质保时长(天)")
    team_name = Column(String(255), comment="Team 名称")
    plan_type = Column(String(50), comment="计划类型")
    subscription_plan = Column(String(100), comment="订阅计划")
    expires_at = Column(DateTime, comment="订阅到期时间")
    current_members = Column(Integer, default=0, comment="当前成员数")
    reserved_members = Column(Integer, default=0, nullable=False, comment="已预占/排队中的成员席位数")
    max_members = Column(Integer, default=5, comment="最大成员数")
    status = Column(String(20), default="active", comment="状态: active/full/expired/error/banned")
    account_role = Column(String(50), comment="账号角色: account-owner/standard-user 等")
    device_code_auth_enabled = Column(Boolean, default=False, comment="是否开启设备代码身份验证")
    warranty_unavailable = Column(Boolean, default=False, nullable=False, comment="是否标记为质保不可用")
    warranty_unavailable_reason = Column(Text, comment="质保不可用原因")
    warranty_unavailable_at = Column(DateTime, comment="质保不可用标记时间")
    error_count = Column(Integer, default=0, comment="连续报错次数")
    last_sync = Column(DateTime, comment="最后同步时间")
    last_refresh_at = Column(DateTime, comment="最后任意渠道刷新时间")
    import_status = Column(String(20), nullable=False, default="classified", comment="导入状态: pending/classified")
    imported_by_user_id = Column(Integer, ForeignKey("admin_users.id"), comment="导入的子管理员 ID")
    imported_by_username = Column(String(100), comment="导入人用户名快照")
    import_tag = Column(String(20), comment="导入标签: other_paid/self_paid")
    created_at = Column(DateTime, default=get_now, comment="创建时间")

    # 关系
    team_accounts = relationship("TeamAccount", back_populates="team", cascade="all, delete-orphan")
    redemption_records = relationship("RedemptionRecord", back_populates="team", cascade="all, delete-orphan")

    # 索引
    __table_args__ = (
        Index("idx_status", "status"),
        Index("idx_team_type", "team_type"),
        Index("idx_team_import_status", "import_status"),
        Index("idx_team_imported_by_user_id", "imported_by_user_id"),
        Index("idx_team_import_tag", "import_tag"),
        Index("idx_team_created_at", "created_at"),
        Index("idx_team_last_refresh_at", "last_refresh_at"),
    )


class TeamAccount(Base):
    """Team Account 关联表"""
    __tablename__ = "team_accounts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    team_id = Column(Integer, ForeignKey("teams.id", ondelete="CASCADE"), nullable=False)
    account_id = Column(String(100), nullable=False, comment="Account ID")
    account_name = Column(String(255), comment="Account 名称")
    is_primary = Column(Boolean, default=False, comment="是否为主 Account")
    created_at = Column(DateTime, default=get_now, comment="创建时间")

    # 关系
    team = relationship("Team", back_populates="team_accounts")

    # 唯一约束
    __table_args__ = (
        Index("idx_team_account", "team_id", "account_id", unique=True),
    )


class TeamMemberSnapshot(Base):
    """Team 子账号成员快照表"""
    __tablename__ = "team_member_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    team_id = Column(Integer, ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, comment="Team ID")
    email = Column(String(255), nullable=False, comment="成员邮箱（统一小写）")
    member_state = Column(String(20), nullable=False, default="joined", comment="成员状态: joined/invited")
    created_at = Column(DateTime, default=get_now, comment="创建时间")
    updated_at = Column(DateTime, default=get_now, onupdate=get_now, comment="更新时间")

    __table_args__ = (
        Index("idx_team_member_snapshot_team_email", "team_id", "email", unique=True),
        Index("idx_team_member_snapshot_email", "email"),
    )


class RedemptionCode(Base):
    """兑换码表"""
    __tablename__ = "redemption_codes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(32), unique=True, nullable=False, comment="兑换码")
    status = Column(String(20), default="unused", comment="状态: unused/used/expired/warranty_active")
    created_at = Column(DateTime, default=get_now, comment="创建时间")
    expires_at = Column(DateTime, comment="过期时间")
    bound_team_id = Column(Integer, ForeignKey("teams.id"), comment="绑定的 Team ID")
    used_by_email = Column(String(255), comment="使用者邮箱")
    used_team_id = Column(Integer, ForeignKey("teams.id"), comment="使用的 Team ID")
    used_at = Column(DateTime, comment="使用时间")
    has_warranty = Column(Boolean, default=False, comment="是否为质保兑换码")
    warranty_days = Column(Integer, default=30, comment="质保时长(天)")
    warranty_claims = Column(Integer, default=10, comment="质保次数")
    warranty_expires_at = Column(DateTime, comment="质保到期时间(首次使用后根据质保时长计算)")

    # 关系
    redemption_records = relationship("RedemptionRecord", back_populates="redemption_code")

    # 索引
    __table_args__ = (
        Index("idx_code_status", "code", "status"),
    )


class RedemptionRecord(Base):
    """使用记录表"""
    __tablename__ = "redemption_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(255), nullable=False, comment="用户邮箱")
    code = Column(String(32), ForeignKey("redemption_codes.code"), nullable=False, comment="兑换码")
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=False, comment="Team ID")
    account_id = Column(String(100), nullable=False, comment="Account ID")
    redeemed_at = Column(DateTime, default=get_now, comment="兑换时间")
    is_warranty_redemption = Column(Boolean, default=False, comment="是否为质保兑换")
    warranty_super_code_type = Column(String(20), comment="触发质保的超级兑换码类型: usage_limit/time_limit")

    # 关系
    team = relationship("Team", back_populates="redemption_records")
    redemption_code = relationship("RedemptionCode", back_populates="redemption_records")

    # 索引
    __table_args__ = (
        Index("idx_email", "email"),
    )


class InviteJob(Base):
    """前台拉人队列表"""
    __tablename__ = "invite_jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_type = Column(String(20), nullable=False, comment="任务类型: redeem/warranty")
    status = Column(String(20), nullable=False, default="queued", comment="状态: queued/processing/success/failed")
    email = Column(String(255), nullable=False, comment="用户邮箱（统一小写）")
    code = Column(String(32), comment="兑换码；质保任务为最近普通兑换码")
    warranty_entry_id = Column(Integer, ForeignKey("warranty_email_entries.id"), comment="质保邮箱列表订单 ID")
    team_id = Column(Integer, ForeignKey("teams.id"), comment="当前预占/处理的 Team ID")
    idempotency_key = Column(String(255), nullable=False, comment="幂等键")
    attempt_count = Column(Integer, default=0, nullable=False, comment="处理尝试次数")
    max_attempts = Column(Integer, default=5, nullable=False, comment="最大处理尝试次数")
    reservation_released = Column(Boolean, default=False, nullable=False, comment="当前 Team 预占是否已释放")
    error = Column(Text, comment="失败原因")
    result_payload = Column(Text, comment="成功/失败结果 JSON")
    created_at = Column(DateTime, default=get_now, nullable=False, comment="创建时间")
    updated_at = Column(DateTime, default=get_now, onupdate=get_now, nullable=False, comment="更新时间")
    started_at = Column(DateTime, comment="开始处理时间")
    completed_at = Column(DateTime, comment="完成时间")

    __table_args__ = (
        Index("idx_invite_jobs_status_created_at", "status", "created_at"),
        Index("idx_invite_jobs_type_email", "job_type", "email"),
        Index("idx_invite_jobs_code", "code"),
        Index("idx_invite_jobs_warranty_entry", "warranty_entry_id"),
        Index("idx_invite_jobs_team_status", "team_id", "status"),
        Index("idx_invite_jobs_idempotency", "idempotency_key"),
    )


class Setting(Base):
    """系统设置表"""
    __tablename__ = "settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(100), unique=True, nullable=False, comment="配置项名称")
    value = Column(Text, comment="配置项值")
    description = Column(String(255), comment="配置项描述")
    created_at = Column(DateTime, default=get_now, comment="创建时间")
    updated_at = Column(DateTime, default=get_now, onupdate=get_now, comment="更新时间")

    # 索引
    __table_args__ = (
        Index("idx_key", "key"),
    )


class WarrantyEmailEntry(Base):
    """质保邮箱资格表"""
    __tablename__ = "warranty_email_entries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(255), nullable=False, comment="质保邮箱（统一小写）")
    remaining_claims = Column(Integer, default=0, nullable=False, comment="剩余质保次数")
    expires_at = Column(DateTime, comment="质保资格到期时间")
    source = Column(String(20), nullable=False, default="auto_redeem", comment="来源: auto_redeem/manual")
    last_redeem_code = Column(String(32), ForeignKey("redemption_codes.code"), comment="最近一次普通兑换码")
    last_warranty_team_id = Column(Integer, ForeignKey("teams.id"), comment="最近一次质保 Team ID")
    created_at = Column(DateTime, default=get_now, comment="创建时间")
    updated_at = Column(DateTime, default=get_now, onupdate=get_now, comment="更新时间")

    __table_args__ = (
        Index("idx_warranty_email_entries_email", "email"),
        Index("idx_warranty_email_entries_expires_at", "expires_at"),
        Index("idx_warranty_email_entries_source", "source"),
    )


class EmailWhitelistEntry(Base):
    """邮箱白名单表"""
    __tablename__ = "warranty_team_whitelist_entries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(255), unique=True, nullable=False, comment="白名单邮箱（统一小写）")
    source = Column(String(30), nullable=False, default="manual", comment="来源: console_team/warranty_email/manual/manual_pull")
    is_active = Column(Boolean, default=True, nullable=False, comment="是否启用自动清理保护")
    note = Column(Text, comment="备注")
    last_warranty_team_id = Column(Integer, ForeignKey("teams.id"), comment="最近关联 Team ID")
    created_at = Column(DateTime, default=get_now, nullable=False, comment="创建时间")
    updated_at = Column(DateTime, default=get_now, onupdate=get_now, nullable=False, comment="更新时间")

    __table_args__ = (
        Index("idx_warranty_team_whitelist_email", "email", unique=True),
        Index("idx_warranty_team_whitelist_source", "source"),
        Index("idx_warranty_team_whitelist_active", "is_active"),
    )


# 兼容旧代码路径：物理表仍沿用既有表名，业务语义升级为全局邮箱白名单。
WarrantyTeamWhitelistEntry = EmailWhitelistEntry


class WarrantyClaimRecord(Base):
    """质保提交记录表"""
    __tablename__ = "warranty_claim_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(255), nullable=False, comment="质保邮箱（统一小写）")
    before_team_id = Column(Integer, ForeignKey("teams.id"), comment="提交前所在 Team ID")
    before_team_name = Column(String(255), comment="提交前所在 Team 名称快照")
    before_team_email = Column(String(255), comment="提交前所在 Team 管理员邮箱快照")
    before_team_account_id = Column(String(100), comment="提交前所在 Team Account ID 快照")
    before_team_status = Column(String(20), comment="提交前所在 Team 状态")
    before_team_recorded_at = Column(DateTime, comment="提交前所在 Team 的最近记录时间")
    claim_status = Column(String(20), nullable=False, comment="质保提交状态: success/failed")
    failure_reason = Column(Text, comment="失败原因")
    after_team_id = Column(Integer, ForeignKey("teams.id"), comment="质保成功后加入的 Team ID")
    after_team_name = Column(String(255), comment="质保成功后加入的 Team 名称快照")
    after_team_email = Column(String(255), comment="质保成功后加入的 Team 管理员邮箱快照")
    after_team_account_id = Column(String(100), comment="质保成功后加入的 Team Account ID 快照")
    after_team_recorded_at = Column(DateTime, comment="质保成功后记录时间")
    submitted_at = Column(DateTime, default=get_now, nullable=False, comment="提交时间")
    completed_at = Column(DateTime, comment="处理完成时间")

    __table_args__ = (
        Index("idx_warranty_claim_records_email", "email"),
        Index("idx_warranty_claim_records_status", "claim_status"),
        Index("idx_warranty_claim_records_submitted_at", "submitted_at"),
    )


class TeamCleanupRecord(Base):
    """标准 Team 自动清理非绑定邮箱记录表"""
    __tablename__ = "team_cleanup_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    team_id = Column(Integer, ForeignKey("teams.id"), comment="触发清理的 Team ID")
    team_email = Column(String(255), nullable=False, comment="Team 管理员邮箱快照")
    team_name = Column(String(255), comment="Team 名称快照")
    team_account_id = Column(String(100), comment="Team Account ID 快照")
    cleanup_status = Column(String(20), nullable=False, default="success", comment="清理状态: success/partial_failed/failed")
    removed_member_count = Column(Integer, nullable=False, default=0, comment="自动删除成员数量")
    revoked_invite_count = Column(Integer, nullable=False, default=0, comment="自动撤回邀请数量")
    failed_count = Column(Integer, nullable=False, default=0, comment="自动清理失败数量")
    removed_member_emails = Column(Text, comment="删除成员邮箱 JSON")
    revoked_invite_emails = Column(Text, comment="撤回邀请邮箱 JSON")
    failed_items = Column(Text, comment="失败明细 JSON")
    created_at = Column(DateTime, default=get_now, nullable=False, comment="记录创建时间")

    __table_args__ = (
        Index("idx_team_cleanup_records_team_id", "team_id"),
        Index("idx_team_cleanup_records_status", "cleanup_status"),
        Index("idx_team_cleanup_records_created_at", "created_at"),
    )


class TeamRefreshRecord(Base):
    """Team 刷新记录表"""
    __tablename__ = "team_refresh_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    team_id = Column(Integer, ForeignKey("teams.id"), comment="刷新 Team ID")
    team_email = Column(String(255), nullable=False, comment="Team 管理员邮箱快照")
    team_name = Column(String(255), comment="Team 名称快照")
    team_account_id = Column(String(100), comment="Team Account ID 快照")
    source = Column(String(30), nullable=False, default="unknown", comment="刷新来源")
    refresh_status = Column(String(20), nullable=False, default="success", comment="刷新结果: success/failed")
    force_refresh = Column(Boolean, default=False, nullable=False, comment="是否强制刷新 Token")
    team_status = Column(String(20), comment="刷新后的 Team 状态")
    current_members = Column(Integer, comment="刷新后的成员数")
    max_members = Column(Integer, comment="刷新后的最大成员数")
    message = Column(Text, comment="成功信息")
    error = Column(Text, comment="失败原因")
    error_code = Column(String(100), comment="失败代码")
    cleanup_record_id = Column(Integer, ForeignKey("team_cleanup_records.id"), comment="关联自动清理记录 ID")
    cleanup_removed_member_count = Column(Integer, nullable=False, default=0, comment="自动删除成员数量")
    cleanup_revoked_invite_count = Column(Integer, nullable=False, default=0, comment="自动撤回邀请数量")
    cleanup_failed_count = Column(Integer, nullable=False, default=0, comment="自动清理失败数量")
    created_at = Column(DateTime, default=get_now, nullable=False, comment="记录创建时间")

    __table_args__ = (
        Index("idx_team_refresh_records_team_id", "team_id"),
        Index("idx_team_refresh_records_source", "source"),
        Index("idx_team_refresh_records_status", "refresh_status"),
        Index("idx_team_refresh_records_team_status", "team_status"),
        Index("idx_team_refresh_records_cleanup_record_id", "cleanup_record_id"),
        Index("idx_team_refresh_records_created_at", "created_at"),
    )
