"""富文本清洗工具。"""
from __future__ import annotations

import re
from html import unescape
from typing import Final

import bleach

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
]

ALLOWED_RICH_TEXT_ATTRIBUTES: Final[dict[str, list[str]]] = {
    "a": ["href", "title", "target", "rel"],
}

ALLOWED_RICH_TEXT_PROTOCOLS: Final[list[str]] = ["http", "https", "mailto"]


def sanitize_rich_text(value: str | None) -> str:
    """清洗管理员输入的富文本，仅保留安全的基础排版标签。"""
    raw_value = (value or "").strip()
    if not raw_value:
        return ""

    sanitized = bleach.clean(
        raw_value,
        tags=ALLOWED_RICH_TEXT_TAGS,
        attributes=ALLOWED_RICH_TEXT_ATTRIBUTES,
        protocols=ALLOWED_RICH_TEXT_PROTOCOLS,
        strip=True,
    )
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
