"""
Team 管理服务
用于管理 Team 账号的导入、同步、成员管理等功能
"""
import logging
import asyncio
from typing import Optional, Dict, Any, List, Callable, Awaitable
from datetime import datetime
from sqlalchemy import select, update, delete, func, or_, case
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Team, TeamAccount, TeamMemberSnapshot, RedemptionCode, RedemptionRecord, WarrantyEmailEntry
from app.services.chatgpt import ChatGPTService
from app.services.team_cleanup_record import team_cleanup_record_service
from app.services.team_refresh_record import (
    SOURCE_ADMIN_BATCH,
    SOURCE_ADMIN_MEMBER,
    SOURCE_UNKNOWN,
    team_refresh_record_service,
)
from app.services.encryption import encryption_service
from app.services.redemption import RedemptionService
from app.services.settings import settings_service
from app.utils.token_parser import TokenParser
from app.utils.jwt_parser import JWTParser
from app.utils.time_utils import get_now

logger = logging.getLogger(__name__)

DEFAULT_TEAM_MAX_MEMBERS = 5
TEAM_OWNER_RESERVED_SEATS = 1
STANDARD_TRANSFER_CODE_COUNT = 4
TEAM_TYPE_STANDARD = "standard"
TEAM_TYPE_WARRANTY = "warranty"
IMPORT_STATUS_PENDING = "pending"
IMPORT_STATUS_CLASSIFIED = "classified"
IMPORT_TAG_OTHER_PAID = "other_paid"
IMPORT_TAG_SELF_PAID = "self_paid"
IMPORT_TAG_LABELS = {
    IMPORT_TAG_OTHER_PAID: "他付",
    IMPORT_TAG_SELF_PAID: "自付",
}
CLASSIFY_TARGET_STANDARD = "standard"
CLASSIFY_TARGET_WARRANTY_CODE = "warranty_code"
CLASSIFY_TARGET_WARRANTY_TEAM = "warranty_team"
IMPORT_RETRY_ATTEMPTS = 3
IMPORT_RETRY_DELAYS_SECONDS = (1, 2)
ProgressCallback = Optional[Callable[[Dict[str, Any]], Awaitable[None]]]


def normalize_import_tag(value: Optional[str]) -> Optional[str]:
    """标准化导入标签。"""
    if value is None:
        return None

    normalized_value = str(value).strip()
    if not normalized_value:
        return None

    alias_map = {
        "他付": IMPORT_TAG_OTHER_PAID,
        "other": IMPORT_TAG_OTHER_PAID,
        "other-paid": IMPORT_TAG_OTHER_PAID,
        "other_paid": IMPORT_TAG_OTHER_PAID,
        "自付": IMPORT_TAG_SELF_PAID,
        "self": IMPORT_TAG_SELF_PAID,
        "self-paid": IMPORT_TAG_SELF_PAID,
        "self_paid": IMPORT_TAG_SELF_PAID,
    }
    import_tag = alias_map.get(normalized_value.lower()) or alias_map.get(normalized_value)
    if import_tag not in IMPORT_TAG_LABELS:
        raise ValueError("无效的导入标签")

    return import_tag


def get_import_tag_label(value: Optional[str]) -> str:
    """获取导入标签展示名。"""
    return IMPORT_TAG_LABELS.get(value or "", "")


class TeamService:
    """Team 管理服务类"""

    BANNED_ERROR_CODES = {
        "account_deactivated",
        "token_invalidated",
        "account_suspended",
        "account_not_found",
        "user_not_found",
        "deactivated_workspace",
    }

    def __init__(self):
        """初始化 Team 管理服务"""
        from app.services.chatgpt import chatgpt_service
        self.chatgpt_service = chatgpt_service
        self.token_parser = TokenParser()
        self.jwt_parser = JWTParser()
        self.redemption_service = RedemptionService()

    def _get_import_retry_identifier(
        self,
        access_token: Optional[str],
        email: Optional[str],
        account_id: Optional[str]
    ) -> str:
        token_email = None
        if access_token:
            try:
                token_email = self.jwt_parser.extract_email(access_token)
            except Exception:
                token_email = None

        return email or token_email or account_id or "import"

    @staticmethod
    def _is_retryable_import_error(error: Optional[str]) -> bool:
        error_text = str(error or "")
        retryable_keywords = (
            "获取账户信息失败",
            "获取 Team 成员失败",
            "获取 Team 邀请失败",
            "初始成员数异常",
            "导入失败:"
        )
        return any(keyword in error_text for keyword in retryable_keywords)

    @staticmethod
    def _is_invalid_workspace_selected_error(error: Optional[str]) -> bool:
        return "invalid_workspace_selected" in str(error or "").lower()

    async def _clear_bound_codes_for_team(
        self,
        team_id: int,
        db_session: AsyncSession
    ) -> Dict[str, int]:
        """
        清理 Team 当前绑定的兑换码。

        - 未使用兑换码：直接删除，避免继续流入库存
        - 已使用/历史兑换码：仅解除绑定，避免破坏历史记录与质保追踪
        """
        stmt = select(RedemptionCode).where(RedemptionCode.bound_team_id == team_id)
        result = await db_session.execute(stmt)
        bound_codes = result.scalars().all()

        if not bound_codes:
            return {
                "total_cleared": 0,
                "deleted_unused_count": 0,
                "detached_history_count": 0
            }

        unused_ids = [code.id for code in bound_codes if code.status == "unused"]
        history_ids = [code.id for code in bound_codes if code.status != "unused"]

        if unused_ids:
            await db_session.execute(
                delete(RedemptionCode).where(RedemptionCode.id.in_(unused_ids))
            )

        if history_ids:
            await db_session.execute(
                update(RedemptionCode)
                .where(RedemptionCode.id.in_(history_ids))
                .values(bound_team_id=None)
            )

        return {
            "total_cleared": len(unused_ids) + len(history_ids),
            "deleted_unused_count": len(unused_ids),
            "detached_history_count": len(history_ids)
        }

    def _get_standard_transfer_code_count(self, team: Team) -> int:
        """
        兼容旧逻辑字段，统一池不再使用导入自动生码。

        默认补 4 个；若当前剩余席位不足，则按剩余席位生成，避免超卖。
        """
        remaining_seats = max((team.max_members or DEFAULT_TEAM_MAX_MEMBERS) - (team.current_members or 0), 0)
        return min(STANDARD_TRANSFER_CODE_COUNT, remaining_seats)

    async def _emit_progress(
        self,
        progress_callback: ProgressCallback,
        stage_key: str,
        stage_label: str,
        team: Optional[Team] = None
    ) -> None:
        if not progress_callback:
            return

        payload = {
            "stage_key": stage_key,
            "stage_label": stage_label,
        }
        if team is not None:
            payload["team_id"] = team.id
            payload["email"] = team.email

        await progress_callback(payload)

    def _normalize_member_email(self, email: Optional[str]) -> Optional[str]:
        normalized_email = (email or "").strip().lower()
        return normalized_email or None

    @staticmethod
    def _is_team_full_error_message(error: Optional[str]) -> bool:
        error_msg = str(error or "").lower()
        full_keywords = (
            "maximum number of seats",
            "reached maximum number of seats",
            "no seats available",
        )
        return any(keyword in error_msg for keyword in full_keywords)

    @staticmethod
    def _is_warranty_intercept_error(result: Dict[str, Any]) -> bool:
        error_code = str(result.get("error_code") or "").strip().lower()
        error_msg = str(result.get("error") or "").strip().lower()
        return error_code == "ghost_success" and "官方拦截下发" in error_msg

    def _should_mark_warranty_team_unavailable(self, team: Team, result: Dict[str, Any]) -> bool:
        if not team:
            return False

        error_msg = result.get("error")
        return self._is_warranty_intercept_error(result) or self._is_team_full_error_message(error_msg)

    def _mark_warranty_team_unavailable(
        self,
        team: Team,
        reason: Optional[str]
    ) -> None:
        if not team:
            return

        team.warranty_unavailable = True
        team.warranty_unavailable_reason = (reason or "").strip() or team.warranty_unavailable_reason
        team.warranty_unavailable_at = get_now()

    def _clear_warranty_team_unavailable(self, team: Team) -> None:
        if not team:
            return

        team.warranty_unavailable = False
        team.warranty_unavailable_reason = None
        team.warranty_unavailable_at = None

    async def _sync_team_member_snapshots(
        self,
        team: Team,
        joined_member_emails: set[str],
        invited_member_emails: set[str],
        db_session: AsyncSession
    ) -> None:
        desired_states: Dict[str, str] = {}

        for email in joined_member_emails:
            normalized_email = self._normalize_member_email(email)
            if normalized_email:
                desired_states[normalized_email] = "joined"

        for email in invited_member_emails:
            normalized_email = self._normalize_member_email(email)
            if normalized_email and normalized_email not in desired_states:
                desired_states[normalized_email] = "invited"

        result = await db_session.execute(
            select(TeamMemberSnapshot).where(TeamMemberSnapshot.team_id == team.id)
        )
        existing_snapshots = {
            snapshot.email: snapshot
            for snapshot in result.scalars().all()
        }

        desired_emails = set(desired_states.keys())
        for email, snapshot in existing_snapshots.items():
            if email not in desired_emails:
                await db_session.delete(snapshot)

        now = get_now()
        for email, member_state in desired_states.items():
            snapshot = existing_snapshots.get(email)
            if snapshot:
                snapshot.member_state = member_state
                snapshot.updated_at = now
            else:
                db_session.add(
                    TeamMemberSnapshot(
                        team_id=team.id,
                        email=email,
                        member_state=member_state,
                        created_at=now,
                        updated_at=now,
                    )
                )

        if desired_emails:
            warranty_entries_result = await db_session.execute(
                select(WarrantyEmailEntry).where(WarrantyEmailEntry.email.in_(desired_emails))
            )
            for entry in warranty_entries_result.scalars().all():
                entry.last_warranty_team_id = team.id

        await db_session.flush()

    async def _get_bound_code_allowed_emails(
        self,
        team_id: int,
        db_session: AsyncSession
    ) -> set[str]:
        result = await db_session.execute(
            select(RedemptionCode.used_by_email).where(
                RedemptionCode.bound_team_id == team_id,
                RedemptionCode.used_team_id == team_id,
                RedemptionCode.used_by_email.is_not(None),
            )
        )

        allowed_emails: set[str] = set()
        for email in result.scalars().all():
            normalized_email = self._normalize_member_email(email)
            if normalized_email:
                allowed_emails.add(normalized_email)

        record_result = await db_session.execute(
            select(RedemptionRecord.email).where(
                RedemptionRecord.team_id == team_id,
                RedemptionRecord.email.is_not(None),
            )
        )
        for email in record_result.scalars().all():
            normalized_email = self._normalize_member_email(email)
            if normalized_email:
                allowed_emails.add(normalized_email)

        return allowed_emails

    async def _get_email_cleanup_allowed_emails(
        self,
        db_session: AsyncSession
    ) -> set[str]:
        """获取系统自动清理全局邮箱白名单。"""
        from app.services.email_whitelist import email_whitelist_service

        return await email_whitelist_service.get_allowed_emails(db_session)

    async def _ensure_manual_email_whitelist(
        self,
        email: str,
        db_session: AsyncSession,
        last_warranty_team_id: Optional[int] = None,
    ) -> None:
        """管理员手动拉入 Team 的邮箱自动进入全局邮箱白名单。"""
        from app.services.email_whitelist import email_whitelist_service

        await email_whitelist_service.ensure_manual_entry(
            db_session=db_session,
            email=email,
            source=email_whitelist_service.SOURCE_MANUAL_PULL,
            last_warranty_team_id=last_warranty_team_id,
            commit=False,
        )

    async def _backfill_manual_warranty_whitelist_from_snapshots(
        self,
        team: Team,
        db_session: AsyncSession
    ) -> int:
        """从历史成员快照补写手动邮箱白名单。"""
        if not team:
            return 0

        from app.services.email_whitelist import email_whitelist_service

        result = await db_session.execute(
            select(TeamMemberSnapshot.email).where(TeamMemberSnapshot.team_id == team.id)
        )
        owner_email = self._normalize_member_email(team.email)
        snapshot_emails = {
            normalized_email
            for email in result.scalars().all()
            if (normalized_email := self._normalize_member_email(email))
            and normalized_email != owner_email
        }
        if not snapshot_emails:
            return 0

        processed_count = 0
        for email in sorted(snapshot_emails):
            await email_whitelist_service.ensure_manual_entry(
                db_session=db_session,
                email=email,
                source=email_whitelist_service.SOURCE_MANUAL_PULL,
                last_warranty_team_id=team.id,
                commit=False,
                reactivate_existing=False,
            )
            processed_count += 1

        if processed_count:
            await db_session.flush()
            logger.info(
                "已从历史成员快照补写邮箱白名单: team_id=%s count=%s",
                team.id,
                processed_count,
            )

        return processed_count

    def _build_member_state_from_results(
        self,
        members_result: Dict[str, Any],
        invites_result: Dict[str, Any]
    ) -> Dict[str, Any]:
        all_member_emails: set[str] = set()
        joined_member_emails: set[str] = set()
        invited_member_emails: set[str] = set()
        current_members = 0

        if members_result.get("success"):
            current_members += int(members_result.get("total") or 0)
            for member in members_result.get("members", []):
                normalized_email = self._normalize_member_email(member.get("email"))
                if not normalized_email:
                    continue
                all_member_emails.add(normalized_email)
                joined_member_emails.add(normalized_email)

        if invites_result.get("success"):
            current_members += int(invites_result.get("total") or 0)
            for invite in invites_result.get("items", []):
                normalized_email = self._normalize_member_email(invite.get("email_address"))
                if not normalized_email:
                    continue
                all_member_emails.add(normalized_email)
                invited_member_emails.add(normalized_email)

        return {
            "all_member_emails": all_member_emails,
            "joined_member_emails": joined_member_emails,
            "invited_member_emails": invited_member_emails,
            "current_members": current_members,
        }

    async def _cleanup_non_bound_team_emails(
        self,
        team: Team,
        access_token: str,
        account_id: str,
        members_result: Dict[str, Any],
        invites_result: Dict[str, Any],
        db_session: AsyncSession,
        allowed_emails: Optional[set[str]] = None,
        cleanup_scope_label: str = "标准 Team",
    ) -> Dict[str, Any]:
        cleanup_summary = {
            "removed_member_count": 0,
            "revoked_invite_count": 0,
            "failed_count": 0,
            "removed_member_emails": [],
            "revoked_invite_emails": [],
            "failed_items": [],
            "attempted": False,
        }

        effective_allowed_emails = (
            set(allowed_emails)
            if allowed_emails is not None
            else await self._get_email_cleanup_allowed_emails(db_session)
        )
        owner_email = self._normalize_member_email(team.email)
        if owner_email:
            effective_allowed_emails.add(owner_email)

        removable_members = []
        for member in members_result.get("members", []):
            normalized_email = self._normalize_member_email(member.get("email"))
            if not normalized_email or normalized_email in effective_allowed_emails:
                continue

            if (member.get("role") or "").strip().lower() == "account-owner":
                continue

            removable_members.append({
                "email": normalized_email,
                "user_id": member.get("id"),
            })

        revocable_invites = []
        for invite in invites_result.get("items", []):
            normalized_email = self._normalize_member_email(invite.get("email_address"))
            if not normalized_email or normalized_email in effective_allowed_emails:
                continue

            revocable_invites.append({"email": normalized_email})

        if not removable_members and not revocable_invites:
            return cleanup_summary

        cleanup_summary["attempted"] = True

        for member in removable_members:
            target_email = member["email"]
            user_id = member.get("user_id")

            if not user_id:
                cleanup_summary["failed_count"] += 1
                cleanup_summary["failed_items"].append({
                    "type": "member",
                    "email": target_email,
                    "error": "缺少用户 ID，无法删除成员",
                })
                logger.warning(
                    "%s 自动清理跳过成员: team_id=%s email=%s reason=%s",
                    cleanup_scope_label,
                    team.id,
                    target_email,
                    "缺少用户 ID",
                )
                continue

            delete_result = await self.chatgpt_service.delete_member(
                access_token,
                account_id,
                user_id,
                db_session,
                identifier=team.email,
            )

            if delete_result.get("success"):
                cleanup_summary["removed_member_count"] += 1
                cleanup_summary["removed_member_emails"].append(target_email)
                logger.info(
                    "%s 自动清理已删除成员: team_id=%s email=%s",
                    cleanup_scope_label,
                    team.id,
                    target_email,
                )
                continue

            cleanup_summary["failed_count"] += 1
            cleanup_summary["failed_items"].append({
                "type": "member",
                "email": target_email,
                "error": delete_result.get("error") or "删除成员失败",
            })
            logger.warning(
                "%s 自动清理删除成员失败: team_id=%s email=%s error=%s",
                cleanup_scope_label,
                team.id,
                target_email,
                delete_result.get("error"),
            )

        for invite in revocable_invites:
            target_email = invite["email"]
            revoke_result = await self.chatgpt_service.delete_invite(
                access_token,
                account_id,
                target_email,
                db_session,
                identifier=team.email,
            )

            if revoke_result.get("success"):
                cleanup_summary["revoked_invite_count"] += 1
                cleanup_summary["revoked_invite_emails"].append(target_email)
                logger.info(
                    "%s 自动清理已撤回邀请: team_id=%s email=%s",
                    cleanup_scope_label,
                    team.id,
                    target_email,
                )
                continue

            cleanup_summary["failed_count"] += 1
            cleanup_summary["failed_items"].append({
                "type": "invite",
                "email": target_email,
                "error": revoke_result.get("error") or "撤回邀请失败",
            })
            logger.warning(
                "%s 自动清理撤回邀请失败: team_id=%s email=%s error=%s",
                cleanup_scope_label,
                team.id,
                target_email,
                revoke_result.get("error"),
            )

        return cleanup_summary

    @staticmethod
    def _build_cleanup_summary_text(cleanup_summary: Dict[str, Any]) -> Optional[str]:
        removed_member_count = int(cleanup_summary.get("removed_member_count") or 0)
        revoked_invite_count = int(cleanup_summary.get("revoked_invite_count") or 0)
        failed_count = int(cleanup_summary.get("failed_count") or 0)

        if removed_member_count <= 0 and revoked_invite_count <= 0 and failed_count <= 0:
            return None

        return (
            f"自动清理：删除成员 {removed_member_count} 个，"
            f"撤回邀请 {revoked_invite_count} 个，失败 {failed_count} 个"
        )

    async def _handle_api_error(self, result: Dict[str, Any], team: Team, db_session: AsyncSession) -> bool:
        """
        检查结果是否表示账号被封禁、Token 失效或 Team 已满,如果是则更新状态
        
        Returns:
            bool: 是否已处理致命错误
        """
        error_code = result.get("error_code")
        error_msg = str(result.get("error", "")).lower()
        
        # 1. 判定是否为“封号/永久失效”类致命错误
        # 明确的错误码匹配
        is_banned = error_code in self.BANNED_ERROR_CODES
        
        # 关键词匹配 (针对不同接口返回的文本差异，尤其是刷新 Token 时 descripton 里的信息)
        if not is_banned:
            ban_keywords = [
                "token has been invalidated", 
                "account_deactivated",
                "account has been deactivated",
                "account is deactivated",
                "account_suspended",
                "account is suspended",
                "account was deleted",
                "user_not_found",
                "session_invalidated",
                "this account is deactivated",
                "deactivated_workspace"
            ]
            if any(kw in error_msg for kw in ban_keywords):
                is_banned = True
                
        # 1.1 判定是否为“虚假成功” (Ghost Success)
        if error_code == "ghost_success":
            logger.error(f"检测到 Team {team.id} ({team.email}) 存在“虚假成功”现象 (邀请返回 200 但列表无成员)，标记为 error")
            team.status = "error"
            if self._should_mark_warranty_team_unavailable(team, result):
                self._mark_warranty_team_unavailable(team, result.get("error"))
            if not db_session.in_transaction():
                await db_session.commit()
            return True

        if is_banned:
            # 简化状态描述判断
            if "workspace" in error_msg or "workspace" in (error_code or ""):
                status_desc = "到期"
            elif any(x in error_msg for x in ["deactivated", "suspended", "not found", "deleted"]):
                status_desc = "封禁"
            else:
                status_desc = "失效"
                
            logger.warning(f"检测到账号{status_desc} (code={error_code}, msg={error_msg}), 更新 Team {team.id} ({team.email}) 状态为 banned")
            team.status = "banned"
            if not db_session.in_transaction():
                await db_session.commit()
            return True

        # 2. 判定是否为“席位已满”错误
        if self._is_team_full_error_message(error_msg):
            logger.warning(f"检测到 Team 席位已满 (msg={error_msg}), 更新 Team {team.id} ({team.email}) 状态为 full")
            team.status = "full"
            if self._should_mark_warranty_team_unavailable(team, result):
                self._mark_warranty_team_unavailable(team, result.get("error"))
            # 学习真实的席位上限: 如果当前探测到的成员数小于预设的最大值，说明该团队实际容量较小
            if team.current_members > 0 and team.current_members < team.max_members:
                logger.info(f"修正 Team {team.id} 的最大成员数: {team.max_members} -> {team.current_members}")
                team.max_members = team.current_members
            elif team.current_members >= team.max_members:
                # 进位修正，确保逻辑闭环
                team.current_members = team.max_members

            if not db_session.in_transaction():
                await db_session.commit()
            return True

        # 2.5 判定是否为“已在团队中” (这通常被视为成功的变种)
        already_in_keywords = ["already in workspace", "already in team", "already a member"]
        if any(kw in error_msg for kw in already_in_keywords):
            logger.info(f"Team {team.id} 提示用户已在团队中: {error_msg}")
            # 虽然提示错误，但在业务逻辑上应视为加入成功
            return False # 返回 False 表示不是致命故障，允许后续逻辑（如下车/同步）继续

        # 3. 判定是否为 Token 过期 (需刷新)
        is_token_expired = error_code == "token_expired" or "token_expired" in error_msg or "token is expired" in error_msg
        
        # 4. 处理其他所有非致命错误 (累加错误次数)
        # 只要走到这里，说明不是封号也不是满员，统统记录错误
        logger.warning(f"Team {team.id} ({team.email}) 请求出错 (code={error_code}, msg={error_msg})")
        
        team.error_count = (team.error_count or 0) + 1
        if team.error_count >= 3:
            # 如果错误次数达标且是 Token 问题，标记为 expired 提高可读性
            if is_token_expired:
                logger.error(f"Team {team.id} 连续 Token 错误，标记为 expired")
                team.status = "expired"
            else:
                logger.error(f"Team {team.id} 连续错误 {team.error_count} 次，标记为 error")
                team.status = "error"
        
        # 如果是 Token 过期，尝试立即刷新一次（为下次重试做准备）
        if is_token_expired:
            logger.info(f"Team {team.id} Token 过期，尝试后台刷新...")
            # 注意：此处不等待刷新结果，仅作为修复尝试
            await self.ensure_access_token(team, db_session)
            
        if not db_session.in_transaction():
            await db_session.commit()
        return True
        
    async def _reset_error_status(self, team: Team, db_session: AsyncSession) -> None:
        """
        成功执行请求后重置错误计数并尝试从 error 状态恢复
        """
        team.error_count = 0
        if team.status == "error":
            # 恢复时也要校验是否满员或到期
            if team.current_members >= team.max_members:
                logger.info(f"Team {team.id} ({team.email}) 请求成功, 将状态从 error 恢复为 full")
                team.status = "full"
            elif team.expires_at and team.expires_at < datetime.now():
                logger.info(f"Team {team.id} ({team.email}) 请求成功, 将状态从 error 恢复为 expired")
                team.status = "expired"
            else:
                logger.info(f"Team {team.id} ({team.email}) 请求成功, 将状态从 error 恢复为 active")
                team.status = "active"
        if not db_session.in_transaction():
            await db_session.commit()

    def _is_fatal_token_refresh_error(self, result: Dict[str, Any]) -> bool:
        """
        判断 Token 刷新失败是否属于致命错误。

        仅对明确的封禁/失效类错误提前终止刷新流程；
        其他刷新失败应继续尝试备用刷新方式，或在当前 AT 仍有效时回退使用现有 Token。
        """
        error_code = result.get("error_code")
        error_msg = str(result.get("error", "")).lower()

        if error_code in self.BANNED_ERROR_CODES:
            return True

        fatal_keywords = [
            "token has been invalidated",
            "account_deactivated",
            "account has been deactivated",
            "account is deactivated",
            "account_suspended",
            "account is suspended",
            "account was deleted",
            "user_not_found",
            "session_invalidated",
            "this account is deactivated",
            "deactivated_workspace",
        ]
        return any(keyword in error_msg for keyword in fatal_keywords)

    async def ensure_access_token(self, team: Team, db_session: AsyncSession, force_refresh: bool = False) -> Optional[str]:
        """
        确保 AT Token 有效,如果过期则尝试刷新
        
        Args:
            team: Team 对象
            db_session: 数据库会话
            force_refresh: 是否强制刷新 (忽略过期检查)
            
        Returns:
            有效的 AT Token, 刷新失败返回 None
        """
        access_token = None
        current_token_is_valid = False

        try:
            # 1. 解密当前 Token
            access_token = encryption_service.decrypt_token(team.access_token_encrypted)

            # 2. 检查当前 Token 是否仍可用
            current_token_is_valid = not self.jwt_parser.is_token_expired(access_token)

            # 如果不强制刷新且未过期，则直接返回
            if not force_refresh and current_token_is_valid:
                return access_token

            if force_refresh:
                logger.info(f"Team {team.id} ({team.email}) 强制刷新 Token")
            else:
                logger.info(f"Team {team.id} ({team.email}) Token 已过期, 尝试刷新")
        except Exception as e:
            logger.error(f"解密或验证 Token 失败: {e}")
            access_token = None  # 可能是解密失败，强制走刷新流程
            current_token_is_valid = False

        # 3. 尝试使用 session_token 刷新
        if team.session_token_encrypted:
            session_token = encryption_service.decrypt_token(team.session_token_encrypted)
            refresh_result = await self.chatgpt_service.refresh_access_token_with_session_token(
                session_token, db_session, account_id=team.account_id, identifier=team.email
            )
            if refresh_result["success"]:
                new_at = refresh_result["access_token"]
                new_st = refresh_result.get("session_token")
                logger.info(f"Team {team.id} 通过 session_token 成功刷新 AT")
                team.access_token_encrypted = encryption_service.encrypt_token(new_at)
                
                # 如果返回了新的 session_token,予以更新
                if new_st and new_st != session_token:
                    logger.info(f"Team {team.id} Session Token 已更新")
                    team.session_token_encrypted = encryption_service.encrypt_token(new_st)
                
                # 成功刷新，重置错误状态
                await self._reset_error_status(team, db_session)
                return new_at
            else:
                if self._is_fatal_token_refresh_error(refresh_result):
                    await self._handle_api_error(refresh_result, team, db_session)
                    return None
                logger.warning(
                    f"Team {team.id} ({team.email}) 通过 session_token 刷新失败，继续尝试其他方式: "
                    f"{refresh_result.get('error', '未知错误')}"
                )

        # 4. 尝试使用 refresh_token 刷新
        if team.refresh_token_encrypted and team.client_id:
            refresh_token = encryption_service.decrypt_token(team.refresh_token_encrypted)
            refresh_result = await self.chatgpt_service.refresh_access_token_with_refresh_token(
                refresh_token, team.client_id, db_session, identifier=team.email
            )
            if refresh_result["success"]:
                new_at = refresh_result["access_token"]
                new_rt = refresh_result.get("refresh_token")
                logger.info(f"Team {team.id} 通过 refresh_token 成功刷新 AT")
                team.access_token_encrypted = encryption_service.encrypt_token(new_at)
                if new_rt:
                    team.refresh_token_encrypted = encryption_service.encrypt_token(new_rt)
                # 成功刷新，重置错误状态
                await self._reset_error_status(team, db_session)
                return new_at
            else:
                if self._is_fatal_token_refresh_error(refresh_result):
                    await self._handle_api_error(refresh_result, team, db_session)
                    return None

                logger.warning(
                    f"Team {team.id} ({team.email}) 通过 refresh_token 刷新失败: "
                    f"{refresh_result.get('error', '未知错误')}"
                )

        # 5. 强制刷新失败，但当前 Token 仍有效时，回退到现有 Token，避免误判为 expired
        if current_token_is_valid and access_token:
            logger.warning(
                f"Team {team.id} ({team.email}) 强制刷新失败，但当前 Access Token 仍有效，继续使用现有 Token"
            )
            return access_token

        if team.status != "banned":
            logger.error(f"Team {team.id} Token 已过期且无法刷新，标记为 expired")
            team.status = "expired"
            team.error_count = (team.error_count or 0) + 1
        if not db_session.in_transaction():
            await db_session.commit()
        return None

    async def import_team_single(
        self,
        access_token: Optional[str],
        db_session: AsyncSession,
        email: Optional[str] = None,
        account_id: Optional[str] = None,
        refresh_token: Optional[str] = None,
        session_token: Optional[str] = None,
        client_id: Optional[str] = None,
        team_type: str = TEAM_TYPE_STANDARD,
        generate_warranty_codes: bool = False,
        warranty_days: int = 30,
        generate_codes_on_import: bool = True,
        import_status: str = IMPORT_STATUS_CLASSIFIED,
        imported_by_user_id: Optional[int] = None,
        imported_by_username: Optional[str] = None,
        import_tag: Optional[str] = None,
    ) -> Dict[str, Any]:
        retry_identifier = self._get_import_retry_identifier(access_token, email, account_id)
        last_result: Optional[Dict[str, Any]] = None

        for attempt in range(1, IMPORT_RETRY_ATTEMPTS + 1):
            result = await self._import_team_single_once(
                access_token=access_token,
                db_session=db_session,
                email=email,
                account_id=account_id,
                refresh_token=refresh_token,
                session_token=session_token,
                client_id=client_id,
                team_type=team_type,
                generate_warranty_codes=generate_warranty_codes,
                warranty_days=warranty_days,
                generate_codes_on_import=generate_codes_on_import,
                import_status=import_status,
                imported_by_user_id=imported_by_user_id,
                imported_by_username=imported_by_username,
                import_tag=import_tag,
            )

            if result.get("success"):
                if attempt > 1:
                    logger.info(
                        "Team 导入在第 %s 次尝试后成功: email=%s account_id=%s",
                        attempt,
                        result.get("email") or email,
                        account_id
                    )
                return result

            last_result = result
            error_message = result.get("error")
            retryable = self._is_retryable_import_error(error_message)
            if not retryable or attempt >= IMPORT_RETRY_ATTEMPTS:
                return result

            delay_seconds = IMPORT_RETRY_DELAYS_SECONDS[min(attempt - 1, len(IMPORT_RETRY_DELAYS_SECONDS) - 1)]
            logger.warning(
                "Team 导入失败，准备重试: attempt=%s/%s email=%s account_id=%s error=%s",
                attempt,
                IMPORT_RETRY_ATTEMPTS,
                result.get("email") or email,
                account_id,
                error_message
            )
            await self.chatgpt_service.clear_session(retry_identifier)
            await asyncio.sleep(delay_seconds)

        return last_result or {
            "success": False,
            "team_id": None,
            "email": email,
            "message": None,
            "error": "导入失败: 未知错误"
        }

    async def _import_team_single_once(
        self,
        access_token: Optional[str],
        db_session: AsyncSession,
        email: Optional[str] = None,
        account_id: Optional[str] = None,
        refresh_token: Optional[str] = None,
        session_token: Optional[str] = None,
        client_id: Optional[str] = None,
        team_type: str = TEAM_TYPE_STANDARD,
        generate_warranty_codes: bool = False,
        warranty_days: int = 30,
        generate_codes_on_import: bool = True,
        import_status: str = IMPORT_STATUS_CLASSIFIED,
        imported_by_user_id: Optional[int] = None,
        imported_by_username: Optional[str] = None,
        import_tag: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        单个导入 Team

        Args:
            access_token: AT Token (可选,如果提供 RT/ST 可自动获取)
            db_session: 数据库会话
            email: 邮箱 (可选,如果不提供则从 Token 中提取)
            account_id: Account ID (可选,如果不提供则从 API 获取并导入所有活跃的)

        Returns:
            结果字典,包含 success, team_id (第一个导入的), message, error
        """
        try:
            normalized_import_tag = normalize_import_tag(import_tag)
            normalized_team_type = TEAM_TYPE_STANDARD
            should_generate_codes = False

            # 1. 检查并尝试刷新 Token (如果 AT 缺失或过期)
            is_at_valid = False
            if access_token:
                try:
                    if not self.jwt_parser.is_token_expired(access_token):
                        is_at_valid = True
                except:
                    pass
            
            if not is_at_valid:
                logger.info("导入时 AT 缺失或过期, 尝试使用 ST/RT 刷新")
                # 尝试 session_token
                if session_token:
                    refresh_result = await self.chatgpt_service.refresh_access_token_with_session_token(
                        session_token, db_session, account_id=account_id, identifier=email or "import"
                    )
                    if refresh_result["success"]:
                        access_token = refresh_result["access_token"]
                        # 导入时如果 ST 变了,更新变量以便后续保存
                        if refresh_result.get("session_token"):
                            session_token = refresh_result["session_token"]
                        is_at_valid = True
                        logger.info("导入时通过 session_token 成功获取 AT")
                
                # 尝试 refresh_token
                if not is_at_valid and refresh_token and client_id:
                    refresh_result = await self.chatgpt_service.refresh_access_token_with_refresh_token(
                        refresh_token, client_id, db_session, identifier=email or "import"
                    )
                    if refresh_result["success"]:
                        access_token = refresh_result["access_token"]
                        # RT 刷新可能会返回新的 RT
                        if refresh_result.get("refresh_token"):
                            refresh_token = refresh_result["refresh_token"]
                        is_at_valid = True
                        logger.info("导入时通过 refresh_token 成功获取 AT")

            if not access_token or not is_at_valid:
                return {
                    "success": False,
                    "team_id": None,
                    "email": email,
                    "message": None,
                    "error": "缺少有效的 Access Token，且无法通过 Session/Refresh Token 刷新"
                }

            # 2. 如果没有提供邮箱,从 Token 中提取; 如果提供了,则校验是否匹配 (安全兜底)
            token_email = self.jwt_parser.extract_email(access_token)
            if not email:
                email = token_email
                if not email:
                    return {
                        "success": False,
                        "team_id": None,
                        "email": None,
                        "message": None,
                        "error": "无法从 Token 中提取邮箱,请手动提供邮箱"
                    }
            elif token_email and token_email.lower() != email.lower():
                logger.error(f"导入时 Token 邮箱不匹配: 预期 {email}, 实际 {token_email}")
                return {
                    "success": False,
                    "team_id": None,
                    "email": email,
                    "message": None,
                    "error": f"Token 对应的账号身份 ({token_email}) 与提供的邮箱 ({email}) 不符，导入已中止。请检查是否有其他账号正在登录导致 Session 污染。"
                }

            # 2. 尝试从 API 获取账户信息
            accounts_to_import = []
            team_accounts = []
            
            account_result = await self.chatgpt_service.get_account_info(
                access_token,
                db_session,
                identifier=email,
                account_id=account_id
            )
            
            if account_result["success"]:
                team_accounts = account_result["accounts"]
            else:
                logger.warning(f"导入时获取账户信息失败: {account_result['error']}")
                if (
                    session_token
                    and account_id
                    and self._is_invalid_workspace_selected_error(account_result.get("error"))
                ):
                    logger.info(
                        "导入时检测到 invalid_workspace_selected，尝试使用 session_token 重新交换 workspace AT: email=%s account_id=%s",
                        email,
                        account_id
                    )
                    await self.chatgpt_service.clear_session(email or "import")
                    refresh_result = await self.chatgpt_service.refresh_access_token_with_session_token(
                        session_token,
                        db_session,
                        account_id=account_id,
                        identifier=email or "import"
                    )
                    if refresh_result["success"]:
                        access_token = refresh_result["access_token"]
                        if refresh_result.get("session_token"):
                            session_token = refresh_result["session_token"]
                        account_result = await self.chatgpt_service.get_account_info(
                            access_token,
                            db_session,
                            identifier=email,
                            account_id=account_id
                        )
                        if account_result["success"]:
                            team_accounts = account_result["accounts"]
                            logger.info("导入时通过 session_token 重新换取 workspace AT 后获取账户信息成功")
                        else:
                            logger.warning(f"导入时重试获取账户信息仍失败: {account_result['error']}")

            # 3. 确定要导入的账户列表
            if account_id:
                # 3.1 指定 account_id 时，必须拉到真实元数据，避免“假成功”落库
                if not account_result["success"]:
                    return {
                        "success": False,
                        "team_id": None,
                        "email": email,
                        "message": None,
                        "error": f"获取账户信息失败，无法校验指定的 Account ID: {account_result['error']}"
                    }

                found_account = next((acc for acc in team_accounts if acc["account_id"] == account_id), None)
                
                if found_account:
                    accounts_to_import.append(found_account)
                    logger.info(f"导入时找到指定的 account_id: {account_id}, 已获取真实元数据")
                else:
                    return {
                        "success": False,
                        "team_id": None,
                        "email": email,
                        "message": None,
                        "error": f"指定的 Account ID ({account_id}) 未出现在当前 Token 可访问的 Team 列表中，导入已中止。"
                    }
            
            # 3.2 自动导入 API 返回的所有其他活跃账号 (多账号支持)
            for acc in team_accounts:
                if acc["has_active_subscription"]:
                    # 避免与指定的 account_id 重复
                    if not any(a["account_id"] == acc["account_id"] for a in accounts_to_import):
                        accounts_to_import.append(acc)

            # 3.3 如果此时依然没有任何账号可导入 (且没有指定 account_id)
            if not accounts_to_import and not account_id:
                if not account_result["success"]:
                    return {
                        "success": False,
                        "team_id": None,
                        "email": email,
                        "message": None,
                        "error": f"获取账户信息失败: {account_result['error']}"
                    }
                
                if not team_accounts:
                    return {
                        "success": False,
                        "team_id": None,
                        "email": email,
                        "message": None,
                        "error": "该 Token 没有关联任何 Team 账户"
                    }
                
                # 保底使用第一个
                accounts_to_import.append(team_accounts[0])

            # 4. 循环处理这些账户
            imported_ids = []
            imported_team_details = []
            skipped_ids = []
            
            for selected_account in accounts_to_import:
                # 检查是否已存在 (根据 account_id)
                stmt = select(Team).where(
                    Team.account_id == selected_account["account_id"]
                )
                result = await db_session.execute(stmt)
                existing_team = result.scalar_one_or_none()

                if existing_team:
                    skipped_ids.append(selected_account["account_id"])
                    continue

                # 获取成员列表 (包含已加入和待加入)
                members_result = await self.chatgpt_service.get_members(
                    access_token,
                    selected_account["account_id"],
                    db_session,
                    identifier=email
                )
                
                invites_result = await self.chatgpt_service.get_invites(
                    access_token,
                    selected_account["account_id"],
                    db_session,
                    identifier=email
                )

                if not members_result["success"]:
                    return {
                        "success": False,
                        "team_id": None,
                        "email": email,
                        "message": None,
                        "error": f"获取 Team 成员失败: {members_result['error']}"
                    }

                if not invites_result["success"]:
                    return {
                        "success": False,
                        "team_id": None,
                        "email": email,
                        "message": None,
                        "error": f"获取 Team 邀请失败: {invites_result['error']}"
                    }

                current_members = 0
                current_members += members_result["total"]
                if current_members < 1:
                    return {
                        "success": False,
                        "team_id": None,
                        "email": email,
                        "message": None,
                        "error": f"导入校验失败: Team 初始成员数异常 ({current_members})，预期至少为 1"
                    }
                current_members += invites_result["total"]

                # 解析过期时间
                expires_at = None
                if selected_account["expires_at"]:
                    try:
                        # ISO 8601 格式: 2026-02-21T23:10:05+00:00
                        expires_at = datetime.fromisoformat(
                            selected_account["expires_at"].replace("+00:00", "")
                        )
                    except Exception as e:
                        logger.warning(f"解析过期时间失败: {e}")

                # 获取账户设置 (包含 beta_settings)
                device_code_auth_enabled = False
                settings_result = await self.chatgpt_service.get_account_settings(
                    access_token,
                    selected_account["account_id"],
                    db_session,
                    identifier=email
                )
                if settings_result["success"]:
                    beta_settings = settings_result["data"].get("beta_settings", {})
                    device_code_auth_enabled = beta_settings.get("codex_device_code_auth", False)

                # 确定状态和最大成员数（默认值来自系统设置）
                max_members = await settings_service.get_default_team_max_members(db_session)
                status = "active"
                if current_members >= max_members:
                    status = "full"
                elif expires_at and expires_at < datetime.now():
                    status = "expired"

                # 加密 AT Token
                encrypted_token = encryption_service.encrypt_token(access_token)
                encrypted_rt = encryption_service.encrypt_token(refresh_token) if refresh_token else None
                encrypted_st = encryption_service.encrypt_token(session_token) if session_token else None
                normalized_warranty_days = max(int(warranty_days or 30), 1)

                # 创建 Team 记录
                team = Team(
                    email=email,
                    access_token_encrypted=encrypted_token,
                    refresh_token_encrypted=encrypted_rt,
                    session_token_encrypted=encrypted_st,
                    client_id=client_id,
                    encryption_key_id="default",
                    account_id=selected_account["account_id"],
                    team_type=normalized_team_type,
                    bound_code_type=TEAM_TYPE_STANDARD,
                    bound_code_warranty_days=None,
                    team_name=selected_account["name"],
                    plan_type=selected_account["plan_type"],
                    subscription_plan=selected_account["subscription_plan"],
                    expires_at=expires_at,
                    current_members=current_members,
                    max_members=max_members,
                    status=status,
                    account_role=selected_account.get("account_user_role"),
                    device_code_auth_enabled=device_code_auth_enabled,
                    last_sync=get_now(),
                    import_status=import_status if import_status in {IMPORT_STATUS_PENDING, IMPORT_STATUS_CLASSIFIED} else IMPORT_STATUS_CLASSIFIED,
                    imported_by_user_id=imported_by_user_id,
                    imported_by_username=imported_by_username,
                    import_tag=normalized_import_tag,
                )

                db_session.add(team)
                await db_session.flush()  # 获取 team.id

                # 创建 TeamAccount 记录 (保存所有 Team 账户)
                for acc in team_accounts:
                    team_account = TeamAccount(
                        team_id=team.id,
                        account_id=acc["account_id"],
                        account_name=acc["name"],
                        is_primary=(acc["account_id"] == selected_account["account_id"])
                    )
                    db_session.add(team_account)

                remaining_seats = max(max_members - current_members, 0)
                generated_codes = []
                if should_generate_codes and generate_codes_on_import and remaining_seats > 0:
                    generate_result = await self.redemption_service.generate_code_batch(
                        db_session=db_session,
                        count=remaining_seats,
                        bound_team_id=team.id,
                        has_warranty=False,
                        warranty_days=normalized_warranty_days,
                        commit=False
                    )
                    if not generate_result["success"]:
                        raise Exception(
                            f"为 Team {team.team_name or team.id} 自动生成兑换码失败: {generate_result['error']}"
                        )
                    generated_codes = generate_result.get("codes", [])

                imported_ids.append(team.id)
                imported_team_details.append({
                    "team_id": team.id,
                    "account_id": team.account_id,
                    "team_type": team.team_type,
                    "bound_code_type": team.bound_code_type,
                    "import_tag": team.import_tag,
                    "import_tag_label": get_import_tag_label(team.import_tag),
                    "team_name": team.team_name,
                    "current_members": current_members,
                    "max_members": max_members,
                    "remaining_seats": remaining_seats,
                    "generated_codes": generated_codes,
                    "generated_code_count": len(generated_codes),
                    "generated_code_has_warranty": False,
                    "generated_code_warranty_days": None,
                })

            # 5. 返回结果总结
            if not imported_ids and skipped_ids:
                return {
                    "success": False,
                    "team_id": None,
                    "email": email,
                    "message": None,
                    "error": f"共发现 {len(skipped_ids)} 个 Team 账号,但均已在系统中"
                }
            
            if not imported_ids:
                return {
                    "success": False,
                    "team_id": None,
                    "email": email,
                    "message": None,
                    "error": "未发现可导入的 Team 账号"
                }

            await db_session.commit()

            total_generated_codes = sum(item["generated_code_count"] for item in imported_team_details)

            message = f"成功导入 {len(imported_ids)} 个 Team 账号；兑换码请在兑换码管理页面生成"
            if skipped_ids:
                message += f" (另有 {len(skipped_ids)} 个已存在)"

            logger.info(f"Team 导入成功: {email}, 共 {len(imported_ids)} 个账号")

            return {
                "success": True,
                "team_id": imported_ids[0],
                "team_ids": imported_ids,
                "email": email,
                "imported_teams": imported_team_details,
                "generated_codes": [code for item in imported_team_details for code in item["generated_codes"]],
                "generated_code_count": total_generated_codes,
                "message": message,
                "error": None
            }

        except Exception as e:
            await db_session.rollback()
            logger.error(f"Team 导入失败: {e}")
            return {
                "success": False,
                "team_id": None,
                "email": email,
                "message": None,
                "error": f"导入失败: {str(e)}"
            }


    async def update_team(
        self,
        team_id: int,
        db_session: AsyncSession,
        access_token: Optional[str] = None,
        refresh_token: Optional[str] = None,
        session_token: Optional[str] = None,
        client_id: Optional[str] = None,
        email: Optional[str] = None,
        account_id: Optional[str] = None,
        max_members: Optional[int] = None,
        team_name: Optional[str] = None,
        status: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        更新 Team 信息

        Args:
            team_id: Team ID
            db_session: 数据库会话
            access_token: 新的 AT Token (可选)
            refresh_token: 新的 RT Token (可选)
            session_token: 新的 ST Token (可选)
            client_id: 新的 Client ID (可选)
            email: 新的邮箱 (可选)
            account_id: 新的 Account ID (可选)
            max_members: 最大成员数 (可选)
            team_name: Team 名称 (可选)
            status: 状态 (可选)

        Returns:
            结果字典
        """
        try:
            # 1. 查询 Team (包含关联的 team_accounts)
            stmt = select(Team).where(Team.id == team_id).options(
                selectinload(Team.team_accounts)
            )
            result = await db_session.execute(stmt)
            team = result.scalar_one_or_none()

            if not team:
                return {"success": False, "error": f"Team ID {team_id} 不存在"}

            # 2. 更新属性
            if email:
                team.email = email
            
            if team_name is not None:
                team.team_name = team_name

            if account_id:
                team.account_id = account_id
                # 更新关联账户的主次状态
                for acc in team.team_accounts:
                    if acc.account_id == account_id:
                        acc.is_primary = True
                    else:
                        acc.is_primary = False

            # 3. 更新 Token
            if access_token:
                team.access_token_encrypted = encryption_service.encrypt_token(access_token)
            if refresh_token:
                team.refresh_token_encrypted = encryption_service.encrypt_token(refresh_token)
            if session_token:
                team.session_token_encrypted = encryption_service.encrypt_token(session_token)
            if client_id:
                team.client_id = client_id

            # 4. 更新最大成员数
            if max_members is not None:
                team.max_members = max_members

            # 5. 更新状态
            if status:
                team.status = status
            
            # 自动维护 active/full/expired 状态 (仅当当前处于这三者之一或刚更新了 max_members/status)
            if team.status in ["active", "full", "expired"]:
                if team.current_members >= team.max_members:
                    team.status = "full"
                elif team.expires_at and team.expires_at < datetime.now():
                    team.status = "expired"
                else:
                    team.status = "active"

            await db_session.commit()


            logger.info(f"Team {team_id} 信息更新成功")
            return {"success": True, "message": "Team 信息更新成功"}

        except Exception as e:
            await db_session.rollback()
            logger.error(f"更新 Team 失败: {e}")
            return {"success": False, "error": f"更新失败: {str(e)}"}

    async def get_team_info(self, team_id: int, db_session: AsyncSession) -> Dict[str, Any]:
        """获取 Team 详细信息 (含解密 Token)"""
        try:
            stmt = select(Team).where(Team.id == team_id)
            result = await db_session.execute(stmt)
            team = result.scalar_one_or_none()

            if not team:
                return {"success": False, "error": "Team 不存在"}

            # 解密 Token
            access_token = ""
            try:
                access_token = encryption_service.decrypt_token(team.access_token_encrypted)
            except Exception as e:
                logger.error(f"解密 Token 失败: {e}")

            return {
                "success": True,
                "team": {
                    "id": team.id,
                    "email": team.email,
                    "account_id": team.account_id,
                    "max_members": team.max_members,
                    "access_token": access_token,
                    "refresh_token": encryption_service.decrypt_token(team.refresh_token_encrypted) if team.refresh_token_encrypted else "",
                    "session_token": encryption_service.decrypt_token(team.session_token_encrypted) if team.session_token_encrypted else "",
                    "client_id": team.client_id or "",
                    "team_name": team.team_name,
                    "status": team.status,
                    "account_role": team.account_role,
                    "device_code_auth_enabled": team.device_code_auth_enabled
                }
            }
        except Exception as e:
            logger.error(f"获取 Team 信息失败: {e}")
            return {"success": False, "error": str(e)}

    async def transfer_team_type(
        self,
        team_id: int,
        target_team_type: str,
        db_session: AsyncSession
    ) -> Dict[str, Any]:
        """兼容旧接口：统一 Team 池后只允许归一到控制台 Team。"""
        try:
            stmt = select(Team).where(Team.id == team_id)
            result = await db_session.execute(stmt)
            team = result.scalar_one_or_none()

            if not team:
                return {"success": False, "error": f"Team ID {team_id} 不存在"}

            current_team_type = (team.team_type or TEAM_TYPE_STANDARD).strip().lower()
            normalized_target_type = (target_team_type or "").strip().lower()

            if normalized_target_type != TEAM_TYPE_STANDARD:
                return {"success": False, "error": "目标 Team 类型无效"}

            cleanup_result = await self._clear_bound_codes_for_team(team.id, db_session)
            team.team_type = TEAM_TYPE_STANDARD
            team.bound_code_type = TEAM_TYPE_STANDARD
            team.bound_code_warranty_days = None

            generated_codes: List[str] = []
            generated_code_count = 0

            await db_session.commit()

            message = f"账号已归一到控制台 Team，已清理 {cleanup_result['total_cleared']} 个历史 Team 绑定"

            logger.info(
                "Team 类型转移成功: team_id=%s, from=%s, to=%s, cleaned=%s, generated=%s",
                team.id,
                current_team_type,
                TEAM_TYPE_STANDARD,
                cleanup_result["total_cleared"],
                generated_code_count
            )

            return {
                "success": True,
                "team_id": team.id,
                "team_type": TEAM_TYPE_STANDARD,
                "cleaned_code_count": cleanup_result["total_cleared"],
                "deleted_unused_code_count": cleanup_result["deleted_unused_count"],
                "detached_history_code_count": cleanup_result["detached_history_count"],
                "generated_code_count": generated_code_count,
                "generated_codes": generated_codes,
                "message": message,
                "error": None
            }
        except Exception as e:
            await db_session.rollback()
            logger.error(f"转移 Team 类型失败: {e}")
            return {"success": False, "error": f"转移失败: {str(e)}"}

    async def classify_pending_team(
        self,
        team_id: int,
        target: str,
        db_session: AsyncSession,
        warranty_days: int = 30,
    ) -> Dict[str, Any]:
        """将待分类 Team 归档到统一控制台池；兑换码统一在兑换码管理页生成。"""
        normalized_target = (target or "").strip().lower()
        if normalized_target not in {
            CLASSIFY_TARGET_STANDARD,
            CLASSIFY_TARGET_WARRANTY_CODE,
            CLASSIFY_TARGET_WARRANTY_TEAM,
        }:
            return {"success": False, "error": "分类目标无效"}

        try:
            team = await db_session.scalar(select(Team).where(Team.id == team_id))
            if not team:
                return {"success": False, "error": f"Team ID {team_id} 不存在"}

            if (team.import_status or IMPORT_STATUS_CLASSIFIED) != IMPORT_STATUS_PENDING:
                return {"success": False, "error": "该 Team 不在待分类列表中"}

            cleanup_result = await self._clear_bound_codes_for_team(team.id, db_session)
            generated_codes: List[str] = []

            team.import_status = IMPORT_STATUS_CLASSIFIED
            team.bound_code_type = TEAM_TYPE_STANDARD
            team.bound_code_warranty_days = None
            team.team_type = TEAM_TYPE_STANDARD
            message = "已归类到控制台 Team；兑换码请在兑换码管理页面生成"

            await db_session.commit()
            return {
                "success": True,
                "team_id": team.id,
                "target": normalized_target,
                "team_type": team.team_type,
                "bound_code_type": team.bound_code_type,
                "generated_codes": generated_codes,
                "generated_code_count": len(generated_codes),
                "cleaned_code_count": cleanup_result["total_cleared"],
                "message": message,
                "error": None,
            }
        except Exception as e:
            await db_session.rollback()
            logger.error("待分类 Team 归类失败: %s", e)
            return {"success": False, "error": f"分类失败: {str(e)}"}


    async def import_team_batch(
        self,
        text: str,
        db_session: AsyncSession,
        team_type: str = TEAM_TYPE_STANDARD,
        generate_warranty_codes: bool = False,
        warranty_days: int = 30,
        generate_codes_on_import: bool = True,
        import_status: str = IMPORT_STATUS_CLASSIFIED,
        imported_by_user_id: Optional[int] = None,
        imported_by_username: Optional[str] = None,
        import_tag: Optional[str] = None,
    ):
        """
        批量导入 Team (流式返回进度)

        Args:
            text: 包含 Token、邮箱、Account ID 的文本
            db_session: 数据库会话

        Yields:
            各阶段进度的 Dict
        """
        try:
            # 1. 解析文本
            normalized_import_tag = normalize_import_tag(import_tag)
            parsed_data = self.token_parser.parse_team_import_text(text)

            if not parsed_data:
                yield {
                    "type": "error",
                    "error": "未能从文本中提取任何 Token"
                }
                return

            # 1.1 按邮箱去重 (以前是按 AT，现在改为按邮箱，防止重复处理同一个账号)
            seen_emails = set()
            unique_data = []
            for item in parsed_data:
                token = item.get("token")
                email = item.get("email")
                
                # 如果没有显式邮箱，尝试从 Token 中提取
                if not email and token:
                    try:
                        extracted = self.jwt_parser.extract_email(token)
                        if extracted:
                            email = extracted
                            item["email"] = email
                    except:
                        pass
                
                # 确定排重键：优先使用邮箱(不区分大小写)，如果没有则退而求其次使用 Token
                dedup_key = email.lower() if email else token
                
                if dedup_key and dedup_key not in seen_emails:
                    seen_emails.add(dedup_key)
                    unique_data.append(item)
            
            parsed_data = unique_data
            total = len(parsed_data)
            yield {
                "type": "start",
                "total": total
            }

            # 2. 逐个导入
            success_count = 0
            failed_count = 0

            for i, data in enumerate(parsed_data):
                result = await self.import_team_single(
                    access_token=data.get("token"),
                    db_session=db_session,
                    email=data.get("email"),
                    account_id=data.get("account_id"),
                    refresh_token=data.get("refresh_token"),
                    session_token=data.get("session_token"),
                    client_id=data.get("client_id"),
                    team_type=team_type,
                    generate_warranty_codes=generate_warranty_codes,
                    warranty_days=warranty_days,
                    generate_codes_on_import=generate_codes_on_import,
                    import_status=import_status,
                    imported_by_user_id=imported_by_user_id,
                    imported_by_username=imported_by_username,
                    import_tag=normalized_import_tag,
                )

                if result["success"]:
                    success_count += 1
                else:
                    failed_count += 1

                yield {
                    "type": "progress",
                    "current": i + 1,
                    "total": total,
                    "success_count": success_count,
                    "failed_count": failed_count,
                    "last_result": {
                        "email": result.get("email") or data.get("email") or "未知",
                        "account_id": data.get("account_id", "未指定"),
                        "success": result["success"],
                        "team_id": result["team_id"],
                        "team_ids": result.get("team_ids", []),
                        "imported_teams": result.get("imported_teams", []),
                        "generated_codes": result.get("generated_codes", []),
                        "generated_code_count": result.get("generated_code_count", 0),
                        "message": result["message"],
                        "error": result["error"]
                    }
                }

            logger.info(f"批量导入完成: 总数 {total}, 成功 {success_count}, 失败 {failed_count}")

            yield {
                "type": "finish",
                "total": total,
                "success_count": success_count,
                "failed_count": failed_count
            }

        except Exception as e:
            logger.error(f"批量导入失败: {e}")
            yield {
                "type": "error",
                "error": f"批量导入过程中发生异常: {str(e)}"
            }

    async def sync_team_info(
        self,
        team_id: int,
        db_session: AsyncSession,
        force_refresh: bool = False,
        progress_callback: ProgressCallback = None,
        enforce_bound_email_cleanup: bool = False,
    ) -> Dict[str, Any]:
        """
        同步单个 Team 的信息

        Args:
            team_id: Team ID
            db_session: 数据库会话
            force_refresh: 是否强制刷新 Token
            enforce_bound_email_cleanup: 是否在刷新时按邮箱白名单自动清理非保护邮箱

        Returns:
            结果字典,包含 success, message, error
        """
        try:
            # 1. 查询 Team
            stmt = select(Team).where(Team.id == team_id)
            result = await db_session.execute(stmt)
            team = result.scalar_one_or_none()

            if not team:
                return {
                    "success": False,
                    "message": None,
                    "error": f"Team ID {team_id} 不存在"
                }

            await self._emit_progress(progress_callback, "load_team", "加载 Team 信息", team)

            # 2. 确保 AT Token 有效
            await self._emit_progress(progress_callback, "ensure_token", "校验 / 刷新 Token", team)
            access_token = await self.ensure_access_token(team, db_session, force_refresh=force_refresh)
            if not access_token:
                if team.status == "banned":
                    return {
                        "success": False,
                        "message": None,
                        "error": "Team 账号已封禁/失效 (token_invalidated)",
                        "error_code": "token_invalidated"
                    }
                return {
                    "success": False,
                    "message": None,
                    "error": "Token 已过期且无法刷新",
                    "error_code": "token_refresh_failed"
                }

            # 2.5 校验 Token 所属用户是否正确 (安全兜底)
            token_email = self.jwt_parser.extract_email(access_token)
            if token_email and team.email and token_email.lower() != team.email.lower():
                logger.error(f"Team {team_id} Token 邮箱不匹配: 预期 {team.email}, 实际 {token_email}")
                return {
                    "success": False,
                    "message": None,
                    "error": f"刷新出的账号身份 ({token_email}) 与原账号 ({team.email}) 不符，刷新已中止以防止数据污染。这可能是由于浏览器 Session 污染导致，建议清理 ST 后重新导入。"
                }

            # 3. 获取账户信息
            await self._emit_progress(progress_callback, "fetch_account_info", "拉取账户信息", team)
            account_result = await self.chatgpt_service.get_account_info(
                access_token,
                db_session,
                identifier=team.email
            )

            if not account_result["success"]:
                # 如果是 Token 过期，尝试在此处自动重试一次
                error_msg_raw = str(account_result.get("error", "")).lower()
                is_token_expired = account_result.get("error_code") == "token_expired" or "token_expired" in error_msg_raw or "token is expired" in error_msg_raw

                # 调用通用的错误处理逻辑 (包含标记封禁、累计错误次数、后台刷新等)
                await self._handle_api_error(account_result, team, db_session)

                if is_token_expired:
                    logger.info(f"Team {team.id} 同步时发现 Token 过期，尝试立即刷新并重试...")
                    new_token = await self.ensure_access_token(team, db_session, force_refresh=True)
                    if new_token:
                        # 2.6 重试后的 AT 也需要校验身份 (安全兜底)
                        new_token_email = self.jwt_parser.extract_email(new_token)
                        if new_token_email and team.email and new_token_email.lower() != team.email.lower():
                            logger.error(f"Team {team_id} 重试刷新 Token 邮箱不匹配: 预期 {team.email}, 实际 {new_token_email}")
                            return {
                                "success": False,
                                "message": None,
                                "error": f"刷新出的账号身份 ({new_token_email}) 与原账号 ({team.email}) 不符。同步已中止。",
                                "error_code": "token_identity_mismatch"
                            }

                        # 使用新 Token 再次尝试
                        account_result = await self.chatgpt_service.get_account_info(new_token, db_session, identifier=team.email)
                        if account_result["success"]:
                            logger.info(f"Team {team.id} 自动刷新 Token 后重试同步成功")
                        else:
                            # 刷新成功但请求依然失败，标记为过期/异常
                            logger.error(f"Team {team.id} Token 刷新成功但获取账户信息仍失败，标记为 expired")
                            team.status = "expired"
                            if not db_session.in_transaction():
                                await db_session.commit()
                            return {
                                "success": False,
                                "message": None,
                                "error": f"Token 刷新成功但获取账户信息仍失败 (status 401)",
                                "error_code": account_result.get("error_code") or "account_info_failed_after_refresh"
                            }
                    else:
                        # 刷新失败，标记为过期
                        logger.error(f"Team {team.id} Token 刷新失败，标记为 expired")
                        team.status = "expired"
                        if not db_session.in_transaction():
                            await db_session.commit()
                        return {
                            "success": False,
                            "message": None,
                            "error": "Token 已过期且无法刷新",
                            "error_code": "token_refresh_failed"
                        }
                else:
                    # 其他非 Token 过期导致的错误
                    error_msg = account_result.get("error", "未知错误")
                    if account_result.get("error_code") == "account_deactivated":
                        error_msg = "账号已封禁 (account_deactivated)"
                    elif account_result.get("error_code") == "token_invalidated":
                        error_msg = "账号已封禁/失效 (token_invalidated)"
                    elif team.status == "error":
                        error_msg = "账号连续多次同步失败，已标记异常"
                        
                    return {
                        "success": False,
                        "message": None,
                        "error": error_msg,
                        "error_code": account_result.get("error_code")
                    }

            # 4. 查找当前使用的 account
            team_accounts = account_result["accounts"]
            current_account = None

            for acc in team_accounts:
                if acc["account_id"] == team.account_id:
                    current_account = acc
                    break

            if not current_account:
                # 如果当前 account_id 不存在,使用第一个活跃的
                for acc in team_accounts:
                    if acc["has_active_subscription"]:
                        current_account = acc
                        break

                if not current_account and team_accounts:
                    current_account = team_accounts[0]

            if not current_account:
                team.status = "error"
                await db_session.commit()
                return {
                    "success": False,
                    "message": None,
                    "error": "该 Token 没有关联任何 Team 账户"
                }

            cleanup_summary = {
                "removed_member_count": 0,
                "revoked_invite_count": 0,
                "failed_count": 0,
                "removed_member_emails": [],
                "revoked_invite_emails": [],
                "failed_items": [],
                "attempted": False,
            }
            cleanup_record_id = None

            async def handle_member_fetch_failure(
                fetch_result: Dict[str, Any],
                target_label: str,
                after_cleanup: bool = False
            ) -> Dict[str, Any]:
                if await self._handle_api_error(fetch_result, team, db_session):
                    error_msg = fetch_result.get("error", "未知错误")
                    if fetch_result.get("error_code") == "account_deactivated":
                        error_msg = "账号已封禁 (account_deactivated)"
                    elif fetch_result.get("error_code") == "token_invalidated":
                        error_msg = "账号已封禁/失效 (token_invalidated)"

                    if after_cleanup:
                        error_msg = f"自动清理后重新获取{target_label}失败: {error_msg}"

                    return {
                        "success": False,
                        "message": None,
                        "error": error_msg,
                        "error_code": fetch_result.get("error_code"),
                        "cleanup_removed_member_count": cleanup_summary["removed_member_count"],
                        "cleanup_revoked_invite_count": cleanup_summary["revoked_invite_count"],
                        "cleanup_failed_count": cleanup_summary["failed_count"],
                        "cleanup_removed_member_emails": cleanup_summary["removed_member_emails"],
                        "cleanup_revoked_invite_emails": cleanup_summary["revoked_invite_emails"],
                        "cleanup_failed_items": cleanup_summary["failed_items"],
                        "cleanup_record_id": cleanup_record_id,
                    }

                team.error_count = (team.error_count or 0) + 1
                if team.error_count >= 3:
                    logger.error(
                        "Team %s 获取%s连续失败 %s 次，更新状态为 error",
                        team.id,
                        target_label,
                        team.error_count,
                    )
                    team.status = "error"
                await db_session.commit()

                error_prefix = "自动清理后重新获取" if after_cleanup else "获取"
                return {
                    "success": False,
                    "message": None,
                    "error": f"{error_prefix}{target_label}失败: {fetch_result.get('error')} (错误次数: {team.error_count})",
                    "error_code": fetch_result.get("error_code"),
                    "cleanup_removed_member_count": cleanup_summary["removed_member_count"],
                    "cleanup_revoked_invite_count": cleanup_summary["revoked_invite_count"],
                    "cleanup_failed_count": cleanup_summary["failed_count"],
                    "cleanup_removed_member_emails": cleanup_summary["removed_member_emails"],
                    "cleanup_revoked_invite_emails": cleanup_summary["revoked_invite_emails"],
                    "cleanup_failed_items": cleanup_summary["failed_items"],
                    "cleanup_record_id": cleanup_record_id,
                }

            # 5. 获取成员列表 (包含已加入和待加入)
            await self._emit_progress(progress_callback, "fetch_members", "拉取成员 / 邀请列表", team)
            members_result = await self.chatgpt_service.get_members(
                access_token,
                current_account["account_id"],
                db_session,
                identifier=team.email
            )
            
            invites_result = await self.chatgpt_service.get_invites(
                access_token,
                current_account["account_id"],
                db_session,
                identifier=team.email
            )

            if not members_result["success"]:
                return await handle_member_fetch_failure(members_result, "成员列表")

            if not invites_result["success"]:
                return await handle_member_fetch_failure(invites_result, "邀请列表")

            member_state = self._build_member_state_from_results(
                members_result=members_result,
                invites_result=invites_result,
            )
            all_member_emails = member_state["all_member_emails"]
            joined_member_emails = member_state["joined_member_emails"]
            invited_member_emails = member_state["invited_member_emails"]
            current_members = member_state["current_members"]

            cleanup_allowed_emails = None
            cleanup_scope_label = "Team"
            should_cleanup_team = enforce_bound_email_cleanup or (team.team_type == TEAM_TYPE_WARRANTY)

            if should_cleanup_team:
                await self._backfill_manual_warranty_whitelist_from_snapshots(team, db_session)

                cleanup_allowed_emails = await self._get_email_cleanup_allowed_emails(db_session)
                cleanup_summary = await self._cleanup_non_bound_team_emails(
                    team=team,
                    access_token=access_token,
                    account_id=current_account["account_id"],
                    members_result=members_result,
                    invites_result=invites_result,
                    db_session=db_session,
                    allowed_emails=cleanup_allowed_emails,
                    cleanup_scope_label=cleanup_scope_label,
                )

                if cleanup_summary["attempted"]:
                    try:
                        cleanup_record = await team_cleanup_record_service.create_record(
                            db_session=db_session,
                            team_id=team.id,
                            team_email=team.email,
                            team_name=current_account.get("name") or team.team_name,
                            team_account_id=current_account.get("account_id") or team.account_id,
                            cleanup_summary=cleanup_summary,
                        )
                        if cleanup_record:
                            cleanup_record_id = cleanup_record.id
                    except Exception as cleanup_record_error:
                        logger.error(
                            "写入 Team 自动清理记录失败: team_id=%s error=%s",
                            team.id,
                            cleanup_record_error,
                        )

                    members_result = await self.chatgpt_service.get_members(
                        access_token,
                        current_account["account_id"],
                        db_session,
                        identifier=team.email,
                    )
                    invites_result = await self.chatgpt_service.get_invites(
                        access_token,
                        current_account["account_id"],
                        db_session,
                        identifier=team.email,
                    )

                    if not members_result["success"]:
                        return await handle_member_fetch_failure(
                            members_result,
                            "成员列表",
                            after_cleanup=True,
                        )

                    if not invites_result["success"]:
                        return await handle_member_fetch_failure(
                            invites_result,
                            "邀请列表",
                            after_cleanup=True,
                        )

                    member_state = self._build_member_state_from_results(
                        members_result=members_result,
                        invites_result=invites_result,
                    )
                    all_member_emails = member_state["all_member_emails"]
                    joined_member_emails = member_state["joined_member_emails"]
                    invited_member_emails = member_state["invited_member_emails"]
                    current_members = member_state["current_members"]

            # 6. 解析过期时间
            expires_at = None
            if current_account["expires_at"]:
                try:
                    expires_at = datetime.fromisoformat(
                        current_account["expires_at"].replace("+00:00", "")
                    )
                except Exception as e:
                    logger.warning(f"解析过期时间失败: {e}")

            # 7.5 获取账户设置 (包含 beta_settings)
            settings_result = await self.chatgpt_service.get_account_settings(
                access_token,
                current_account["account_id"],
                db_session,
                identifier=team.email
            )
            device_code_auth_enabled = team.device_code_auth_enabled
            if settings_result["success"]:
                beta_settings = settings_result["data"].get("beta_settings", {})
                device_code_auth_enabled = beta_settings.get("codex_device_code_auth", False)

            # 7. 确定状态
            status = "active"
            if current_members >= team.max_members:
                status = "full"
            elif expires_at and expires_at < datetime.now():
                status = "expired"
            
            # 8. 更新 Team 信息
            await self._emit_progress(progress_callback, "persist_result", "写回同步结果", team)
            team.account_id = current_account["account_id"]
            team.team_name = current_account["name"]
            team.plan_type = current_account["plan_type"]
            team.subscription_plan = current_account["subscription_plan"]
            team.account_role = current_account.get("account_user_role")
            team.expires_at = expires_at
            team.current_members = current_members
            team.status = status
            team.device_code_auth_enabled = device_code_auth_enabled
            if status == "active":
                self._clear_warranty_team_unavailable(team)
            team.error_count = 0  # 同步成功，重置错误次数
            team.last_sync = get_now()
            await self._sync_team_member_snapshots(
                team=team,
                joined_member_emails=joined_member_emails,
                invited_member_emails=invited_member_emails,
                db_session=db_session
            )

            if not db_session.in_transaction():
                await db_session.commit()
            else:
                await db_session.flush()

            cleanup_summary_text = self._build_cleanup_summary_text(cleanup_summary)
            success_message = f"同步成功,当前成员数: {current_members}"
            if cleanup_summary_text:
                success_message = f"{success_message}；{cleanup_summary_text}"

            logger.info(
                "Team 同步成功: ID %s, 成员数 %s, cleanup=%s",
                team_id,
                current_members,
                cleanup_summary_text or "无",
            )

            return {
                "success": True,
                "message": success_message,
                "member_emails": list(all_member_emails),
                "cleanup_removed_member_count": cleanup_summary["removed_member_count"],
                "cleanup_revoked_invite_count": cleanup_summary["revoked_invite_count"],
                "cleanup_failed_count": cleanup_summary["failed_count"],
                "cleanup_removed_member_emails": cleanup_summary["removed_member_emails"],
                "cleanup_revoked_invite_emails": cleanup_summary["revoked_invite_emails"],
                "cleanup_failed_items": cleanup_summary["failed_items"],
                "cleanup_record_id": cleanup_record_id,
                "error": None
            }

        except Exception as e:
            await db_session.rollback()
            logger.error(f"Team 同步失败: {e}")
            return {
                "success": False,
                "message": None,
                "error": f"同步失败: {str(e)}"
            }

    async def refresh_team_state(
        self,
        team_id: int,
        db_session: AsyncSession,
        force_refresh: bool = False,
        progress_callback: ProgressCallback = None,
        source: str = SOURCE_UNKNOWN,
    ) -> Dict[str, Any]:
        """
        统一刷新 Team 后台状态。

        所有主动/自动刷新入口都应调用本方法，确保成员数、成员快照、
        状态、自动清理机制、刷新记录和每 Team 自动刷新计时使用同一套语义。
        """
        refresh_result = await self.sync_team_info(
            team_id,
            db_session,
            force_refresh=force_refresh,
            progress_callback=progress_callback,
            enforce_bound_email_cleanup=True,
        )
        refreshed_team = await db_session.get(Team, team_id)
        if not refreshed_team:
            return refresh_result

        refreshed_at = get_now()
        refreshed_team.last_refresh_at = refreshed_at

        try:
            refresh_record = await team_refresh_record_service.create_record(
                db_session=db_session,
                team=refreshed_team,
                source=source,
                force_refresh=force_refresh,
                refresh_result=refresh_result,
            )
            return {
                **refresh_result,
                "refresh_record_id": refresh_record.id,
                "last_refresh_at": refreshed_at.isoformat(),
            }
        except Exception as record_error:
            logger.error(
                "写入 Team 刷新记录失败: team_id=%s source=%s error=%s",
                team_id,
                source,
                record_error,
            )
            return {
                **refresh_result,
                "last_refresh_at": refreshed_at.isoformat(),
            }

    async def sync_all_teams(
        self,
        db_session: AsyncSession
    ) -> Dict[str, Any]:
        """
        同步所有 Team 的信息

        Args:
            db_session: 数据库会话

        Returns:
            结果字典,包含 success, total, success_count, failed_count, results
        """
        try:
            # 1. 查询所有 Team
            stmt = select(Team)
            result = await db_session.execute(stmt)
            teams = result.scalars().all()

            if not teams:
                return {
                    "success": True,
                    "total": 0,
                    "success_count": 0,
                    "failed_count": 0,
                    "results": [],
                    "error": None
                }

            # 2. 逐个同步
            results = []
            success_count = 0
            failed_count = 0

            for team in teams:
                result = await self.refresh_team_state(
                    team.id,
                    db_session,
                    source=SOURCE_ADMIN_BATCH,
                )

                if result["success"]:
                    success_count += 1
                else:
                    failed_count += 1

                results.append({
                    "team_id": team.id,
                    "email": team.email,
                    "success": result["success"],
                    "message": result["message"],
                    "error": result["error"]
                })

            logger.info(f"批量同步完成: 总数 {len(teams)}, 成功 {success_count}, 失败 {failed_count}")

            return {
                "success": True,
                "total": len(teams),
                "success_count": success_count,
                "failed_count": failed_count,
                "results": results,
                "error": None
            }

        except Exception as e:
            logger.error(f"批量同步失败: {e}")
            return {
                "success": False,
                "total": 0,
                "success_count": 0,
                "failed_count": 0,
                "results": [],
                "error": f"批量同步失败: {str(e)}"
            }

    async def get_team_members(
        self,
        team_id: int,
        db_session: AsyncSession
    ) -> Dict[str, Any]:
        """
        获取 Team 成员列表

        Args:
            team_id: Team ID
            db_session: 数据库会话

        Returns:
            结果字典,包含 success, members, total, error
        """
        try:
            # 1. 查询 Team
            stmt = select(Team).where(Team.id == team_id)
            result = await db_session.execute(stmt)
            team = result.scalar_one_or_none()

            if not team:
                return {
                    "success": False,
                    "members": [],
                    "total": 0,
                    "error": f"Team ID {team_id} 不存在"
                }

            # 2. 确保 AT Token 有效
            access_token = await self.ensure_access_token(team, db_session)
            if not access_token:
                return {
                    "success": False,
                    "members": [],
                    "total": 0,
                    "error": "Token 已过期且无法刷新"
                }

            # 3. 调用 ChatGPT API 获取成员列表
            members_result = await self.chatgpt_service.get_members(
                access_token,
                team.account_id,
                db_session,
                identifier=team.email
            )

            if not members_result["success"]:
                # 检查是否封号或 Token 失效
                if await self._handle_api_error(members_result, team, db_session):
                    error_msg = members_result.get("error", "未知错误")
                    if members_result.get("error_code") == "account_deactivated":
                        error_msg = "账号已封禁 (account_deactivated)"
                    elif members_result.get("error_code") == "token_invalidated":
                        error_msg = "Token 已失效 (token_invalidated)"
                        
                    return {
                        "success": False,
                        "members": [],
                        "total": 0,
                        "error": error_msg
                    }

                return {
                    "success": False,
                    "members": [],
                    "total": 0,
                    "error": f"获取成员列表失败: {members_result['error']}"
                }

            # 4. 调用 ChatGPT API 获取邀请列表
            invites_result = await self.chatgpt_service.get_invites(
                access_token,
                team.account_id,
                db_session,
                identifier=team.email
            )
            
            if not invites_result["success"]:
                # 检查是否封号或 Token 失效
                if await self._handle_api_error(invites_result, team, db_session):
                    error_msg = invites_result.get("error", "未知错误")
                    if invites_result.get("error_code") == "account_deactivated":
                        error_msg = "账号已封禁 (account_deactivated)"
                    elif invites_result.get("error_code") == "token_invalidated":
                        error_msg = "Token 已失效 (token_invalidated)"
                        
                    return {
                        "success": False,
                        "members": [],
                        "total": 0,
                        "error": error_msg
                    }

            # 5. 合并列表并统一格式
            all_members = []
            
            # 处理已加入成员
            for m in members_result["members"]:
                all_members.append({
                    "user_id": m.get("id"),
                    "email": m.get("email"),
                    "name": m.get("name"),
                    "role": m.get("role"),
                    "added_at": m.get("created_time"),
                    "status": "joined"
                })
            
            # 处理待加入成员
            if invites_result["success"]:
                for inv in invites_result["items"]:
                    all_members.append({
                        "user_id": None, # 邀请还没有 user_id
                        "email": inv.get("email_address"),
                        "name": None,
                        "role": inv.get("role"),
                        "added_at": inv.get("created_time"),
                        "status": "invited"
                    })

            logger.info(f"获取 Team {team_id} 成员列表成功: 共 {len(all_members)} 个成员 (已加入: {members_result['total']})")

            # 6. 请求成功，重置错误状态
            await self._reset_error_status(team, db_session)

            return {
                "success": True,
                "members": all_members,
                "total": len(all_members),
                "error": None
            }

        except Exception as e:
            logger.error(f"获取成员列表失败: {e}")
            return {
                "success": False,
                "members": [],
                "total": 0,
                "error": f"获取成员列表失败: {str(e)}"
            }

    async def revoke_team_invite(
        self,
        team_id: int,
        email: str,
        db_session: AsyncSession
    ) -> Dict[str, Any]:
        """
        撤回 Team 邀请

        Args:
            team_id: Team ID
            email: 邀请邮箱
            db_session: 数据库会话

        Returns:
            结果字典,包含 success, message, error
        """
        try:
            # 1. 查询 Team
            stmt = select(Team).where(Team.id == team_id)
            result = await db_session.execute(stmt)
            team = result.scalar_one_or_none()

            if not team:
                return {
                    "success": False,
                    "message": None,
                    "error": f"Team ID {team_id} 不存在"
                }

            # 2. 确保 AT Token 有效
            access_token = await self.ensure_access_token(team, db_session)
            if not access_token:
                return {
                    "success": False,
                    "message": None,
                    "error": "Token 已过期且无法刷新"
                }

            # 3. 调用 ChatGPT API 撤回邀请
            revoke_result = await self.chatgpt_service.delete_invite(
                access_token,
                team.account_id,
                email,
                db_session,
                identifier=team.email
            )

            if not revoke_result["success"]:
                # 检查是否封号或 Token 失效
                if await self._handle_api_error(revoke_result, team, db_session):
                    error_msg = revoke_result.get("error", "未知错误")
                    if revoke_result.get("error_code") == "account_deactivated":
                        error_msg = "账号已封禁 (account_deactivated)"
                    elif revoke_result.get("error_code") == "token_invalidated":
                        error_msg = "Token 已失效 (token_invalidated)"
                        
                    return {
                        "success": False,
                        "message": None,
                        "error": error_msg
                    }

                return {
                    "success": False,
                    "message": None,
                    "error": f"撤回邀请失败: {revoke_result['error']}"
                }

            # 4. 更新成员数 (不再手动 -1，同步最新数据)
            await self.refresh_team_state(
                team_id,
                db_session,
                source=SOURCE_ADMIN_MEMBER,
            )

            await db_session.commit()

            logger.info(f"撤回邀请成功: {email} from Team {team_id}")

            # 5. 请求成功，重置错误状态
            await self._reset_error_status(team, db_session)

            return {
                "success": True,
                "message": f"已撤回对 {email} 的邀请",
                "error": None
            }

        except Exception as e:
            await db_session.rollback()
            logger.error(f"撤回邀请失败: {e}")
            return {
                "success": False,
                "message": None,
                "error": f"撤回邀请失败: {str(e)}"
            }

    async def add_team_member(
        self,
        team_id: int,
        email: str,
        db_session: AsyncSession,
        source: str = SOURCE_ADMIN_MEMBER,
    ) -> Dict[str, Any]:
        """
        添加 Team 成员

        Args:
            team_id: Team ID
            email: 成员邮箱
            db_session: 数据库会话

        Returns:
            结果字典,包含 success, message, error
        """
        try:
            # 1. 查询 Team
            stmt = select(Team).where(Team.id == team_id)
            result = await db_session.execute(stmt)
            team = result.scalar_one_or_none()

            if not team:
                return {
                    "success": False,
                    "message": None,
                    "error": f"Team ID {team_id} 不存在"
                }

            refresh_result = await self.refresh_team_state(
                team_id,
                db_session,
                source=source,
            )
            await db_session.commit()
            if not refresh_result.get("success"):
                return {
                    "success": False,
                    "message": None,
                    "error": refresh_result.get("error") or "刷新 Team 状态失败",
                    "allow_try_next_team": bool(refresh_result.get("allow_try_next_team")),
                }

            # 2. 检查 Team 状态
            if team.status == "full":
                return {
                    "success": False,
                    "message": None,
                    "error": "Team 已满,无法添加成员",
                    "allow_try_next_team": True
                }

            if team.status == "expired":
                return {
                    "success": False,
                    "message": None,
                    "error": "Team 已过期,无法添加成员"
                }

            # 3. 确保 AT Token 有效
            access_token = await self.ensure_access_token(team, db_session)
            if not access_token:
                return {
                    "success": False,
                    "message": None,
                    "error": "Token 已过期且无法刷新"
                }

            # 4. 调用 ChatGPT API 发送邀请
            invite_result = await self.chatgpt_service.send_invite(
                access_token,
                team.account_id,
                email,
                db_session,
                identifier=team.email
            )

            if not invite_result["success"]:
                # 检查是否封号或 Token 失效
                if await self._handle_api_error(invite_result, team, db_session):
                    error_msg = invite_result.get("error", "未知错误")
                    if invite_result.get("error_code") == "account_deactivated":
                        error_msg = "账号已封禁 (account_deactivated)"
                    elif invite_result.get("error_code") == "token_invalidated":
                        error_msg = "Token 已失效 (token_invalidated)"

                    allow_try_next_team = bool(
                        team.status == "full"
                        or self._is_team_full_error_message(error_msg)
                    )

                    return {
                        "success": False,
                        "message": None,
                        "error": error_msg,
                        "allow_try_next_team": allow_try_next_team
                    }

                return {
                    "success": False,
                    "message": None,
                    "error": f"发送邀请失败: {invite_result['error']}"
                }

            invite_data = invite_result.get("data", {})
            if "account_invites" in invite_data and not invite_data.get("account_invites"):
                # 记录异常状态
                await self._handle_api_error({"success": False, "error": "官方拦截下发(响应空列表)", "error_code": "ghost_success"}, team, db_session)
                return {
                    "success": False,
                    "message": None,
                    "error": "Team账号受限: 官方拦截下发(响应空列表)，请检查账单/风控状态",
                    "error_code": "invite_intercepted_empty_list",
                    "allow_try_next_team": True
                }

            await self._ensure_manual_email_whitelist(
                email,
                db_session,
                last_warranty_team_id=team.id,
            )

            # 5. 更新成员数并二次校验邀请是否真的生效 (循环检测 3 次，防止接口返回 200 但实际延迟入库)
            is_verified = False
            for i in range(3):
                await asyncio.sleep(5)
                sync_res = await self.refresh_team_state(
                    team_id,
                    db_session,
                    source=source,
                )
                await db_session.commit()
                member_emails = [m.lower() for m in sync_res.get("member_emails", [])]
                if email.lower() in member_emails:
                    is_verified = True
                    logger.info(f"Team {team_id} [add_member] 同步确认成功 (尝试第 {i+1} 次)")
                    break
                if i < 2:
                    logger.warning(f"Team {team_id} [add_member] 尚未见到成员 {email}，准备第 {i+2} 次重试...")
            
            if not is_verified:
                logger.error(f"检测到“虚假成功”: Team {team_id} 发送邀请返回成功，但经过 3 次同步校验均未见该邮箱 {email}")
                # 标记错误
                await self._handle_api_error({"success": False, "error": "邀请发送成功但同步列表未见成员", "error_code": "ghost_success"}, team, db_session)
                return {
                    "success": False,
                    "message": None,
                    "error": "邀请发送成功但 3 次同步成员列表校验均失败，该 Team 账号可能存在延迟或异常。建议稍后手动同步。"
                }

            await db_session.commit()

            logger.info(f"添加成员成功: {email} -> Team {team_id}")

            # 6. 请求成功，重置错误状态
            if team.status == "active":
                self._clear_warranty_team_unavailable(team)
            await self._reset_error_status(team, db_session)

            return {
                "success": True,
                "message": f"邀请已发送到 {email}",
                "error": None
            }

        except Exception as e:
            await db_session.rollback()
            logger.error(f"添加成员失败: {e}")
            return {
                "success": False,
                "message": None,
                "error": f"添加成员失败: {str(e)}"
            }

    async def delete_team_member(
        self,
        team_id: int,
        user_id: str,
        db_session: AsyncSession,
        source: str = SOURCE_ADMIN_MEMBER,
    ) -> Dict[str, Any]:
        """
        删除 Team 成员

        Args:
            team_id: Team ID
            user_id: 用户 ID (格式: user-xxx)
            db_session: 数据库会话

        Returns:
            结果字典,包含 success, message, error
        """
        try:
            # 1. 查询 Team
            stmt = select(Team).where(Team.id == team_id)
            result = await db_session.execute(stmt)
            team = result.scalar_one_or_none()

            if not team:
                return {
                    "success": False,
                    "message": None,
                    "error": f"Team ID {team_id} 不存在"
                }

            # 2. 确保 AT Token 有效
            access_token = await self.ensure_access_token(team, db_session)
            if not access_token:
                return {
                    "success": False,
                    "message": None,
                    "error": "Token 已过期且无法刷新"
                }

            # 3. 调用 ChatGPT API 删除成员
            delete_result = await self.chatgpt_service.delete_member(
                access_token,
                team.account_id,
                user_id,
                db_session,
                identifier=team.email
            )

            if not delete_result["success"]:
                # 检查是否封号或 Token 失效
                if await self._handle_api_error(delete_result, team, db_session):
                    error_msg = delete_result.get("error", "未知错误")
                    if delete_result.get("error_code") == "account_deactivated":
                        error_msg = "账号已封禁 (account_deactivated)"
                    elif delete_result.get("error_code") == "token_invalidated":
                        error_msg = "Token 已失效 (token_invalidated)"
                        
                    return {
                        "success": False,
                        "message": None,
                        "error": error_msg
                    }

                return {
                    "success": False,
                    "message": None,
                    "error": f"删除成员失败: {delete_result['error']}"
                }

            # 4. 更新成员数 (不再手动 -1，同步最新数据)
            await self.refresh_team_state(
                team_id,
                db_session,
                source=source,
            )

            await db_session.commit()

            logger.info(f"删除成员成功: {user_id} from Team {team_id}")

            # 5. 请求成功，重置错误状态
            await self._reset_error_status(team, db_session)

            return {
                "success": True,
                "message": "成员已删除",
                "error": None
            }

        except Exception as e:
            await db_session.rollback()
            logger.error(f"删除成员失败: {e}")
            return {
                "success": False,
                "message": None,
                "error": f"删除成员失败: {str(e)}"
            }

    async def enable_device_code_auth(
        self,
        team_id: int,
        db_session: AsyncSession,
        progress_callback: ProgressCallback = None
    ) -> Dict[str, Any]:
        """
        开启 Team 的设备代码身份验证
        """
        team = None
        try:
            # 1. 查询 Team
            stmt = select(Team).where(Team.id == team_id)
            result = await db_session.execute(stmt)
            team = result.scalar_one_or_none()

            if not team:
                return {
                    "success": False,
                    "team_id": team_id,
                    "email": None,
                    "error": f"Team ID {team_id} 不存在"
                }

            # 2. 确保 AT Token 有效
            await self._emit_progress(progress_callback, "load_team", "加载 Team 信息", team)
            await self._emit_progress(progress_callback, "ensure_token", "校验 / 刷新 Token", team)
            access_token = await self.ensure_access_token(team, db_session)
            if not access_token:
                return {
                    "success": False,
                    "team_id": team_id,
                    "email": team.email,
                    "error": "Token 已过期且无法刷新"
                }

            # 3. 调用 ChatGPT API 开启功能
            await self._emit_progress(progress_callback, "toggle_feature", "调用开启验证接口", team)
            result = await self.chatgpt_service.toggle_beta_feature(
                access_token,
                team.account_id,
                "codex_device_code_auth",
                True,
                db_session,
                identifier=team.email
            )

            if not result["success"]:
                return {
                    "success": False,
                    "team_id": team_id,
                    "email": team.email,
                    "error": f"开启设备身份验证失败: {result.get('error', '未知错误')}"
                }

            # 更新数据库状态
            await self._emit_progress(progress_callback, "persist_result", "写回开启验证结果", team)
            team.device_code_auth_enabled = True
            await db_session.commit()

            logger.info(f"Team {team_id} ({team.email}) 开启设备身份验证成功")
            return {
                "success": True,
                "team_id": team_id,
                "email": team.email,
                "message": "设备代码身份验证开启成功"
            }

        except Exception as e:
            logger.error(f"开启设备身份验证失败: {e}")
            return {
                "success": False,
                "team_id": team_id,
                "email": team.email if team else None,
                "error": f"异常: {str(e)}"
            }

    async def get_available_teams(
        self,
        db_session: AsyncSession,
        team_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        获取可用的 Team 列表 (用于用户兑换页面)

        Args:
            db_session: 数据库会话

        Returns:
            结果字典,包含 success, teams, error
        """
        try:
            # 查询 status='active' 且 current_members < max_members 的 Team
            capacity_expr = func.coalesce(Team.current_members, 0) + func.coalesce(Team.reserved_members, 0)
            stmt = select(Team).where(
                Team.status == "active",
                capacity_expr < Team.max_members,
                Team.import_status == IMPORT_STATUS_CLASSIFIED,
                or_(Team.warranty_unavailable.is_(False), Team.warranty_unavailable.is_(None)),
            )
            if team_type:
                stmt = stmt.where(Team.team_type == team_type)
            stmt = stmt.order_by(Team.id.asc())
            result = await db_session.execute(stmt)
            teams = result.scalars().all()

            # 构建返回数据 (不包含敏感信息)
            team_list = []
            for team in teams:
                team_list.append({
                    "id": team.id,
                    "team_type": team.team_type,
                    "team_name": team.team_name,
                    "current_members": team.current_members,
                    "max_members": team.max_members,
                    "expires_at": team.expires_at.isoformat() if team.expires_at else None,
                    "subscription_plan": team.subscription_plan
                })

            logger.info(f"获取可用 Team 列表成功: 共 {len(team_list)} 个")

            return {
                "success": True,
                "teams": team_list,
                "error": None
            }

        except Exception as e:
            logger.error(f"获取可用 Team 列表失败: {e}")
            return {
                "success": False,
                "teams": [],
                "error": f"获取列表失败: {str(e)}"
            }




    async def get_team_by_id(
        self,
        team_id: int,
        db_session: AsyncSession
    ) -> Dict[str, Any]:
        """
        根据 ID 获取 Team 详情

        Args:
            team_id: Team ID
            db_session: 数据库会话

        Returns:
            结果字典,包含 success, team, team_accounts, error
        """
        try:
            # 查询 Team (包含关联的 team_accounts)
            stmt = select(Team).where(Team.id == team_id).options(
                selectinload(Team.team_accounts)
            )
            result = await db_session.execute(stmt)
            team = result.scalar_one_or_none()

            if not team:
                return {
                    "success": False,
                    "team": None,
                    "team_accounts": [],
                    "error": f"Team ID {team_id} 不存在"
                }

            # 解密 Token
            access_token = ""
            refresh_token = ""
            session_token = ""
            try:
                if team.access_token_encrypted:
                    access_token = encryption_service.decrypt_token(team.access_token_encrypted)
                if team.refresh_token_encrypted:
                    refresh_token = encryption_service.decrypt_token(team.refresh_token_encrypted)
                if team.session_token_encrypted:
                    session_token = encryption_service.decrypt_token(team.session_token_encrypted)
            except Exception as e:
                logger.error(f"解密 Team {team_id} Token 失败: {e}")

            # 构建返回数据
            team_data = {
                "id": team.id,
                "email": team.email,
                "account_id": team.account_id,
                "access_token": access_token,
                "refresh_token": refresh_token,
                "session_token": session_token,
                "client_id": team.client_id or "",
                "team_name": team.team_name,
                "plan_type": team.plan_type,
                "subscription_plan": team.subscription_plan,
                "expires_at": team.expires_at.isoformat() if team.expires_at else None,
                "current_members": team.current_members,
                "max_members": team.max_members,
                "status": team.status,
                "device_code_auth_enabled": team.device_code_auth_enabled,
                "last_sync": team.last_sync.isoformat() if team.last_sync else None,
                "created_at": team.created_at.isoformat() if team.created_at else None
            }

            team_accounts_data = []
            for acc in team.team_accounts:
                team_accounts_data.append({
                    "id": acc.id,
                    "account_id": acc.account_id,
                    "account_name": acc.account_name,
                    "is_primary": acc.is_primary
                })

            logger.info(f"获取 Team {team_id} 详情成功")

            return {
                "success": True,
                "team": team_data,
                "team_accounts": team_accounts_data,
                "error": None
            }

        except Exception as e:
            logger.error(f"获取 Team 详情失败: {e}")
            return {
                "success": False,
                "team": None,
                "team_accounts": [],
                "error": f"获取 Team 详情失败: {str(e)}"
            }

    async def get_all_teams(
        self,
        db_session: AsyncSession,
        page: int = 1,
        per_page: int = 20,
        search: Optional[str] = None,
        status: Optional[str] = None,
        team_type: Optional[str] = None,
        import_status: Optional[str] = IMPORT_STATUS_CLASSIFIED,
        imported_by_user_id: Optional[int] = None,
        imported_only: bool = False,
        import_tag: Optional[str] = None,
        imported_from: Optional[datetime] = None,
        imported_to: Optional[datetime] = None,
        expires_from: Optional[datetime] = None,
        expires_to: Optional[datetime] = None,
        device_auth_enabled: Optional[bool] = None,
        members_min: Optional[int] = None,
        members_max: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        获取所有 Team 列表 (用于管理员页面)

        Args:
            db_session: 数据库会话
            page: 页码
            per_page: 每页数量
            search: 搜索关键词
            status: 状态过滤 (可选)

        Returns:
            结果字典,包含 success, teams, total, total_pages, current_page, error
        """
        try:
            normalized_import_tag = normalize_import_tag(import_tag)

            # 1. 构建查询语句
            stmt = select(Team)
            
            # 2. 如果有搜索词,添加过滤条件
            if search:
                from sqlalchemy import cast, String
                search_filter = f"%{search}%"
                stmt = stmt.where(
                    or_(
                        Team.email.ilike(search_filter),
                        Team.account_id.ilike(search_filter),
                        Team.team_name.ilike(search_filter),
                        cast(Team.id, String).ilike(search_filter)
                    )
                )

            # 3. 如果有状态过滤,添加过滤条件
            if status:
                stmt = stmt.where(Team.status == status)
                if status == "active":
                    stmt = stmt.where(
                        or_(Team.warranty_unavailable.is_(False), Team.warranty_unavailable.is_(None))
                    )

            if team_type:
                stmt = stmt.where(Team.team_type == team_type)

            if import_status:
                stmt = stmt.where(Team.import_status == import_status)

            if imported_by_user_id is not None:
                stmt = stmt.where(Team.imported_by_user_id == imported_by_user_id)

            if imported_only:
                stmt = stmt.where(Team.imported_by_user_id.is_not(None))

            if normalized_import_tag:
                stmt = stmt.where(Team.import_tag == normalized_import_tag)

            if imported_from:
                stmt = stmt.where(Team.created_at >= imported_from)

            if imported_to:
                stmt = stmt.where(Team.created_at <= imported_to)

            if expires_from:
                stmt = stmt.where(Team.expires_at >= expires_from)

            if expires_to:
                stmt = stmt.where(Team.expires_at <= expires_to)

            if device_auth_enabled is True:
                stmt = stmt.where(Team.device_code_auth_enabled.is_(True))
            elif device_auth_enabled is False:
                stmt = stmt.where(
                    or_(
                        Team.device_code_auth_enabled.is_(False),
                        Team.device_code_auth_enabled.is_(None),
                    )
                )

            if members_min is not None:
                stmt = stmt.where(Team.current_members >= members_min)

            if members_max is not None:
                stmt = stmt.where(Team.current_members <= members_max)

            # 4. 获取总数
            count_stmt = select(func.count()).select_from(stmt.subquery())
            count_result = await db_session.execute(count_stmt)
            total = count_result.scalar() or 0

            # 4. 计算分页
            import math
            total_pages = math.ceil(total / per_page) if total > 0 else 1
            if page < 1:
                page = 1
            if total_pages > 0 and page > total_pages:
                page = total_pages
            
            offset = (page - 1) * per_page

            # 5. 查询分页数据
            final_stmt = stmt.order_by(Team.created_at.desc()).limit(per_page).offset(offset)
            result = await db_session.execute(final_stmt)
            teams = result.scalars().all()

            team_ids = [team.id for team in teams]
            bound_codes_map = {}
            if team_ids:
                codes_stmt = select(RedemptionCode).where(RedemptionCode.bound_team_id.in_(team_ids)).order_by(
                    RedemptionCode.created_at.desc()
                )
                codes_result = await db_session.execute(codes_stmt)
                bound_codes = codes_result.scalars().all()

                code_values = [code.code for code in bound_codes]
                redemption_records_map = {}
                redemption_team_map = {}

                if code_values:
                    records_stmt = (
                        select(RedemptionRecord)
                        .where(RedemptionRecord.code.in_(code_values))
                        .order_by(RedemptionRecord.redeemed_at.desc())
                    )
                    records_result = await db_session.execute(records_stmt)
                    redemption_records = records_result.scalars().all()

                    redemption_team_ids = {record.team_id for record in redemption_records if record.team_id}
                    if redemption_team_ids:
                        redemption_team_stmt = select(Team).where(Team.id.in_(redemption_team_ids))
                        redemption_team_result = await db_session.execute(redemption_team_stmt)
                        redemption_team_map = {
                            team.id: team for team in redemption_team_result.scalars().all()
                        }

                    for record in redemption_records:
                        record_team = redemption_team_map.get(record.team_id)
                        redemption_records_map.setdefault(record.code, []).append({
                            "id": record.id,
                            "email": record.email,
                            "team_id": record.team_id,
                            "team_name": record_team.team_name if record_team else None,
                            "redeemed_at": record.redeemed_at.isoformat() if record.redeemed_at else None,
                            "is_warranty_redemption": record.is_warranty_redemption
                        })

                for code in bound_codes:
                    redemption_records_for_code = redemption_records_map.get(code.code, [])
                    bound_codes_map.setdefault(code.bound_team_id, []).append({
                        "code": code.code,
                        "status": code.status,
                        "has_warranty": bool(code.has_warranty),
                        "warranty_days": code.warranty_days,
                        "used_by_email": code.used_by_email,
                        "used_at": code.used_at.isoformat() if code.used_at else None,
                        "used_team_id": code.used_team_id,
                        "redemption_count": len(redemption_records_for_code),
                        "latest_redemption": redemption_records_for_code[0] if redemption_records_for_code else None,
                        "redemption_records": redemption_records_for_code
                    })

            # 构建返回数据
            team_list = []
            for team in teams:
                bound_codes_for_team = bound_codes_map.get(team.id, [])
                warranty_days_from_codes = sorted({
                    int(code["warranty_days"])
                    for code in bound_codes_for_team
                    if code.get("has_warranty") and code.get("warranty_days")
                })
                stored_warranty_days = getattr(team, "bound_code_warranty_days", None)
                if stored_warranty_days is not None and stored_warranty_days > 0:
                    bound_code_warranty_days = stored_warranty_days
                    bound_code_warranty_days_label = f"{stored_warranty_days} 天"
                elif len(warranty_days_from_codes) == 1:
                    bound_code_warranty_days = warranty_days_from_codes[0]
                    bound_code_warranty_days_label = f"{warranty_days_from_codes[0]} 天"
                elif len(warranty_days_from_codes) > 1:
                    bound_code_warranty_days = None
                    bound_code_warranty_days_label = "多种时长"
                else:
                    bound_code_warranty_days = None
                    bound_code_warranty_days_label = None
                review_status = team.import_status or IMPORT_STATUS_CLASSIFIED
                if review_status == IMPORT_STATUS_PENDING:
                    review_status_label = "待审核"
                    review_decision_label = "未审核"
                else:
                    review_status_label = "已审核"
                    review_decision_label = "控制台 Team"

                team_list.append({
                    "id": team.id,
                    "email": team.email,
                    "account_id": team.account_id,
                    "team_type": team.team_type,
                    "import_status": review_status,
                    "import_status_label": review_status_label,
                    "import_decision_label": review_decision_label,
                    "imported_by_user_id": team.imported_by_user_id,
                    "imported_by_username": team.imported_by_username,
                    "import_tag": team.import_tag,
                    "import_tag_label": get_import_tag_label(team.import_tag),
                    "bound_code_type": team.bound_code_type or TEAM_TYPE_STANDARD,
                    "bound_code_type_label": "质保" if (team.bound_code_type or TEAM_TYPE_STANDARD) == TEAM_TYPE_WARRANTY else "普通",
                    "bound_code_warranty_days": bound_code_warranty_days,
                    "bound_code_warranty_days_label": bound_code_warranty_days_label,
                    "team_name": team.team_name,
                    "plan_type": team.plan_type,
                    "subscription_plan": team.subscription_plan,
                    "expires_at": team.expires_at.isoformat() if team.expires_at else None,
                    "current_members": team.current_members,
                    "max_members": team.max_members,
                    "bound_code_count": len(bound_codes_for_team),
                    "bound_codes": bound_codes_for_team,
                    "status": team.status,
                    "warranty_unavailable": bool(getattr(team, "warranty_unavailable", False)),
                    "warranty_unavailable_reason": getattr(team, "warranty_unavailable_reason", None),
                    "warranty_unavailable_at": (
                        team.warranty_unavailable_at.isoformat()
                        if getattr(team, "warranty_unavailable_at", None)
                        else None
                    ),
                    "device_code_auth_enabled": getattr(team, 'device_code_auth_enabled', False),
                    "last_sync": team.last_sync.isoformat() if team.last_sync else None,
                    "last_refresh_at": team.last_refresh_at.isoformat() if team.last_refresh_at else None,
                    "created_at": team.created_at.isoformat() if team.created_at else None
                })

            logger.info(f"获取所有 Team 列表成功: 第 {page} 页, 共 {len(team_list)} 个 / 总数 {total}")

            return {
                "success": True,
                "teams": team_list,
                "total": total,
                "total_pages": total_pages,
                "current_page": page,
                "error": None
            }

        except Exception as e:
            logger.error(f"获取所有 Team 列表失败: {e}")
            return {
                "success": False,
                "teams": [],
                "error": f"获取所有 Team 列表失败: {str(e)}"
            }

    async def remove_invite_or_member(
        self,
        team_id: int,
        email: str,
        db_session: AsyncSession
    ) -> Dict[str, Any]:
        """
        撤回邀请或删除成员 (根据邮箱自动判断)

        Args:
            team_id: Team ID
            email: 目标邮箱
            db_session: 数据库会话

        Returns:
            结果字典
        """
        try:
            # 1. 获取最新成员和邀请列表
            members_result = await self.get_team_members(team_id, db_session)
            if not members_result["success"]:
                return members_result

            all_members = members_result["members"]
            
            # 2. 查找匹配的记录
            target = next((m for m in all_members if m["email"] == email), None)
            
            if not target:
                logger.warning(f"在 Team {team_id} 中未找到邮箱为 {email} 的成员或邀请")
                # 即使没找到也返回成功，以便上层逻辑继续更新记录
                return {"success": True, "message": "成员已不存在"}

            # 3. 根据状态执行删除
            if target["status"] == "joined":
                # 已加入，调用删除成员
                return await self.delete_team_member(team_id, target["user_id"], db_session)
            else:
                # 待加入，调用撤回邀请
                return await self.revoke_team_invite(team_id, email, db_session)

        except Exception as e:
            logger.error(f"撤回邀请或删除成员时发生异常: {e}")
            return {"success": False, "error": str(e)}

    async def delete_team(
        self,
        team_id: int,
        db_session: AsyncSession
    ) -> Dict[str, Any]:
        """
        删除 Team

        Args:
            team_id: Team ID
            db_session: 数据库会话

        Returns:
            结果字典,包含 success, message, error
        """
        try:
            # 1. 查询 Team
            stmt = select(Team).where(Team.id == team_id)
            result = await db_session.execute(stmt)
            team = result.scalar_one_or_none()

            if not team:
                return {
                    "success": False,
                    "message": None,
                    "error": f"Team ID {team_id} 不存在"
                }

            # 1.5 删除 Team 关联的兑换记录和兑换码
            codes_stmt = select(RedemptionCode.id).where(
                or_(
                    RedemptionCode.bound_team_id == team_id,
                    RedemptionCode.used_team_id == team_id
                )
            )
            codes_result = await db_session.execute(codes_stmt)
            code_ids = codes_result.scalars().all()
            deleted_code_count = len(code_ids)

            records_delete_stmt = delete(RedemptionRecord).where(RedemptionRecord.team_id == team_id)
            await db_session.execute(records_delete_stmt)

            if code_ids:
                codes_delete_stmt = delete(RedemptionCode).where(RedemptionCode.id.in_(code_ids))
                await db_session.execute(codes_delete_stmt)

            # 2. 删除 Team (级联删除 team_accounts 和 redemption_records)
            await db_session.delete(team)
            await db_session.commit()

            logger.info(f"删除 Team {team_id} 成功，并删除 %s 个关联兑换码", deleted_code_count)

            return {
                "success": True,
                "deleted_code_count": deleted_code_count,
                "message": f"Team 已删除，并删除 {deleted_code_count} 个关联兑换码",
                "error": None
            }

        except Exception as e:
            await db_session.rollback()
            logger.error(f"删除 Team 失败: {e}")
            return {
                "success": False,
                "message": None,
                "error": f"删除 Team 失败: {str(e)}"
            }

    async def get_total_available_seats(
        self,
        db_session: AsyncSession,
        team_type: Optional[str] = None
    ) -> int:
        """
        获取所有活跃 Team 的总剩余车位数
        """
        try:
            # 统计所有状态为 active 的 Team 的剩余位置
            occupied_expr = func.coalesce(Team.current_members, 0) + func.coalesce(Team.reserved_members, 0)
            stmt = select(func.sum(Team.max_members - occupied_expr)).where(
                Team.status == "active",
                occupied_expr < Team.max_members,
                Team.import_status == IMPORT_STATUS_CLASSIFIED,
                or_(Team.warranty_unavailable.is_(False), Team.warranty_unavailable.is_(None)),
            )
            if team_type:
                stmt = stmt.where(Team.team_type == team_type)
            result = await db_session.execute(stmt)
            return result.scalar() or 0
        except Exception as e:
            logger.error(f"获取总可用车位数失败: {e}")
            return 0

    async def get_stats(
        self,
        db_session: AsyncSession,
        team_type: Optional[str] = None,
        import_status: Optional[str] = IMPORT_STATUS_CLASSIFIED,
    ) -> Dict[str, int]:
        """获取 Team 统计信息"""
        try:
            # 总数
            total_stmt = select(func.count(Team.id))
            if team_type:
                total_stmt = total_stmt.where(Team.team_type == team_type)
            if import_status:
                total_stmt = total_stmt.where(Team.import_status == import_status)
            total_result = await db_session.execute(total_stmt)
            total = total_result.scalar() or 0
            
            # 可用 Team 数 (状态为 active 且未满)
            occupied_expr = func.coalesce(Team.current_members, 0) + func.coalesce(Team.reserved_members, 0)
            available_stmt = select(func.count(Team.id)).where(
                Team.status == "active",
                occupied_expr < Team.max_members
            )
            if team_type:
                available_stmt = available_stmt.where(Team.team_type == team_type)
            if import_status:
                available_stmt = available_stmt.where(Team.import_status == import_status)
            available_stmt = available_stmt.where(
                or_(Team.warranty_unavailable.is_(False), Team.warranty_unavailable.is_(None))
            )
            available_result = await db_session.execute(available_stmt)
            available = available_result.scalar() or 0

            # 所有席位统计为可进入成员位，不包含 Team 管理员自身占用的 owner 位。
            total_seats_expr = case(
                (
                    Team.max_members > TEAM_OWNER_RESERVED_SEATS,
                    Team.max_members - TEAM_OWNER_RESERVED_SEATS,
                ),
                else_=0,
            )
            total_seats_stmt = select(func.sum(total_seats_expr))
            if team_type:
                total_seats_stmt = total_seats_stmt.where(Team.team_type == team_type)
            if import_status:
                total_seats_stmt = total_seats_stmt.where(Team.import_status == import_status)
            total_seats_result = await db_session.execute(total_seats_stmt)
            total_seats = total_seats_result.scalar() or 0

            remaining_seats_stmt = select(func.sum(Team.max_members - occupied_expr)).where(
                Team.status == "active",
                occupied_expr < Team.max_members
            )
            if team_type:
                remaining_seats_stmt = remaining_seats_stmt.where(Team.team_type == team_type)
            if import_status:
                remaining_seats_stmt = remaining_seats_stmt.where(Team.import_status == import_status)
            remaining_seats_stmt = remaining_seats_stmt.where(
                or_(Team.warranty_unavailable.is_(False), Team.warranty_unavailable.is_(None))
            )
            remaining_seats_result = await db_session.execute(remaining_seats_stmt)
            remaining_seats = remaining_seats_result.scalar() or 0
            
            return {
                "total": total,
                "available": available,
                "total_seats": total_seats,
                "remaining_seats": remaining_seats
            }
        except Exception as e:
            logger.error(f"获取 Team 统计信息失败: {e}")
            return {
                "total": 0,
                "available": 0,
                "total_seats": 0,
                "remaining_seats": 0
            }


# 创建全局 Team 服务实例
team_service = TeamService()
