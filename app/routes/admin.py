"""
管理员路由
处理管理员面板的所有页面和操作
"""
import asyncio
import logging
from dataclasses import dataclass
from typing import Optional, List, Dict, Any, Callable, Awaitable
from urllib.parse import urlparse
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException, status, Request, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse, RedirectResponse
import json
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field, EmailStr

from app.database import get_db
from app.dependencies.auth import require_admin, require_team_import_admin, is_import_admin_user
from app.models import Team, RedemptionCode
from app.services.team import (
    TeamService,
    TEAM_TYPE_STANDARD,
    TEAM_TYPE_WARRANTY,
    IMPORT_STATUS_PENDING,
    IMPORT_STATUS_CLASSIFIED,
    CLASSIFY_TARGET_STANDARD,
    CLASSIFY_TARGET_WARRANTY_CODE,
    CLASSIFY_TARGET_WARRANTY_TEAM,
)
from app.services.team_cleanup_record import team_cleanup_record_service
from app.services.redemption import RedemptionService
from app.services.settings import settings_service
from app.services.warranty import warranty_service
from app.services.auth import auth_service
from app.utils.time_utils import get_now
from app.utils.storage import (
    build_customer_service_upload_url,
    customer_service_upload_exists,
    get_customer_service_upload_dir,
    is_customer_service_upload_url,
    resolve_customer_service_upload_display_url,
)

logger = logging.getLogger(__name__)

MAX_CUSTOMER_SERVICE_IMAGE_SIZE = 5 * 1024 * 1024
ALLOWED_CUSTOMER_SERVICE_IMAGE_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}

# 创建路由器
router = APIRouter(
    prefix="/admin",
    tags=["admin"]
)

# 服务实例
team_service = TeamService()
redemption_service = RedemptionService()


# 请求模型
class TeamImportRequest(BaseModel):
    """Team 导入请求"""
    import_type: str = Field(..., description="导入类型: single 或 batch")
    team_type: str = Field(TEAM_TYPE_STANDARD, description="Team 类型: standard 或 warranty")
    generate_warranty_codes: bool = Field(False, description="是否自动生成质保兑换码")
    warranty_days: int = Field(30, description="自动生成质保兑换码时的质保天数")
    access_token: Optional[str] = Field(None, description="AT Token (单个导入)")
    refresh_token: Optional[str] = Field(None, description="Refresh Token (单个导入)")
    session_token: Optional[str] = Field(None, description="Session Token (单个导入)")
    client_id: Optional[str] = Field(None, description="Client ID (单个导入)")
    email: Optional[str] = Field(None, description="邮箱 (单个导入)")
    account_id: Optional[str] = Field(None, description="Account ID (单个导入)")
    content: Optional[str] = Field(None, description="批量导入内容")


class AddMemberRequest(BaseModel):
    """添加成员请求"""
    email: str = Field(..., description="成员邮箱")


class CodeGenerateRequest(BaseModel):
    """兑换码生成请求"""
    type: str = Field(..., description="生成类型: single 或 batch")
    code: Optional[str] = Field(None, description="自定义兑换码 (单个生成)")
    count: Optional[int] = Field(None, description="生成数量 (批量生成)")
    expires_days: Optional[int] = Field(None, description="有效期天数")
    has_warranty: bool = Field(False, description="是否为质保兑换码")
    warranty_days: int = Field(30, description="质保天数")


class TeamUpdateRequest(BaseModel):
    """Team 更新请求"""
    email: Optional[str] = Field(None, description="新邮箱")
    account_id: Optional[str] = Field(None, description="新 Account ID")
    access_token: Optional[str] = Field(None, description="新 Access Token")
    refresh_token: Optional[str] = Field(None, description="新 Refresh Token")
    session_token: Optional[str] = Field(None, description="新 Session Token")
    client_id: Optional[str] = Field(None, description="新 Client ID")
    max_members: Optional[int] = Field(None, description="最大成员数")
    team_name: Optional[str] = Field(None, description="Team 名称")
    status: Optional[str] = Field(None, description="状态: active/full/expired/error/banned")


class TeamTransferRequest(BaseModel):
    """Team 类型转移请求"""
    target_team_type: str = Field(..., description="目标 Team 类型: standard 或 warranty")


class TeamClassifyRequest(BaseModel):
    """待分类 Team 归类请求"""
    target: str = Field(..., description="归类目标: standard / warranty_code / warranty_team")
    warranty_days: int = Field(30, description="质保兑换码天数")


class SubAdminCreateRequest(BaseModel):
    """创建子管理员请求"""
    username: str = Field(..., min_length=1, max_length=100, description="用户名")
    password: str = Field(..., min_length=6, description="密码")


class SubAdminToggleRequest(BaseModel):
    """启用/禁用子管理员请求"""
    is_active: bool = Field(..., description="是否启用")


class SubAdminResetPasswordRequest(BaseModel):
    """重置子管理员密码请求"""
    password: str = Field(..., min_length=6, description="新密码")


class CodeUpdateRequest(BaseModel):
    """兑换码更新请求"""
    has_warranty: bool = Field(..., description="是否为质保兑换码")
    warranty_days: Optional[int] = Field(None, description="质保天数")

class BulkCodeUpdateRequest(BaseModel):
    """批量兑换码更新请求"""
    codes: List[str] = Field(..., description="兑换码列表")
    has_warranty: bool = Field(..., description="是否为质保兑换码")
    warranty_days: Optional[int] = Field(None, description="质保天数")


class BulkCodeActionRequest(BaseModel):
    """批量兑换码操作请求"""
    codes: List[str] = Field(..., description="兑换码列表")


class CodeExportRequest(BaseModel):
    """兑换码导出请求"""
    codes: List[str] = Field(default_factory=list, description="勾选的兑换码列表")
    search: Optional[str] = Field(None, description="搜索关键词")
    status_filter: Optional[str] = Field(None, description="状态筛选")
    team_id: Optional[int] = Field(None, description="绑定的 Team ID")
    team_ids: List[int] = Field(default_factory=list, description="批量勾选的 Team ID 列表")
    export_format: str = Field("excel", description="导出格式: excel 或 text")


class BulkActionRequest(BaseModel):
    """批量操作请求"""
    ids: List[int] = Field(..., description="Team ID 列表")


class BulkTeamClassifyRequest(BulkActionRequest):
    """批量待分类 Team 归类请求"""
    target: str = Field(..., description="归类目标: standard / warranty_code / warranty_team")
    warranty_days: int = Field(30, description="质保兑换码天数")


class WarrantySuperCodeConfigRequest(BaseModel):
    code: str = Field("", description="超级兑换码")
    limit_value: int = Field(..., description="限制值")


class WarrantyEmailSaveRequest(BaseModel):
    entry_id: Optional[int] = Field(None, description="质保邮箱记录 ID")
    email: EmailStr = Field(..., description="质保邮箱")
    remaining_days: Optional[int] = Field(None, description="剩余天数")
    remaining_claims: int = Field(..., description="剩余次数")


class FrontAnnouncementSettingsRequest(BaseModel):
    """前台公告设置请求"""
    enabled: bool = Field(..., description="是否启用前台公告")
    content: str = Field("", description="公告内容", max_length=5000)


class CustomerServiceSettingsRequest(BaseModel):
    """前台客服设置请求"""
    enabled: bool = Field(..., description="是否启用前台客服模块")
    qr_code_url: str = Field("", description="客服二维码图片地址", max_length=2000)
    link_url: str = Field("", description="客服跳转链接", max_length=2000)
    link_text: str = Field("", description="客服链接文案", max_length=200)
    text_content: str = Field("", description="客服文字内容", max_length=5000)


@dataclass
class BatchActionJobState:
    job_id: str
    action: str
    stop_requested: bool = False


batch_action_jobs: Dict[str, BatchActionJobState] = {}

CLASSIFY_TARGETS = {
    CLASSIFY_TARGET_STANDARD,
    CLASSIFY_TARGET_WARRANTY_CODE,
    CLASSIFY_TARGET_WARRANTY_TEAM,
}


def _normalize_classify_target(target: Optional[str]) -> str:
    return (target or "").strip().lower()


def _to_ndjson(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False) + "\n"


def _build_batch_finish_payload(
    job_id: str,
    total: int,
    processed_count: int,
    success_count: int,
    failed_count: int,
    stopped: bool,
    action_label: str
) -> Dict[str, Any]:
    remaining_count = max(total - processed_count, 0)
    status_label = "已停止" if stopped else "已完成"
    summary = (
        f"{action_label}{status_label}：共 {total} 项，已处理 {processed_count} 项，"
        f"成功 {success_count} 项，失败 {failed_count} 项，剩余 {remaining_count} 项"
    )
    return {
        "type": "finish",
        "job_id": job_id,
        "total": total,
        "processed_count": processed_count,
        "success_count": success_count,
        "failed_count": failed_count,
        "stopped": stopped,
        "summary": summary
    }


def _is_valid_http_url(value: str) -> bool:
    normalized_value = (value or "").strip()
    if not normalized_value:
        return True

    try:
        parsed = urlparse(normalized_value)
    except Exception:
        return False

    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _is_valid_customer_service_image_url(value: str) -> bool:
    normalized_value = (value or "").strip()
    if not normalized_value:
        return True

    if is_customer_service_upload_url(normalized_value):
        return customer_service_upload_exists(normalized_value)

    return _is_valid_http_url(normalized_value)


def _build_batch_item_result(
    result: Dict[str, Any],
    fallback_team_id: int,
    index: int,
    job_id: str,
    processed_count: int,
    success_count: int,
    failed_count: int
) -> Dict[str, Any]:
    success = bool(result.get("success"))
    message = (
        result.get("message")
        or result.get("error")
        or ("处理成功" if success else "处理失败")
    )
    return {
        "type": "item_result",
        "job_id": job_id,
        "index": index,
        "team_id": result.get("team_id", fallback_team_id),
        "email": result.get("email"),
        "success": success,
        "status": "success" if success else "failed",
        "message": message,
        "processed_count": processed_count,
        "success_count": success_count,
        "failed_count": failed_count
    }


def _build_batch_stage_payload(
    stage_payload: Dict[str, Any],
    fallback_team_id: int,
    index: int,
    job_id: str,
    processed_count: int,
    success_count: int,
    failed_count: int
) -> Dict[str, Any]:
    return {
        "type": "item_stage",
        "job_id": job_id,
        "index": index,
        "team_id": stage_payload.get("team_id", fallback_team_id),
        "email": stage_payload.get("email"),
        "stage_key": stage_payload.get("stage_key", "processing"),
        "stage_label": stage_payload.get("stage_label", "处理中"),
        "processed_count": processed_count,
        "success_count": success_count,
        "failed_count": failed_count
    }


async def _stream_batch_team_action(
    request: Request,
    action_data: BulkActionRequest,
    action_key: str,
    action_label: str,
    item_runner: Callable[[int, Callable[[Dict[str, Any]], Awaitable[None]]], Awaitable[Dict[str, Any]]]
):
    total = len(action_data.ids)
    job_id = str(uuid4())
    batch_action_jobs[job_id] = BatchActionJobState(job_id=job_id, action=action_key)

    async def progress_generator():
        processed_count = 0
        success_count = 0
        failed_count = 0

        try:
            yield _to_ndjson({
                "type": "start",
                "job_id": job_id,
                "action": action_key,
                "total": total
            })

            for index, team_id in enumerate(action_data.ids, start=1):
                job_state = batch_action_jobs.get(job_id)
                if not job_state or job_state.stop_requested:
                    break

                if await request.is_disconnected():
                    logger.info(f"批量任务 {job_id} 客户端已断开连接")
                    return

                event_queue: asyncio.Queue = asyncio.Queue()

                async def progress_callback(stage_payload: Dict[str, Any]):
                    await event_queue.put(stage_payload)

                task = asyncio.create_task(item_runner(team_id, progress_callback))
                result: Optional[Dict[str, Any]] = None

                try:
                    while True:
                        if await request.is_disconnected():
                            task.cancel()
                            logger.info(f"批量任务 {job_id} 处理中客户端断开，终止剩余流输出")
                            return

                        if task.done() and event_queue.empty():
                            result = await task
                            break

                        try:
                            stage_payload = await asyncio.wait_for(event_queue.get(), timeout=0.1)
                        except asyncio.TimeoutError:
                            continue

                        yield _to_ndjson(
                            _build_batch_stage_payload(
                                stage_payload=stage_payload,
                                fallback_team_id=team_id,
                                index=index,
                                job_id=job_id,
                                processed_count=processed_count,
                                success_count=success_count,
                                failed_count=failed_count
                            )
                        )
                except asyncio.CancelledError:
                    if not task.done():
                        task.cancel()
                    raise
                except Exception as ex:
                    logger.error(f"{action_label}任务 {job_id} 处理 Team {team_id} 时异常: {ex}")
                    result = {
                        "success": False,
                        "team_id": team_id,
                        "email": None,
                        "error": f"异常: {str(ex)}"
                    }

                processed_count += 1
                if result and result.get("success"):
                    success_count += 1
                else:
                    failed_count += 1

                yield _to_ndjson(
                    _build_batch_item_result(
                        result=result or {
                            "success": False,
                            "team_id": team_id,
                            "email": None,
                            "error": "处理结果为空"
                        },
                        fallback_team_id=team_id,
                        index=index,
                        job_id=job_id,
                        processed_count=processed_count,
                        success_count=success_count,
                        failed_count=failed_count
                    )
                )

                job_state = batch_action_jobs.get(job_id)
                if job_state and job_state.stop_requested:
                    break

            job_state = batch_action_jobs.get(job_id)
            stopped = bool(job_state and job_state.stop_requested)
            yield _to_ndjson(
                _build_batch_finish_payload(
                    job_id=job_id,
                    total=total,
                    processed_count=processed_count,
                    success_count=success_count,
                    failed_count=failed_count,
                    stopped=stopped,
                    action_label=action_label
                )
            )
        except asyncio.CancelledError:
            logger.info(f"批量任务 {job_id} 被取消")
            raise
        except Exception as e:
            logger.error(f"{action_label}流式任务失败: {e}")
            yield _to_ndjson(
                _build_batch_finish_payload(
                    job_id=job_id,
                    total=total,
                    processed_count=processed_count,
                    success_count=success_count,
                    failed_count=failed_count,
                    stopped=True,
                    action_label=f"{action_label}异常中断"
                )
            )
        finally:
            batch_action_jobs.pop(job_id, None)

    return StreamingResponse(
        progress_generator(),
        media_type="application/x-ndjson"
    )


def _normalize_team_type(team_type: Optional[str]) -> str:
    normalized = (team_type or TEAM_TYPE_STANDARD).strip().lower()
    if normalized not in {TEAM_TYPE_STANDARD, TEAM_TYPE_WARRANTY}:
        return TEAM_TYPE_STANDARD
    return normalized


def _normalize_warranty_super_code_type(code_type: str) -> str:
    normalized = (code_type or "").strip().lower().replace("-", "_")
    if normalized not in {"usage_limit", "time_limit"}:
        raise ValueError("无效的超级兑换码类型")
    return normalized


async def _get_import_review_stats(
    db: AsyncSession,
    imported_by_user_id: Optional[int] = None,
) -> Dict[str, int]:
    base_filters = [Team.imported_by_user_id.is_not(None)]
    if imported_by_user_id is not None:
        base_filters.append(Team.imported_by_user_id == imported_by_user_id)

    total = await db.scalar(select(func.count(Team.id)).where(*base_filters)) or 0
    pending = await db.scalar(
        select(func.count(Team.id)).where(*base_filters, Team.import_status == IMPORT_STATUS_PENDING)
    ) or 0
    reviewed = max(total - pending, 0)

    return {
        "total_teams": total,
        "available_teams": pending,
        "reviewed_teams": reviewed,
        "total_codes": 0,
        "used_codes": 0,
        "total_seats": reviewed,
        "remaining_seats": pending,
    }


async def _render_team_dashboard_page(
    request: Request,
    db: AsyncSession,
    current_user: dict,
    page: int,
    per_page: int,
    search: Optional[str],
    status: Optional[str],
    team_type: Optional[str],
    active_page: str,
    page_title: str,
    import_status: Optional[str] = IMPORT_STATUS_CLASSIFIED,
    imported_by_user_id: Optional[int] = None,
    imported_only: bool = False,
):
    from app.main import templates

    auto_refresh_config = await settings_service.get_team_auto_refresh_config(db)
    teams_result = await team_service.get_all_teams(
        db,
        page=page,
        per_page=per_page,
        search=search,
        status=status,
        team_type=team_type,
        import_status=import_status,
        imported_by_user_id=imported_by_user_id,
        imported_only=imported_only,
    )
    is_review_mode = active_page in {"pending_teams", "import_only"}
    team_stats = await team_service.get_stats(db, team_type=team_type) if import_status == IMPORT_STATUS_CLASSIFIED and team_type else {"total": teams_result.get("total", 0), "available": 0, "total_seats": 0, "remaining_seats": 0}

    if is_review_mode:
        stats = await _get_import_review_stats(db, imported_by_user_id=imported_by_user_id)
    elif team_type == TEAM_TYPE_STANDARD:
        code_stats = await redemption_service.get_stats(db)
        stats = {
            "total_teams": team_stats["total"],
            "available_teams": team_stats["available"],
            "total_codes": code_stats["total"],
            "used_codes": code_stats["used"]
        }
    else:
        stats = {
            "total_teams": team_stats["total"],
            "available_teams": team_stats["available"],
            "total_seats": team_stats["total_seats"],
            "remaining_seats": team_stats["remaining_seats"]
        }

    return templates.TemplateResponse(
        request,
        "admin/index.html",
        {
            "request": request,
            "user": current_user,
            "active_page": active_page,
            "page_title": page_title,
            "team_mode": team_type or TEAM_TYPE_STANDARD,
            "is_pending_mode": is_review_mode,
            "is_review_mode": is_review_mode,
            "teams": teams_result.get("teams", []),
            "stats": stats,
            "search": search,
            "status_filter": status,
            "team_auto_refresh_enabled": auto_refresh_config["enabled"],
            "team_auto_refresh_interval_minutes": auto_refresh_config["interval_minutes"],
            "pagination": {
                "current_page": teams_result.get("current_page", page),
                "total_pages": teams_result.get("total_pages", 1),
                "total": teams_result.get("total", 0),
                "per_page": per_page
            }
        }
    )


@router.get("/", response_class=HTMLResponse)
async def admin_dashboard(
    request: Request,
    page: int = 1,
    per_page: int = 20,
    search: Optional[str] = None,
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin)
):
    """
    管理员面板首页
    """
    try:
        logger.info(f"管理员访问控制台, search={search}, page={page}, per_page={per_page}")
        return await _render_team_dashboard_page(
            request=request,
            db=db,
            current_user=current_user,
            page=page,
            per_page=per_page,
            search=search,
            status=status,
            team_type=TEAM_TYPE_STANDARD,
            active_page="dashboard",
            page_title="控制台"
        )
    except Exception as e:
        logger.error(f"加载管理员面板失败: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail=f"加载管理员面板失败: {str(e)}"
        )


@router.get("/warranty-teams", response_class=HTMLResponse)
async def warranty_teams_dashboard(
    request: Request,
    page: int = 1,
    per_page: int = 20,
    search: Optional[str] = None,
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin)
):
    try:
        logger.info(f"管理员访问质保 Team 页面, search={search}, page={page}, per_page={per_page}")
        return await _render_team_dashboard_page(
            request=request,
            db=db,
            current_user=current_user,
            page=page,
            per_page=per_page,
            search=search,
            status=status,
            team_type=TEAM_TYPE_WARRANTY,
            active_page="warranty_teams",
            page_title="质保 Team 管理"
        )
    except Exception as e:
        logger.error(f"加载质保 Team 页面失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"加载质保 Team 页面失败: {str(e)}"
        )


@router.get("/pending-teams", response_class=HTMLResponse)
async def pending_teams_dashboard(
    request: Request,
    page: int = 1,
    per_page: int = 20,
    search: Optional[str] = None,
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin)
):
    """总管理员查看子管理员导入审核记录。"""
    return await _render_team_dashboard_page(
        request=request,
        db=db,
        current_user=current_user,
        page=page,
        per_page=per_page,
        search=search,
        status=status,
        team_type=None,
        active_page="pending_teams",
        page_title="子管理员导入记录",
        import_status=None,
        imported_only=True,
    )


@router.get("/import-only", response_class=HTMLResponse)
async def import_only_page(
    request: Request,
    page: int = 1,
    per_page: int = 20,
    search: Optional[str] = None,
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_team_import_admin)
):
    """子管理员专用导入页；总管理员也可访问用于验证。"""
    imported_by_user_id = current_user.get("id") if is_import_admin_user(current_user) else None
    return await _render_team_dashboard_page(
        request=request,
        db=db,
        current_user=current_user,
        page=page,
        per_page=per_page,
        search=search,
        status=status,
        team_type=None,
        active_page="import_only",
        page_title="导入 Team / 我的导入",
        import_status=None,
        imported_by_user_id=imported_by_user_id,
        imported_only=not is_import_admin_user(current_user),
    )


@router.get("/sub-admins", response_class=HTMLResponse)
async def sub_admins_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin)
):
    from app.main import templates

    sub_admins = await auth_service.list_sub_admins(db)
    return templates.TemplateResponse(
        request,
        "admin/sub_admins/index.html",
        {
            "request": request,
            "user": current_user,
            "active_page": "sub_admins",
            "sub_admins": sub_admins,
        }
    )


@router.post("/sub-admins")
async def create_sub_admin(
    payload: SubAdminCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin),
):
    result = await auth_service.create_sub_admin(payload.username, payload.password, db)
    return JSONResponse(
        status_code=status.HTTP_200_OK if result.get("success") else status.HTTP_400_BAD_REQUEST,
        content=result,
    )


@router.post("/sub-admins/{user_id}/toggle")
async def toggle_sub_admin(
    user_id: int,
    payload: SubAdminToggleRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin),
):
    result = await auth_service.toggle_sub_admin(user_id, payload.is_active, db)
    return JSONResponse(
        status_code=status.HTTP_200_OK if result.get("success") else status.HTTP_404_NOT_FOUND,
        content=result,
    )


@router.post("/sub-admins/{user_id}/reset-password")
async def reset_sub_admin_password(
    user_id: int,
    payload: SubAdminResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin),
):
    result = await auth_service.reset_sub_admin_password(user_id, payload.password, db)
    return JSONResponse(
        status_code=status.HTTP_200_OK if result.get("success") else status.HTTP_400_BAD_REQUEST,
        content=result,
    )




@router.post("/teams/{team_id}/delete")
async def delete_team(
    team_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin)
):
    """
    删除 Team

    Args:
        team_id: Team ID
        db: 数据库会话
        current_user: 当前用户（需要登录）

    Returns:
        删除结果
    """
    try:
        logger.info(f"管理员删除 Team: {team_id}")

        result = await team_service.delete_team(team_id, db)

        if not result["success"]:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content=result
            )

        return JSONResponse(content=result)

    except Exception as e:
        logger.error(f"删除 Team 失败: {e}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "success": False,
                "error": f"删除 Team 失败: {str(e)}"
            }
        )


@router.get("/teams/{team_id}/info")
async def get_team_info(
    team_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin)
):
    """获取 Team 详情 (包含解密后的 Token)"""
    try:
        result = await team_service.get_team_by_id(team_id, db)
        if not result["success"]:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content=result
            )
        return JSONResponse(content=result)
    except Exception as e:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"success": False, "error": str(e)}
        )


@router.post("/teams/{team_id}/update")
async def update_team(
    team_id: int,
    update_data: TeamUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin)
):
    """更新 Team 信息"""
    try:
        result = await team_service.update_team(
            team_id=team_id,
            db_session=db,
            email=update_data.email,
            account_id=update_data.account_id,
            access_token=update_data.access_token,
            refresh_token=update_data.refresh_token,
            session_token=update_data.session_token,
            client_id=update_data.client_id,
            max_members=update_data.max_members,
            team_name=update_data.team_name,
            status=update_data.status
        )
        if not result["success"]:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content=result
            )
        return JSONResponse(content=result)
    except Exception as e:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"success": False, "error": str(e)}
        )


@router.post("/teams/{team_id}/transfer")
async def transfer_team_type(
    team_id: int,
    transfer_data: TeamTransferRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin)
):
    """在普通 Team 与质保 Team 之间转移账号"""
    try:
        target_team_type = (transfer_data.target_team_type or "").strip().lower()
        if target_team_type not in {TEAM_TYPE_STANDARD, TEAM_TYPE_WARRANTY}:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"success": False, "error": "目标 Team 类型无效"}
            )

        logger.info("管理员转移 Team 类型: team_id=%s, target=%s", team_id, target_team_type)

        result = await team_service.transfer_team_type(
            team_id=team_id,
            target_team_type=target_team_type,
            db_session=db
        )

        if not result.get("success"):
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content=result
            )

        return JSONResponse(content=result)
    except Exception as e:
        logger.error(f"转移 Team 类型失败: {e}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"success": False, "error": f"转移失败: {str(e)}"}
        )


@router.post("/teams/{team_id}/classify")
async def classify_pending_team(
    team_id: int,
    classify_data: TeamClassifyRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin)
):
    """总管理员将待分类 Team 归类到普通账号、质保账号或质保 Team。"""
    try:
        target = _normalize_classify_target(classify_data.target)
        if target not in CLASSIFY_TARGETS:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"success": False, "error": "分类目标无效"}
            )

        result = await team_service.classify_pending_team(
            team_id=team_id,
            target=target,
            db_session=db,
            warranty_days=classify_data.warranty_days,
        )
        return JSONResponse(
            status_code=status.HTTP_200_OK if result.get("success") else status.HTTP_400_BAD_REQUEST,
            content=result,
        )
    except Exception as e:
        logger.error("分类待分类 Team 失败: %s", e)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"success": False, "error": f"分类失败: {str(e)}"}
        )


@router.post("/teams/batch-classify/stream")
async def batch_classify_pending_teams_stream(
    request: Request,
    action_data: BulkTeamClassifyRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin)
):
    """总管理员批量归类待审核 Team。"""
    target = _normalize_classify_target(action_data.target)
    if target not in CLASSIFY_TARGETS:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"success": False, "error": "分类目标无效"}
        )

    if not action_data.ids:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"success": False, "error": "请选择要归类的 Team"}
        )

    action_labels = {
        CLASSIFY_TARGET_STANDARD: "批量进入控制台（普通兑换码）",
        CLASSIFY_TARGET_WARRANTY_CODE: "批量进入控制台（质保兑换码）",
        CLASSIFY_TARGET_WARRANTY_TEAM: "批量进入质保 Team",
    }
    stage_labels = {
        CLASSIFY_TARGET_STANDARD: "归类为控制台普通账号",
        CLASSIFY_TARGET_WARRANTY_CODE: "归类为控制台质保账号",
        CLASSIFY_TARGET_WARRANTY_TEAM: "归类到质保 Team 页面",
    }
    action_label = action_labels[target]
    logger.info("管理员%s %s 个 Team", action_label, len(action_data.ids))

    async def item_runner(team_id: int, progress_callback):
        team = await db.scalar(select(Team).where(Team.id == team_id))
        email = team.email if team else None
        await progress_callback({
            "stage_key": "classify_team",
            "stage_label": stage_labels[target],
            "team_id": team_id,
            "email": email,
        })

        result = await team_service.classify_pending_team(
            team_id=team_id,
            target=target,
            db_session=db,
            warranty_days=action_data.warranty_days,
        )
        if email and not result.get("email"):
            result = {**result, "email": email}
        return result

    return await _stream_batch_team_action(
        request=request,
        action_data=action_data,
        action_key=f"batch_classify_{target}",
        action_label=action_label,
        item_runner=item_runner,
    )



@router.post("/teams/import")
async def team_import(
    import_data: TeamImportRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_team_import_admin)
):
    """
    处理 Team 导入

    Args:
        import_data: 导入数据
        db: 数据库会话
        current_user: 当前用户（需要登录）

    Returns:
        导入结果
    """
    try:
        is_import_admin = is_import_admin_user(current_user)
        team_type = _normalize_team_type(import_data.team_type)
        generate_warranty_codes = import_data.generate_warranty_codes
        generate_codes_on_import = True
        import_status = IMPORT_STATUS_CLASSIFIED
        imported_by_user_id = None
        imported_by_username = current_user.get("username")

        if is_import_admin:
            team_type = TEAM_TYPE_STANDARD
            generate_warranty_codes = False
            generate_codes_on_import = False
            import_status = IMPORT_STATUS_PENDING
            imported_by_user_id = current_user.get("id")

        logger.info(
            "后台用户导入 Team: user=%s role=%s import_type=%s team_type=%s import_status=%s",
            current_user.get("username"),
            current_user.get("role"),
            import_data.import_type,
            team_type,
            import_status,
        )

        import_context_kwargs = {}
        if is_import_admin:
            import_context_kwargs = {
                "generate_codes_on_import": generate_codes_on_import,
                "import_status": import_status,
                "imported_by_user_id": imported_by_user_id,
                "imported_by_username": imported_by_username,
            }

        if import_data.import_type == "single":
            # 单个导入 - 允许通过 AT, RT 或 ST 导入
            if not any([import_data.access_token, import_data.refresh_token, import_data.session_token]):
                return JSONResponse(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    content={
                        "success": False,
                        "error": "必须提供 Access Token、Refresh Token 或 Session Token 其中之一"
                    }
                )

            result = await team_service.import_team_single(
                access_token=import_data.access_token,
                db_session=db,
                email=import_data.email,
                account_id=import_data.account_id,
                refresh_token=import_data.refresh_token,
                session_token=import_data.session_token,
                client_id=import_data.client_id,
                team_type=team_type,
                generate_warranty_codes=generate_warranty_codes,
                warranty_days=import_data.warranty_days,
                **import_context_kwargs,
            )

            if not result["success"]:
                return JSONResponse(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    content=result
                )

            return JSONResponse(content=result)

        elif import_data.import_type == "batch":
            # 批量导入使用 StreamingResponse
            async def progress_generator():
                async for status_item in team_service.import_team_batch(
                    text=import_data.content,
                    db_session=db,
                    team_type=team_type,
                    generate_warranty_codes=generate_warranty_codes,
                    warranty_days=import_data.warranty_days,
                    **import_context_kwargs,
                ):
                    yield json.dumps(status_item, ensure_ascii=False) + "\n"

            return StreamingResponse(
                progress_generator(),
                media_type="application/x-ndjson"
            )

        else:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={
                    "success": False,
                    "error": "无效的导入类型"
                }
            )

    except Exception as e:
        logger.error(f"导入 Team 失败: {e}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "success": False,
                "error": f"导入失败: {str(e)}"
            }
        )





@router.get("/teams/{team_id}/members/list")
async def team_members_list(
    team_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin)
):
    """
    获取 Team 成员列表 (JSON)

    Args:
        team_id: Team ID
        db: 数据库会话
        current_user: 当前用户（需要登录）

    Returns:
        成员列表 JSON
    """
    try:
        # 获取成员列表
        result = await team_service.get_team_members(team_id, db)
        return JSONResponse(content=result)
    except Exception as e:
        logger.error(f"获取成员列表失败: {e}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "success": False,
                "error": f"获取成员列表失败: {str(e)}"
            }
        )


@router.post("/teams/{team_id}/members/add")
async def add_team_member(
    team_id: int,
    member_data: AddMemberRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin)
):
    """
    添加 Team 成员

    Args:
        team_id: Team ID
        member_data: 成员数据
        db: 数据库会话
        current_user: 当前用户（需要登录）

    Returns:
        添加结果
    """
    try:
        logger.info(f"管理员添加成员到 Team {team_id}: {member_data.email}")

        result = await team_service.add_team_member(
            team_id=team_id,
            email=member_data.email,
            db_session=db
        )

        if not result["success"]:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content=result
            )

        return JSONResponse(content=result)

    except Exception as e:
        logger.error(f"添加成员失败: {e}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "success": False,
                "error": f"添加成员失败: {str(e)}"
            }
        )


@router.post("/teams/{team_id}/members/{user_id}/delete")
async def delete_team_member(
    team_id: int,
    user_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin)
):
    """
    删除 Team 成员

    Args:
        team_id: Team ID
        user_id: 用户 ID
        db: 数据库会话
        current_user: 当前用户（需要登录）

    Returns:
        删除结果
    """
    try:
        logger.info(f"管理员从 Team {team_id} 删除成员: {user_id}")

        result = await team_service.delete_team_member(
            team_id=team_id,
            user_id=user_id,
            db_session=db
        )

        if not result["success"]:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content=result
            )

        return JSONResponse(content=result)

    except Exception as e:
        logger.error(f"删除成员失败: {e}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "success": False,
                "error": f"删除成员失败: {str(e)}"
            }
        )


@router.post("/teams/{team_id}/invites/revoke")
async def revoke_team_invite(
    team_id: int,
    member_data: AddMemberRequest, # 使用相同的包含 email 的模型
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin)
):
    """
    撤回 Team 邀请

    Args:
        team_id: Team ID
        member_data: 成员数据 (包含 email)
        db: 数据库会话
        current_user: 当前用户（需要登录）

    Returns:
        撤回结果
    """
    try:
        logger.info(f"管理员从 Team {team_id} 撤回邀请: {member_data.email}")

        result = await team_service.revoke_team_invite(
            team_id=team_id,
            email=member_data.email,
            db_session=db
        )

        if not result["success"]:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content=result
            )

        return JSONResponse(content=result)

    except Exception as e:
        logger.error(f"撤回邀请失败: {e}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "success": False,
                "error": f"撤回邀请失败: {str(e)}"
            }
        )


@router.post("/teams/{team_id}/enable-device-auth")
async def enable_team_device_auth(
    team_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin)
):
    """
    开启 Team 的设备代码身份验证

    Args:
        team_id: Team ID
        db: 数据库会话
        current_user: 当前用户（需要登录）

    Returns:
        结果
    """
    try:
        logger.info(f"管理员开启 Team {team_id} 的设备身份验证")

        result = await team_service.enable_device_code_auth(
            team_id=team_id,
            db_session=db
        )

        if not result["success"]:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content=result
            )

        return JSONResponse(content=result)

    except Exception as e:
        logger.error(f"开启设备身份验证失败: {e}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "success": False,
                "error": f"操作失败: {str(e)}"
            }
        )


# ==================== 批量操作路由 ====================

@router.post("/teams/batch-refresh/stream")
async def batch_refresh_teams_stream(
    request: Request,
    action_data: BulkActionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin)
):
    logger.info(f"管理员流式批量刷新 {len(action_data.ids)} 个 Team")

    async def item_runner(team_id: int, progress_callback):
        result = await team_service.sync_team_info(
            team_id,
            db,
            force_refresh=True,
            progress_callback=progress_callback,
            enforce_bound_email_cleanup=True,
        )
        await db.commit()
        return result

    return await _stream_batch_team_action(
        request=request,
        action_data=action_data,
        action_key="batch_refresh",
        action_label="批量刷新",
        item_runner=item_runner
    )


@router.post("/teams/batch-refresh")
async def batch_refresh_teams(
    action_data: BulkActionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin)
):
    """
    批量刷新 Team 信息
    """
    try:
        logger.info(f"管理员批量刷新 {len(action_data.ids)} 个 Team")
        
        success_count = 0
        failed_count = 0
        
        for team_id in action_data.ids:
            try:
                # 注意: 这里使用 sync_team_info, 它会自动处理 Token 刷新和信息同步
                # force_refresh=True 代表强制同步 API
                result = await team_service.sync_team_info(
                    team_id,
                    db,
                    force_refresh=True,
                    enforce_bound_email_cleanup=True
                )
                await db.commit()
                if result.get("success"):
                    success_count += 1
                else:
                    failed_count += 1
            except Exception as ex:
                logger.error(f"批量刷新 Team {team_id} 时出错: {ex}")
                failed_count += 1
        
        return JSONResponse(content={
            "success": True,
            "message": f"批量刷新完成: 成功 {success_count}, 失败 {failed_count}",
            "success_count": success_count,
            "failed_count": failed_count
        })
    except Exception as e:
        logger.error(f"批量刷新 Team 失败: {e}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"success": False, "error": str(e)}
        )


@router.post("/teams/batch-actions/{job_id}/stop")
async def stop_batch_action(
    job_id: str,
    current_user: dict = Depends(require_admin)
):
    job_state = batch_action_jobs.get(job_id)
    if not job_state:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"success": False, "error": "批量任务不存在或已结束"}
        )

    job_state.stop_requested = True
    return JSONResponse(content={"success": True, "message": "已请求停止当前批量任务"})


@router.post("/teams/batch-delete")
async def batch_delete_teams(
    action_data: BulkActionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin)
):
    """
    批量删除 Team
    """
    try:
        logger.info(f"管理员批量删除 {len(action_data.ids)} 个 Team")
        
        success_count = 0
        failed_count = 0
        
        for team_id in action_data.ids:
            try:
                result = await team_service.delete_team(team_id, db)
                if result.get("success"):
                    success_count += 1
                else:
                    failed_count += 1
            except Exception as ex:
                logger.error(f"批量删除 Team {team_id} 时出错: {ex}")
                failed_count += 1
        
        return JSONResponse(content={
            "success": True,
            "message": f"批量删除完成: 成功 {success_count}, 失败 {failed_count}",
            "success_count": success_count,
            "failed_count": failed_count
        })
    except Exception as e:
        logger.error(f"批量删除 Team 失败: {e}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"success": False, "error": str(e)}
        )


@router.post("/teams/batch-enable-device-auth/stream")
async def batch_enable_device_auth_stream(
    request: Request,
    action_data: BulkActionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin)
):
    logger.info(f"管理员流式批量开启 {len(action_data.ids)} 个 Team 的设备验证")

    async def item_runner(team_id: int, progress_callback):
        return await team_service.enable_device_code_auth(
            team_id,
            db,
            progress_callback=progress_callback
        )

    return await _stream_batch_team_action(
        request=request,
        action_data=action_data,
        action_key="batch_enable_device_auth",
        action_label="批量开启验证",
        item_runner=item_runner
    )


@router.post("/teams/batch-enable-device-auth")
async def batch_enable_device_auth(
    action_data: BulkActionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin)
):
    """
    批量开启设备代码身份验证
    """
    try:
        logger.info(f"管理员批量开启 {len(action_data.ids)} 个 Team 的设备验证")
        
        success_count = 0
        failed_count = 0
        failed_items = []
        
        for team_id in action_data.ids:
            try:
                result = await team_service.enable_device_code_auth(team_id, db)
                if result.get("success"):
                    success_count += 1
                else:
                    failed_count += 1
                    failed_items.append({
                        "team_id": result.get("team_id", team_id),
                        "email": result.get("email"),
                        "error": result.get("error", "未知错误")
                    })
            except Exception as ex:
                logger.error(f"批量开启 Team {team_id} 设备验证时出错: {ex}")
                failed_count += 1
                failed_items.append({
                    "team_id": team_id,
                    "email": None,
                    "error": str(ex)
                })
        
        return JSONResponse(content={
            "success": True,
            "message": f"批量处理完成: 成功 {success_count}, 失败 {failed_count}",
            "success_count": success_count,
            "failed_count": failed_count,
            "failed_items": failed_items
        })
    except Exception as e:
        logger.error(f"批量处理失败: {e}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"success": False, "error": str(e)}
        )


# ==================== 兑换码管理路由 ====================

@router.get("/codes", response_class=HTMLResponse)
async def codes_list_page(
    request: Request,
    page: int = 1,
    per_page: int = 50,
    search: Optional[str] = None,
    status_filter: Optional[str] = None,
    team_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin)
):
    """
    兑换码列表页面

    Args:
        request: FastAPI Request 对象
        page: 页码
        per_page: 每页数量
        search: 搜索关键词
        status_filter: 状态筛选
        db: 数据库会话
        current_user: 当前用户（需要登录）

    Returns:
        兑换码列表页面 HTML
    """
    try:
        from app.main import templates

        logger.info(
            f"管理员访问兑换码列表页面, search={search}, status={status_filter}, team_id={team_id}, per_page={per_page}"
        )

        team_options_stmt = (
            select(
                Team.id,
                Team.email,
                Team.team_name,
                func.count(RedemptionCode.id).label("code_count")
            )
            .join(RedemptionCode, RedemptionCode.bound_team_id == Team.id)
            .where(Team.team_type == TEAM_TYPE_STANDARD)
            .group_by(Team.id, Team.email, Team.team_name)
            .order_by(Team.created_at.desc())
        )
        team_options_result = await db.execute(team_options_stmt)
        team_options = [
            {
                "id": row.id,
                "email": row.email,
                "team_name": row.team_name,
                "code_count": row.code_count
            }
            for row in team_options_result
        ]

        # 获取兑换码 (分页)
        # per_page = 50 (Removed hardcoded value)
        codes_result = await redemption_service.get_all_codes(
            db,
            page=page,
            per_page=per_page,
            search=search,
            status=status_filter,
            bound_team_id=team_id
        )
        codes = codes_result.get("codes", [])
        total_codes = codes_result.get("total", 0)
        total_pages = codes_result.get("total_pages", 1)
        current_page = codes_result.get("current_page", 1)

        # 获取统计信息
        stats = await redemption_service.get_stats(db)
        # 兼容旧模版中的 status 统计名 (unused/used/expired)
        # 注意: get_stats 返回的 used 已经包含了 warranty_active

        # 格式化日期时间
        from datetime import datetime
        for code in codes:
            if code.get("created_at"):
                dt = datetime.fromisoformat(code["created_at"])
                code["created_at"] = dt.strftime("%Y-%m-%d %H:%M")
            if code.get("expires_at"):
                dt = datetime.fromisoformat(code["expires_at"])
                code["expires_at"] = dt.strftime("%Y-%m-%d %H:%M")
            if code.get("used_at"):
                dt = datetime.fromisoformat(code["used_at"])
                code["used_at"] = dt.strftime("%Y-%m-%d %H:%M")

        return templates.TemplateResponse(
            request,
            "admin/codes/index.html",
            {
                "request": request,
                "user": current_user,
                "active_page": "codes",
                "codes": codes,
                "stats": stats,
                "search": search,
                "status_filter": status_filter,
                "team_options": team_options,
                "selected_team_id": team_id,
                "pagination": {
                    "current_page": current_page,
                    "total_pages": total_pages,
                    "total": total_codes,
                    "per_page": per_page
                }
            }
        )

    except Exception as e:
        logger.error(f"加载兑换码列表页面失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"加载页面失败: {str(e)}"
        )




@router.post("/codes/generate")
async def generate_codes(
    generate_data: CodeGenerateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin)
):
    """
    处理兑换码生成

    Args:
        generate_data: 生成数据
        db: 数据库会话
        current_user: 当前用户（需要登录）

    Returns:
        生成结果
    """
    try:
        logger.info(f"管理员生成兑换码: {generate_data.type}")

        if generate_data.type == "single":
            # 单个生成
            result = await redemption_service.generate_code_single(
                db_session=db,
                code=generate_data.code,
                expires_days=generate_data.expires_days,
                has_warranty=generate_data.has_warranty,
                warranty_days=generate_data.warranty_days
            )

            if not result["success"]:
                return JSONResponse(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    content=result
                )

            return JSONResponse(content=result)

        elif generate_data.type == "batch":
            # 批量生成
            if not generate_data.count:
                return JSONResponse(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    content={
                        "success": False,
                        "error": "生成数量不能为空"
                    }
                )

            result = await redemption_service.generate_code_batch(
                db_session=db,
                count=generate_data.count,
                expires_days=generate_data.expires_days,
                has_warranty=generate_data.has_warranty,
                warranty_days=generate_data.warranty_days
            )

            if not result["success"]:
                return JSONResponse(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    content=result
                )

            return JSONResponse(content=result)

        else:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={
                    "success": False,
                    "error": "无效的生成类型"
                }
            )

    except Exception as e:
        logger.error(f"生成兑换码失败: {e}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "success": False,
                "error": f"生成失败: {str(e)}"
            }
        )


@router.post("/codes/{code}/delete")
async def delete_code(
    code: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin)
):
    """
    删除兑换码

    Args:
        code: 兑换码
        db: 数据库会话
        current_user: 当前用户（需要登录）

    Returns:
        删除结果
    """
    try:
        logger.info(f"管理员删除兑换码: {code}")

        result = await redemption_service.delete_code(code, db)

        if not result["success"]:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content=result
            )

        return JSONResponse(content=result)

    except Exception as e:
        logger.error(f"删除兑换码失败: {e}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "success": False,
                "error": f"删除失败: {str(e)}"
            }
        )


@router.post("/codes/batch-delete")
async def batch_delete_codes(
    action_data: BulkCodeActionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin)
):
    """
    批量删除兑换码
    """
    try:
        codes = [code for code in action_data.codes if code]
        if not codes:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"success": False, "error": "请先选择要删除的兑换码"}
            )

        logger.info("管理员批量删除 %s 个兑换码", len(codes))

        success_count = 0
        failed_count = 0

        for code in codes:
            try:
                result = await redemption_service.delete_code(code, db)
                if result.get("success"):
                    success_count += 1
                else:
                    failed_count += 1
            except Exception as ex:
                logger.error(f"批量删除兑换码 {code} 时出错: {ex}")
                failed_count += 1

        return JSONResponse(content={
            "success": True,
            "message": f"批量删除完成: 成功 {success_count}，失败 {failed_count}",
            "success_count": success_count,
            "failed_count": failed_count
        })
    except Exception as e:
        logger.error(f"批量删除兑换码失败: {e}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"success": False, "error": str(e)}
        )


@router.get("/codes/export")
async def export_codes(
    search: Optional[str] = None,
    status_filter: Optional[str] = None,
    team_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin)
):
    """
    导出兑换码为Excel文件

    Args:
        search: 搜索关键词
        db: 数据库会话
        current_user: 当前用户（需要登录）

    Returns:
        兑换码Excel文件
    """
    try:
        logger.info("管理员导出兑换码为Excel")
        export_data = CodeExportRequest(
            search=search,
            status_filter=status_filter,
            team_id=team_id,
            export_format="excel"
        )
        return await _build_codes_export_response(export_data, db)

    except Exception as e:
        logger.error(f"导出兑换码失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"导出失败: {str(e)}"
        )


@router.post("/codes/export")
async def export_codes_with_selection(
    export_data: CodeExportRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin)
):
    """按勾选项或筛选条件导出兑换码"""
    try:
        return await _build_codes_export_response(export_data, db)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"导出兑换码失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"导出失败: {str(e)}"
        )


async def _build_codes_export_response(
    export_data: CodeExportRequest,
    db: AsyncSession
):
    """根据导出请求生成响应"""
    from fastapi.responses import Response
    from io import BytesIO
    import xlsxwriter

    export_format = (export_data.export_format or "excel").lower().strip()
    if export_format not in {"excel", "text"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="不支持的导出格式"
        )

    search = export_data.search
    status_filter = export_data.status_filter
    team_id = export_data.team_id
    team_ids = list(dict.fromkeys(export_data.team_ids or [])) or None
    selected_codes = export_data.codes or None
    if selected_codes:
        search = None
        status_filter = None
        team_id = None
        team_ids = None
    elif team_ids:
        search = None
        status_filter = None
        team_id = None

    codes_result = await redemption_service.get_all_codes(
        db,
        page=1,
        per_page=max(len(selected_codes or []), 100000),
        search=search,
        status=status_filter,
        selected_codes=selected_codes,
        bound_team_id=team_id,
        bound_team_ids=team_ids
    )

    if not codes_result.get("success"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=codes_result.get("error") or "获取兑换码失败"
        )

    all_codes = codes_result.get("codes", [])
    logger.info(
        "管理员导出兑换码: format=%s, selected=%s, total=%s",
        export_format,
        len(selected_codes or []),
        len(all_codes)
    )

    if export_format == "text":
        text_content = "\n".join(code["code"] for code in all_codes)
        filename = f"redemption_codes_{get_now().strftime('%Y%m%d_%H%M%S')}.txt"
        return Response(
            content=text_content,
            media_type="text/plain; charset=utf-8",
            headers={
                "Content-Disposition": f"attachment; filename={filename}"
            }
        )

    output = BytesIO()
    workbook = xlsxwriter.Workbook(output, {"in_memory": True})
    worksheet = workbook.add_worksheet("兑换码列表")

    header_format = workbook.add_format({
        "bold": True,
        "fg_color": "#4F46E5",
        "font_color": "white",
        "align": "center",
        "valign": "vcenter",
        "border": 1
    })

    cell_format = workbook.add_format({
        "align": "left",
        "valign": "vcenter",
        "border": 1
    })

    worksheet.set_column("A:A", 12)
    worksheet.set_column("B:B", 30)
    worksheet.set_column("C:C", 24)
    worksheet.set_column("D:D", 25)
    worksheet.set_column("E:E", 12)
    worksheet.set_column("F:F", 18)
    worksheet.set_column("G:G", 18)
    worksheet.set_column("H:H", 30)
    worksheet.set_column("I:I", 18)
    worksheet.set_column("J:J", 12)

    headers = [
        "绑定 Team ID",
        "绑定账号",
        "Team 名称",
        "兑换码",
        "状态",
        "创建时间",
        "过期时间",
        "使用者邮箱",
        "使用时间",
        "质保时长(天)"
    ]
    for col, header in enumerate(headers):
        worksheet.write(0, col, header, header_format)

    status_text_map = {
        "unused": "未使用",
        "used": "已使用",
        "warranty_active": "质保中",
        "expired": "已过期"
    }

    for row, code in enumerate(all_codes, start=1):
        worksheet.write(row, 0, code.get("bound_team_id", "-"), cell_format)
        worksheet.write(row, 1, code.get("bound_team_email", "-"), cell_format)
        worksheet.write(row, 2, code.get("bound_team_name", "-"), cell_format)
        worksheet.write(row, 3, code["code"], cell_format)
        worksheet.write(row, 4, status_text_map.get(code["status"], code["status"]), cell_format)
        worksheet.write(row, 5, code.get("created_at", "-"), cell_format)
        worksheet.write(row, 6, code.get("expires_at", "永久有效"), cell_format)
        worksheet.write(row, 7, code.get("used_by_email", "-"), cell_format)
        worksheet.write(row, 8, code.get("used_at", "-"), cell_format)
        worksheet.write(row, 9, code.get("warranty_days", "-") if code.get("has_warranty") else "-", cell_format)

    workbook.close()
    excel_data = output.getvalue()
    output.close()

    filename = f"redemption_codes_{get_now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return Response(
        content=excel_data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f"attachment; filename={filename}"
        }
    )


@router.post("/codes/{code}/update")
async def update_code(
    code: str,
    update_data: CodeUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin)
):
    """更新兑换码信息"""
    try:
        result = await redemption_service.update_code(
            code=code,
            db_session=db,
            has_warranty=update_data.has_warranty,
            warranty_days=update_data.warranty_days
        )
        if not result["success"]:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content=result
            )
        return JSONResponse(content=result)
    except Exception as e:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"success": False, "error": str(e)}
        )

@router.post("/codes/bulk-update")
async def bulk_update_codes(
    update_data: BulkCodeUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin)
):
    """批量更新兑换码信息"""
    try:
        result = await redemption_service.bulk_update_codes(
            codes=update_data.codes,
            db_session=db,
            has_warranty=update_data.has_warranty,
            warranty_days=update_data.warranty_days
        )
        if not result["success"]:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content=result
            )
        return JSONResponse(content=result)
    except Exception as e:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"success": False, "error": str(e)}
        )


@router.get("/records", response_class=HTMLResponse)
async def records_page(
    request: Request,
    email: Optional[str] = None,
    code: Optional[str] = None,
    team_id: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    page: Optional[str] = "1",
    per_page: int = 20,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin)
):
    """
    使用记录页面

    Args:
        request: FastAPI Request 对象
        email: 邮箱筛选
        code: 兑换码筛选
        team_id: Team ID 筛选
        start_date: 开始日期
        end_date: 结束日期
        page: 页码
        per_page: 每页数量
        db: 数据库会话
        current_user: 当前用户（需要登录）

    Returns:
        使用记录页面 HTML
    """
    try:
        from app.main import templates
        from datetime import datetime, timedelta
        import math

        # 解析参数
        try:
            actual_team_id = int(team_id) if team_id and team_id.strip() else None
        except (ValueError, TypeError):
            actual_team_id = None
            
        try:
            page_int = int(page) if page and page.strip() else 1
        except (ValueError, TypeError):
            page_int = 1
            
        logger.info(f"管理员访问使用记录页面 (page={page_int}, per_page={per_page})")

        # 获取记录 (支持邮箱、兑换码、Team ID 筛选)
        records_result = await redemption_service.get_all_records(
            db, 
            email=email, 
            code=code, 
            team_id=actual_team_id
        )
        all_records = records_result.get("records", [])

        # 仅由于日期范围筛选目前还在内存中处理，如果未来记录数极大可以移至数据库
        filtered_records = []
        for record in all_records:
            # 日期范围筛选
            if start_date or end_date:
                try:
                    record_date = datetime.fromisoformat(record["redeemed_at"]).date()

                    if start_date:
                        start = datetime.strptime(start_date, "%Y-%m-%d").date()
                        if record_date < start:
                            continue

                    if end_date:
                        end = datetime.strptime(end_date, "%Y-%m-%d").date()
                        if record_date > end:
                            continue
                except:
                    pass

            filtered_records.append(record)

        # 获取Team信息并关联到记录
        teams_result = await db.execute(select(Team))
        teams = teams_result.scalars().all()
        team_map = {team.id: team for team in teams}

        # 为记录添加Team名称
        for record in filtered_records:
            team = team_map.get(record["team_id"])
            record["team_name"] = team.team_name if team else None

        # 计算统计数据
        now = get_now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = today_start - timedelta(days=today_start.weekday())
        month_start = today_start.replace(day=1)

        stats = {
            "total": len(filtered_records),
            "today": 0,
            "this_week": 0,
            "this_month": 0
        }

        for record in filtered_records:
            try:
                record_time = datetime.fromisoformat(record["redeemed_at"])
                if record_time >= today_start:
                    stats["today"] += 1
                if record_time >= week_start:
                    stats["this_week"] += 1
                if record_time >= month_start:
                    stats["this_month"] += 1
            except:
                pass

        # 分页
        # per_page = 20 (Removed hardcoded value)
        total_records = len(filtered_records)
        total_pages = math.ceil(total_records / per_page) if total_records > 0 else 1

        # 确保页码有效
        if page_int < 1:
            page_int = 1
        if page_int > total_pages:
            page_int = total_pages

        start_idx = (page_int - 1) * per_page
        end_idx = start_idx + per_page
        paginated_records = filtered_records[start_idx:end_idx]

        # 格式化时间
        for record in paginated_records:
            try:
                dt = datetime.fromisoformat(record["redeemed_at"])
                record["redeemed_at"] = dt.strftime("%Y-%m-%d %H:%M:%S")
            except:
                pass

        return templates.TemplateResponse(
            request,
            "admin/records/index.html",
            {
                "request": request,
                "user": current_user,
                "active_page": "records",
                "records": paginated_records,
                "stats": stats,
                "filters": {
                    "email": email,
                    "code": code,
                    "team_id": team_id,
                    "start_date": start_date,
                    "end_date": end_date
                },
                "pagination": {
                    "current_page": page_int,
                    "total_pages": total_pages,
                    "total": total_records,
                    "per_page": per_page
                }
            }
        )

    except Exception as e:
        logger.error(f"获取使用记录失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取使用记录失败: {str(e)}"
        )


@router.post("/records/{record_id}/withdraw")
async def withdraw_record(
    record_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin)
):
    """
    撤中使用记录 (管理员功能)

    Args:
        record_id: 记录 ID
        db: 数据库会话
        current_user: 当前用户（需要登录）

    Returns:
        结果 JSON
    """
    try:
        logger.info(f"管理员请求撤回记录: {record_id}")
        result = await redemption_service.withdraw_record(record_id, db)

        if not result["success"]:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content=result
            )

        return JSONResponse(content=result)

    except Exception as e:
        logger.error(f"撤回记录失败: {e}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "success": False,
                "error": f"撤回失败: {str(e)}"
            }
        )


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin)
):
    """
    系统设置页面

    Args:
        request: FastAPI Request 对象
        db: 数据库会话
        current_user: 当前用户（需要登录）

    Returns:
        系统设置页面 HTML
    """
    try:
        from app.main import templates

        logger.info("管理员访问系统设置页面")

        # 获取当前配置
        proxy_config = await settings_service.get_proxy_config(db)
        log_level = await settings_service.get_log_level(db)
        team_auto_refresh_config = await settings_service.get_team_auto_refresh_config(db)
        default_team_max_members = await settings_service.get_default_team_max_members(db)
        front_announcement_config = await settings_service.get_front_announcement_config(db)
        customer_service_config = await settings_service.get_customer_service_config(db)
        warranty_service_config = await settings_service.get_warranty_service_config(db)
        warranty_fake_success_config = await settings_service.get_warranty_fake_success_config(db)

        return templates.TemplateResponse(
            request,
            "admin/settings/index.html",
            {
                "request": request,
                "user": current_user,
                "active_page": "settings",
                "proxy_enabled": proxy_config["enabled"],
                "proxy": proxy_config["proxy"],
                "log_level": log_level,
                "team_auto_refresh_enabled": team_auto_refresh_config["enabled"],
                "team_auto_refresh_interval_minutes": team_auto_refresh_config["interval_minutes"],
                "default_team_max_members": default_team_max_members,
                "front_announcement_enabled": front_announcement_config["enabled"],
                "front_announcement_content": front_announcement_config["content"],
                "customer_service_enabled": customer_service_config["enabled"],
                "customer_service_qr_code_url": customer_service_config["qr_code_url"],
                "customer_service_link_url": customer_service_config["link_url"],
                "customer_service_link_text": customer_service_config["link_text"],
                "customer_service_text_content": customer_service_config["text_content"],
                "warranty_service_enabled": warranty_service_config["enabled"],
                "warranty_fake_success_enabled": warranty_fake_success_config["enabled"],
                "webhook_url": await settings_service.get_setting(db, "webhook_url", ""),
                "low_stock_threshold": await settings_service.get_setting(db, "low_stock_threshold", "10"),
                "api_key": await settings_service.get_setting(db, "api_key", "")
            }
        )

    except Exception as e:
        logger.error(f"获取系统设置失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取系统设置失败: {str(e)}"
        )


class ProxyConfigRequest(BaseModel):
    """代理配置请求"""
    enabled: bool = Field(..., description="是否启用代理")
    proxy: str = Field("", description="代理地址")


class LogLevelRequest(BaseModel):
    """日志级别请求"""
    level: str = Field(..., description="日志级别")


class WebhookSettingsRequest(BaseModel):
    """Webhook 设置请求"""
    webhook_url: str = Field("", description="Webhook URL")
    low_stock_threshold: int = Field(10, description="库存阈值")
    api_key: str = Field("", description="API Key")


class TeamAutoRefreshSettingsRequest(BaseModel):
    """Team 自动刷新设置请求"""
    enabled: bool = Field(..., description="是否启用 Team 自动刷新")
    interval_minutes: int = Field(
        settings_service.DEFAULT_TEAM_AUTO_REFRESH_INTERVAL_MINUTES,
        description="自动刷新间隔（分钟）"
    )


class DefaultTeamMaxMembersSettingsRequest(BaseModel):
    """每个 Team 默认最大人数设置请求"""
    value: int = Field(..., description="每个 Team 默认最大人数")


class WarrantyServiceSettingsRequest(BaseModel):
    """前台质保服务开关请求"""
    enabled: bool = Field(..., description="是否启用前台质保服务")


class WarrantyFakeSuccessSettingsRequest(BaseModel):
    """前台质保模拟成功开关请求"""
    enabled: bool = Field(..., description="是否启用前台质保模拟成功")


@router.post("/settings/front-announcement")
async def update_front_announcement_settings(
    announcement_data: FrontAnnouncementSettingsRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin)
):
    """
    更新前台公告配置。
    """
    try:
        logger.info(
            "管理员更新前台公告配置: enabled=%s content_length=%s",
            announcement_data.enabled,
            len((announcement_data.content or "").strip())
        )

        success = await settings_service.update_front_announcement_config(
            db,
            announcement_data.enabled,
            announcement_data.content
        )

        if success:
            return JSONResponse(content={"success": True, "message": "前台公告已保存"})

        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"success": False, "error": "保存失败"}
        )
    except Exception as e:
        logger.error(f"更新前台公告配置失败: {e}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"success": False, "error": f"更新失败: {str(e)}"}
        )


@router.post("/settings/customer-service")
async def update_customer_service_settings(
    customer_service_data: CustomerServiceSettingsRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin)
):
    """
    更新前台客服模块配置。
    """
    try:
        qr_code_url = (customer_service_data.qr_code_url or "").strip()
        link_url = (customer_service_data.link_url or "").strip()
        normalized_qr_code_url = resolve_customer_service_upload_display_url(qr_code_url)

        if not _is_valid_customer_service_image_url(qr_code_url):
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"success": False, "error": "客服二维码地址必须是有效的 http/https 链接或站内已上传且可访问的图片路径"}
            )

        if not _is_valid_http_url(link_url):
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"success": False, "error": "客服跳转链接必须是有效的 http/https 链接"}
            )

        logger.info(
            "管理员更新前台客服模块: enabled=%s has_qr=%s has_link=%s has_text=%s",
            customer_service_data.enabled,
            bool(qr_code_url),
            bool(link_url),
            bool((customer_service_data.text_content or "").strip())
        )

        success = await settings_service.update_customer_service_config(
            db,
            customer_service_data.enabled,
            normalized_qr_code_url if normalized_qr_code_url != qr_code_url else customer_service_data.qr_code_url,
            customer_service_data.link_url,
            customer_service_data.link_text,
            customer_service_data.text_content
        )

        if success:
            return JSONResponse(content={"success": True, "message": "前台客服模块已保存"})

        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"success": False, "error": "保存失败"}
        )
    except Exception as e:
        logger.error(f"更新前台客服模块失败: {e}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"success": False, "error": f"更新失败: {str(e)}"}
        )


@router.post("/settings/customer-service/upload-image")
async def upload_customer_service_image(
    image: UploadFile = File(...),
    current_user: dict = Depends(require_admin)
):
    """
    上传前台客服二维码图片，返回站内静态地址。
    """
    try:
        content_type = (image.content_type or "").lower().strip()
        if content_type not in ALLOWED_CUSTOMER_SERVICE_IMAGE_TYPES:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"success": False, "error": "仅支持 PNG、JPG、WEBP、GIF 格式图片"}
            )

        file_bytes = await image.read()
        if not file_bytes:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"success": False, "error": "图片内容不能为空"}
            )

        if len(file_bytes) > MAX_CUSTOMER_SERVICE_IMAGE_SIZE:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"success": False, "error": "图片大小不能超过 5MB"}
            )

        suffix = ALLOWED_CUSTOMER_SERVICE_IMAGE_TYPES[content_type]
        upload_dir = get_customer_service_upload_dir()
        upload_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{uuid4().hex}{suffix}"
        target_path = upload_dir / filename
        target_path.write_bytes(file_bytes)

        image_url = build_customer_service_upload_url(filename)
        logger.info("管理员上传前台客服二维码图片成功: %s", image_url)

        return JSONResponse(
            content={
                "success": True,
                "message": "图片上传成功",
                "url": image_url
            }
        )
    except Exception as e:
        logger.error(f"上传前台客服二维码图片失败: {e}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"success": False, "error": f"上传失败: {str(e)}"}
        )


@router.get("/warranty-emails", response_class=HTMLResponse)
async def warranty_emails_page(
    request: Request,
    search: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin)
):
    try:
        from app.main import templates

        logger.info("管理员访问质保邮箱列表页 search=%s", search)
        entries = await warranty_service.list_warranty_email_entries(db, search)
        return templates.TemplateResponse(
            request,
            "admin/warranty_emails/index.html",
            {
                "request": request,
                "user": current_user,
                "active_page": "warranty_emails",
                "entries": entries,
                "search": search or ""
            }
        )
    except Exception as e:
        logger.error(f"加载质保邮箱列表页失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"加载质保邮箱列表页失败: {str(e)}"
        )


@router.get("/warranty-claim-records", response_class=HTMLResponse)
async def warranty_claim_records_page(
    request: Request,
    search: Optional[str] = None,
    claim_status: Optional[str] = None,
    page: Optional[str] = "1",
    per_page: int = 20,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin)
):
    try:
        from app.main import templates

        try:
            page_int = int(page) if page and page.strip() else 1
        except (ValueError, TypeError):
            page_int = 1

        logger.info(
            "管理员访问质保提交记录页 search=%s claim_status=%s page=%s per_page=%s",
            search,
            claim_status,
            page_int,
            per_page
        )

        result = await warranty_service.list_warranty_claim_records(
            db_session=db,
            search=search,
            claim_status=claim_status,
            page=page_int,
            per_page=per_page,
        )

        return templates.TemplateResponse(
            request,
            "admin/warranty_claim_records/index.html",
            {
                "request": request,
                "user": current_user,
                "active_page": "warranty_claim_records",
                "records": result["records"],
                "search": search or "",
                "claim_status": (claim_status or "").strip().lower(),
                "pagination": result["pagination"],
            }
        )
    except Exception as e:
        logger.error(f"加载质保提交记录页失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"加载质保提交记录页失败: {str(e)}"
        )


@router.get("/team-cleanup-records", response_class=HTMLResponse)
async def team_cleanup_records_page(
    request: Request,
    search: Optional[str] = None,
    cleanup_status: Optional[str] = None,
    page: Optional[str] = "1",
    per_page: int = 20,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin)
):
    try:
        from app.main import templates

        try:
            page_int = int(page) if page and page.strip() else 1
        except (ValueError, TypeError):
            page_int = 1

        logger.info(
            "管理员访问自动清理记录页 search=%s cleanup_status=%s page=%s per_page=%s",
            search,
            cleanup_status,
            page_int,
            per_page
        )

        result = await team_cleanup_record_service.list_cleanup_records(
            db_session=db,
            search=search,
            cleanup_status=cleanup_status,
            page=page_int,
            per_page=per_page,
        )

        return templates.TemplateResponse(
            request,
            "admin/team_cleanup_records/index.html",
            {
                "request": request,
                "user": current_user,
                "active_page": "team_cleanup_records",
                "records": result["records"],
                "search": search or "",
                "cleanup_status": (cleanup_status or "").strip().lower(),
                "pagination": result["pagination"],
            }
        )
    except Exception as e:
        logger.error(f"加载自动清理记录页失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"加载自动清理记录页失败: {str(e)}"
        )


@router.get("/warranty-super-codes")
async def warranty_super_codes_redirect(
    current_user: dict = Depends(require_admin)
):
    return RedirectResponse(url="/admin/warranty-emails", status_code=status.HTTP_302_FOUND)


@router.post("/warranty-emails/save")
async def save_warranty_email(
    payload: WarrantyEmailSaveRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin)
):
    try:
        entry = await warranty_service.save_warranty_email_entry(
            db_session=db,
            entry_id=payload.entry_id,
            email=payload.email,
            remaining_days=payload.remaining_days,
            remaining_claims=payload.remaining_claims,
            source="manual"
        )
        return JSONResponse(
            content={
                "success": True,
                "message": "质保邮箱已保存",
                "entry": warranty_service.serialize_warranty_email_entry(entry)
            }
        )
    except ValueError as e:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"success": False, "error": str(e)}
        )
    except Exception as e:
        logger.error(f"保存质保邮箱失败: {e}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"success": False, "error": f"保存失败: {str(e)}"}
        )


@router.post("/warranty-emails/{entry_id}/delete")
async def delete_warranty_email(
    entry_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin)
):
    try:
        deleted = await warranty_service.delete_warranty_email_entry(db, entry_id)
        if not deleted:
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={"success": False, "error": "质保邮箱记录不存在"}
            )
        return JSONResponse(content={"success": True, "message": "质保邮箱已删除"})
    except Exception as e:
        logger.error(f"删除质保邮箱失败: {e}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"success": False, "error": f"删除失败: {str(e)}"}
        )


@router.post("/warranty-super-codes/{code_type}/save")
async def save_warranty_super_code(
    code_type: str,
    config_data: WarrantySuperCodeConfigRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin)
):
    return JSONResponse(
        status_code=status.HTTP_410_GONE,
        content={"success": False, "error": "超级兑换码功能已下线，请改用质保邮箱列表"}
    )


@router.post("/warranty-super-codes/{code_type}/regenerate")
async def regenerate_warranty_super_code(
    code_type: str,
    config_data: WarrantySuperCodeConfigRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin)
):
    return JSONResponse(
        status_code=status.HTTP_410_GONE,
        content={"success": False, "error": "超级兑换码功能已下线，请改用质保邮箱列表"}
    )


@router.post("/warranty-super-codes/{code_type}/disable")
async def disable_warranty_super_code(
    code_type: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin)
):
    return JSONResponse(
        status_code=status.HTTP_410_GONE,
        content={"success": False, "error": "超级兑换码功能已下线，请改用质保邮箱列表"}
    )


@router.post("/settings/proxy")
async def update_proxy_config(
    proxy_data: ProxyConfigRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin)
):
    """
    更新代理配置

    Args:
        proxy_data: 代理配置数据
        db: 数据库会话
        current_user: 当前用户（需要登录）

    Returns:
        更新结果
    """
    try:
        from app.services.settings import settings_service

        logger.info(f"管理员更新代理配置: enabled={proxy_data.enabled}, proxy={proxy_data.proxy}")

        # 验证代理地址格式
        if proxy_data.enabled and proxy_data.proxy:
            proxy = proxy_data.proxy.strip()
            if not (proxy.startswith("http://") or proxy.startswith("https://") or proxy.startswith("socks5://") or proxy.startswith("socks5h://")):
                return JSONResponse(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    content={
                        "success": False,
                        "error": "代理地址格式错误,应为 http://host:port, socks5://host:port 或 socks5h://host:port"
                    }
                )

        # 更新配置
        success = await settings_service.update_proxy_config(
            db,
            proxy_data.enabled,
            proxy_data.proxy.strip() if proxy_data.proxy else ""
        )

        if success:
            # 清理 ChatGPT 服务的会话,确保下次请求使用新代理
            from app.services.chatgpt import chatgpt_service
            await chatgpt_service.clear_session()
            
            return JSONResponse(content={"success": True, "message": "代理配置已保存"})
        else:
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={"success": False, "error": "保存失败"}
            )

    except Exception as e:
        logger.error(f"更新代理配置失败: {e}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"success": False, "error": f"更新失败: {str(e)}"}
        )


@router.post("/settings/log-level")
async def update_log_level(
    log_data: LogLevelRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin)
):
    """
    更新日志级别

    Args:
        log_data: 日志级别数据
        db: 数据库会话
        current_user: 当前用户（需要登录）

    Returns:
        更新结果
    """
    try:
        from app.services.settings import settings_service

        logger.info(f"管理员更新日志级别: {log_data.level}")

        # 更新日志级别
        success = await settings_service.update_log_level(db, log_data.level)

        if success:
            return JSONResponse(content={"success": True, "message": "日志级别已保存"})
        else:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"success": False, "error": "无效的日志级别"}
            )

    except Exception as e:
        logger.error(f"更新日志级别失败: {e}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"success": False, "error": f"更新失败: {str(e)}"}
        )


@router.post("/settings/webhook")
async def update_webhook_settings(
    webhook_data: WebhookSettingsRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin)
):
    """
    更新 Webhook 和 API Key 设置
    """
    try:
        from app.services.settings import settings_service

        logger.info(f"管理员更新 Webhook/API 配置: url={webhook_data.webhook_url}, threshold={webhook_data.low_stock_threshold}")

        settings = {
            "webhook_url": webhook_data.webhook_url.strip(),
            "low_stock_threshold": str(webhook_data.low_stock_threshold),
            "api_key": webhook_data.api_key.strip()
        }

        success = await settings_service.update_settings(db, settings)

        if success:
            return JSONResponse(content={"success": True, "message": "配置已保存"})
        else:
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={"success": False, "error": "保存失败"}
            )

    except Exception as e:
        logger.error(f"更新配置失败: {e}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"success": False, "error": f"更新失败: {str(e)}"}
        )


@router.post("/settings/team-auto-refresh")
async def update_team_auto_refresh_settings(
    refresh_data: TeamAutoRefreshSettingsRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin)
):
    """
    更新 Team 自动刷新设置
    """
    try:
        logger.info(
            "管理员更新 Team 自动刷新配置: enabled=%s, interval_minutes=%s",
            refresh_data.enabled,
            refresh_data.interval_minutes
        )

        success = await settings_service.update_team_auto_refresh_config(
            db,
            refresh_data.enabled,
            refresh_data.interval_minutes
        )

        if success:
            return JSONResponse(content={"success": True, "message": "Team 自动刷新配置已保存"})

        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"success": False, "error": "保存失败"}
        )
    except ValueError as e:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"success": False, "error": str(e)}
        )
    except Exception as e:
        logger.error(f"更新 Team 自动刷新配置失败: {e}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"success": False, "error": f"更新失败: {str(e)}"}
        )


@router.post("/settings/default-team-max-members")
async def update_default_team_max_members_settings(
    settings_data: DefaultTeamMaxMembersSettingsRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin)
):
    """
    更新每个 Team 默认最大人数。
    """
    try:
        logger.info(
            "管理员更新每个 Team 默认最大人数: value=%s",
            settings_data.value
        )

        success = await settings_service.update_default_team_max_members(
            db,
            settings_data.value
        )

        if success:
            return JSONResponse(content={"success": True, "message": "Team 默认最大人数已保存"})

        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"success": False, "error": "保存失败"}
        )
    except ValueError as e:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"success": False, "error": str(e)}
        )
    except Exception as e:
        logger.error(f"更新 Team 默认最大人数失败: {e}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"success": False, "error": f"更新失败: {str(e)}"}
        )


@router.post("/settings/warranty-service")
async def update_warranty_service_settings(
    warranty_data: WarrantyServiceSettingsRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin)
):
    """
    更新前台质保服务开关。
    """
    try:
        logger.info(
            "管理员更新前台质保服务开关: enabled=%s",
            warranty_data.enabled
        )

        success = await settings_service.update_warranty_service_config(
            db,
            warranty_data.enabled
        )

        if success:
            return JSONResponse(content={"success": True, "message": "前台质保服务开关已保存"})

        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"success": False, "error": "保存失败"}
        )
    except Exception as e:
        logger.error(f"更新前台质保服务开关失败: {e}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"success": False, "error": f"更新失败: {str(e)}"}
        )


@router.post("/settings/warranty-fake-success")
async def update_warranty_fake_success_settings(
    warranty_data: WarrantyFakeSuccessSettingsRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin)
):
    """
    更新前台质保模拟成功开关。
    """
    try:
        logger.info(
            "管理员更新前台质保模拟成功开关: enabled=%s",
            warranty_data.enabled
        )

        success = await settings_service.update_warranty_fake_success_config(
            db,
            warranty_data.enabled
        )

        if success:
            return JSONResponse(content={"success": True, "message": "前台质保服务开关已保存"})

        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"success": False, "error": "保存失败"}
        )
    except Exception as e:
        logger.error(f"更新前台质保模拟成功开关失败: {e}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"success": False, "error": f"更新失败: {str(e)}"}
        )
