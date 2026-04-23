"""
后台短信快捷工具页面
"""
import re
from dataclasses import dataclass
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi import Request

from app.config import settings
from app.dependencies.auth import require_admin

PHONE_PATTERN = re.compile(r"^[0-9+\-()\s]{3,64}$")

router = APIRouter(
    prefix="/admin",
    tags=["admin"]
)


@dataclass(frozen=True)
class SmsHelperPageState:
    phone: str
    open_url: str
    display_url: str

    @property
    def has_phone(self) -> bool:
        return bool(self.phone)

    @property
    def has_open_url(self) -> bool:
        return bool(self.open_url)


def _normalize_phone(value: str) -> str:
    normalized_value = (value or "").strip()
    if not normalized_value or not PHONE_PATTERN.fullmatch(normalized_value):
        return ""
    return normalized_value


def _normalize_url(value: str) -> str:
    normalized_value = (value or "").strip()
    if not normalized_value:
        return ""

    try:
        parsed = urlparse(normalized_value)
    except Exception:
        return ""

    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return normalized_value


def _build_display_url(value: str) -> str:
    normalized_value = _normalize_url(value)
    if not normalized_value:
        return ""

    parsed = urlparse(normalized_value)
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path or ''}"


def _build_sms_helper_page_state() -> SmsHelperPageState:
    normalized_phone = _normalize_phone(settings.sms_helper_phone)
    normalized_url = _normalize_url(settings.sms_helper_url)

    return SmsHelperPageState(
        phone=normalized_phone,
        open_url=normalized_url,
        display_url=_build_display_url(normalized_url),
    )


@router.get("/sms-helper", response_class=HTMLResponse)
async def sms_helper_page(
    request: Request,
    current_user: dict = Depends(require_admin)
):
    from app.main import templates

    page_state = _build_sms_helper_page_state()

    return templates.TemplateResponse(
        request,
        "admin/sms_helper/index.html",
        {
            "request": request,
            "user": current_user,
            "active_page": "sms_helper",
            "page_title": "短信快捷工具",
            "sms_helper": page_state,
        }
    )


@router.get("/sms-helper/open")
async def open_sms_helper_target(
    current_user: dict = Depends(require_admin)
):
    del current_user

    page_state = _build_sms_helper_page_state()
    if not page_state.has_open_url:
        raise HTTPException(status_code=404, detail="短信快捷工具地址未配置")

    return RedirectResponse(url=page_state.open_url, status_code=307)
