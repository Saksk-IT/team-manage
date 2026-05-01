"""富文本清洗工具。"""
from __future__ import annotations

import re
from html import unescape
from typing import Final

import bleach
from bleach.css_sanitizer import CSSSanitizer

from app.utils.storage import is_warranty_rich_text_upload_url

ALLOWED_RICH_TEXT_TAGS: Final[list[str]] = [
    "p",
    "br",
    "strong",
    "b",
    "em",
    "i",
    "u",
    "s",
    "ul",
    "ol",
    "li",
    "blockquote",
    "a",
    "h3",
    "h4",
    "code",
    "pre",
    "img",
]

ALLOWED_RICH_TEXT_ATTRIBUTES: Final[dict[str, list[str]]] = {
    "a": ["href", "title", "target", "rel"],
    "img": ["src", "alt", "title", "width", "height", "style"],
}

ALLOWED_RICH_TEXT_PROTOCOLS: Final[list[str]] = ["http", "https", "mailto"]
ALLOWED_RICH_TEXT_CSS_PROPERTIES: Final[list[str]] = ["max-width", "height"]
RICH_TEXT_CSS_SANITIZER: Final[CSSSanitizer] = CSSSanitizer(
    allowed_css_properties=ALLOWED_RICH_TEXT_CSS_PROPERTIES
)


def _allow_rich_text_attribute(tag: str, name: str, value: str) -> bool:
    if tag == "a":
        return name in ALLOWED_RICH_TEXT_ATTRIBUTES["a"]

    if tag != "img" or name not in ALLOWED_RICH_TEXT_ATTRIBUTES["img"]:
        return False

    if name == "src":
        return is_warranty_rich_text_upload_url(value)

    if name in {"width", "height"}:
        return str(value or "").strip().isdigit()

    return True


def sanitize_rich_text(value: str | None) -> str:
    """清洗管理员输入的富文本，仅保留安全的基础排版标签。"""
    raw_value = (value or "").strip()
    if not raw_value:
        return ""

    sanitized = bleach.clean(
        raw_value,
        tags=ALLOWED_RICH_TEXT_TAGS,
        attributes=_allow_rich_text_attribute,
        protocols=ALLOWED_RICH_TEXT_PROTOCOLS,
        css_sanitizer=RICH_TEXT_CSS_SANITIZER,
        strip=True,
    )
    sanitized = re.sub(r"<img(?![^>]*\ssrc=)[^>]*>", "", sanitized, flags=re.IGNORECASE)
    return bleach.linkify(
        sanitized,
        callbacks=[bleach.callbacks.nofollow, bleach.callbacks.target_blank],
        skip_tags=["pre", "code"],
        parse_email=False,
    ).strip()


def rich_text_to_plain_text(value: str | None) -> str:
    """将安全富文本转成用于 API message 的纯文本摘要。"""
    no_tags = bleach.clean(value or "", tags=[], strip=True)
    normalized = re.sub(r"\s+", " ", unescape(no_tags)).strip()
    return normalized
