"""
独立本地工具页
数据仅保存在浏览器本地
"""
import ipaddress
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field


router = APIRouter(tags=["local_tools"])

MAX_FETCH_BYTES = 256 * 1024
BLOCKED_HOSTS = {"localhost"}


class LocalToolFetchRequest(BaseModel):
    """本地工具临时读取请求，不做服务端持久化。"""

    url: str = Field(..., min_length=1, max_length=4000)


def _normalize_fetch_url(value: str) -> str:
    normalized_value = (value or "").strip()
    parsed_url = urlparse(normalized_value)

    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
        raise HTTPException(status_code=400, detail="只支持 http/https 地址")

    if _is_blocked_fetch_host(parsed_url.hostname or ""):
        raise HTTPException(status_code=400, detail="不允许读取本机或内网地址")

    return normalized_value


def _is_private_ip(value: str) -> bool:
    try:
        ip_address = ipaddress.ip_address(value)
    except ValueError:
        return False

    return (
        ip_address.is_private
        or ip_address.is_loopback
        or ip_address.is_link_local
        or ip_address.is_multicast
        or ip_address.is_reserved
        or ip_address.is_unspecified
    )


def _is_blocked_fetch_host(hostname: str) -> bool:
    normalized_hostname = (hostname or "").strip().lower().rstrip(".")
    if not normalized_hostname or normalized_hostname in BLOCKED_HOSTS:
        return True

    return _is_private_ip(normalized_hostname)


@router.get("/local-tools", response_class=HTMLResponse)
async def local_tools_page(request: Request):
    from app.main import templates

    return templates.TemplateResponse(
        request,
        "tools/local_tools.html",
        {
            "request": request,
        }
    )


@router.post("/local-tools/fetch-page")
async def fetch_local_tool_page(payload: LocalToolFetchRequest):
    """临时读取目标网页文本，供本地工具页刷新验证码信息；不保存任何数据。"""
    target_url = _normalize_fetch_url(payload.url)

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(8.0),
            follow_redirects=False,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; LocalToolsFetcher/1.0)",
                "Accept": "text/plain,text/html,application/json;q=0.9,*/*;q=0.8",
            },
        ) as client:
            response = await client.get(target_url)
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail="目标网页读取失败") from exc

    content = response.content[:MAX_FETCH_BYTES]

    return {
        "success": 200 <= response.status_code < 400,
        "status_code": response.status_code,
        "content_type": response.headers.get("content-type", ""),
        "text": content.decode(response.encoding or "utf-8", errors="replace"),
    }
