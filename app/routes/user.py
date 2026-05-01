"""
用户路由
处理用户兑换页面
"""
import logging
from urllib.parse import urlencode, urlparse, urlunparse, parse_qsl
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db

logger = logging.getLogger(__name__)


def _build_purchase_link_url(base_url: str, request: Request) -> str:
    normalized_url = (base_url or "").strip()
    if not normalized_url:
        return ""

    try:
        query_params = request.query_params
    except KeyError:
        return normalized_url

    forwarded_keys = ["user_id", "token", "theme", "lang", "ui_mode"]
    forwarded_params = {
        key: query_params.get(key)
        for key in forwarded_keys
        if query_params.get(key)
    }
    if not forwarded_params:
        return normalized_url
    forwarded_params.setdefault("ui_mode", "embedded")

    try:
        parsed = urlparse(normalized_url)
    except Exception:
        return normalized_url
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return normalized_url

    query_items = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query_items.update(forwarded_params)
    return urlunparse(parsed._replace(query=urlencode(query_items)))

# 创建路由器
router = APIRouter(
    tags=["user"]
)


@router.get("/", response_class=HTMLResponse)
async def redeem_page(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    用户兑换页面

    Args:
        request: FastAPI Request 对象
        db: 数据库会话

    Returns:
        用户兑换页面 HTML
    """
    try:
        from app.main import templates
        from app.services.settings import settings_service
        from app.services.team import TeamService, TEAM_TYPE_NUMBER_POOL, TEAM_TYPE_STANDARD

        front_announcement_config = await settings_service.get_front_announcement_config(db)
        customer_service_config = await settings_service.get_customer_service_config(db)
        purchase_link_config = await settings_service.get_purchase_link_config(db)
        warranty_service_config = await settings_service.get_warranty_service_config(db)
        warranty_fake_success_config = await settings_service.get_warranty_fake_success_config(db)
        warranty_email_check_config = await settings_service.get_warranty_email_check_config(db)
        warranty_service_enabled = warranty_service_config["enabled"]
        warranty_fake_success_enabled = (
            warranty_service_enabled
            and warranty_fake_success_config["enabled"]
            and not warranty_email_check_config["enabled"]
        )

        if warranty_fake_success_enabled:
            remaining_spots = await settings_service.get_warranty_fake_success_remaining_spots(db)
        else:
            team_service = TeamService()
            number_pool_config = await settings_service.get_number_pool_config(db)
            redeem_team_type = TEAM_TYPE_NUMBER_POOL if number_pool_config.get("enabled") else TEAM_TYPE_STANDARD
            remaining_spots = await team_service.get_total_available_seats(db, team_type=redeem_team_type)

        purchase_link_config = {
            **purchase_link_config,
            "url": _build_purchase_link_url(purchase_link_config.get("url", ""), request),
        }

        logger.info(f"用户访问兑换页面，剩余车位: {remaining_spots}")

        return templates.TemplateResponse(
            request,
            "user/redeem.html",
            {
                "request": request,
                "remaining_spots": remaining_spots,
                "front_announcement": front_announcement_config,
                "customer_service": customer_service_config,
                "purchase_link": purchase_link_config,
                "warranty_service_enabled": warranty_service_enabled,
                "warranty_fake_success_enabled": warranty_fake_success_enabled,
                "warranty_email_check_enabled": warranty_email_check_config["enabled"]
            }
        )

    except Exception as e:
        logger.error(f"渲染兑换页面失败: {e}")
        return HTMLResponse(
            content=f"<h1>页面加载失败</h1><p>{str(e)}</p>",
            status_code=500
        )
