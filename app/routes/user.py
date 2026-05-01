"""
用户路由
处理用户兑换页面
"""
import logging
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db

logger = logging.getLogger(__name__)

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
