"""Sub2API Admin API integration for warranty email-check redeem-code generation."""
import hashlib
import json
import logging
from typing import Any, Dict, Optional

import httpx

from app.services.settings import settings_service
from app.utils.time_utils import get_now

logger = logging.getLogger(__name__)


class Sub2APIWarrantyRedeemClient:
    """Creates subscription redeem codes in Sub2API for warranty email matches."""

    CREATE_PATH = "/api/v1/admin/redeem-codes"

    def build_code(self, email: str, entry_id: Optional[int], code_prefix: str) -> str:
        normalized_email = (email or "").strip().lower()
        raw_key = f"{normalized_email}:{entry_id or 0}"
        digest = hashlib.sha256(raw_key.encode("utf-8")).hexdigest().upper()[:20]
        prefix = settings_service._normalize_sub2api_warranty_code_prefix(code_prefix)
        return f"{prefix}-{digest}"

    def parse_response_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(payload, dict):
            return {}
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        redeem_code = data.get("redeem_code") if isinstance(data.get("redeem_code"), dict) else data
        return redeem_code if isinstance(redeem_code, dict) else {}

    def build_idempotency_key(self, code: str, request_body: Dict[str, Any]) -> str:
        payload_json = json.dumps(request_body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        payload_digest = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()[:16]
        return f"team-manage-warranty-email-check-create-{code}-{payload_digest}"

    async def create_subscription_code(
        self,
        *,
        base_url: str,
        admin_api_key: str,
        code: str,
        group_id: int,
        validity_days: int,
        email: str,
        entry_id: Optional[int] = None,
        sub2api_user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Create an unused Sub2API subscription redeem code."""
        normalized_base_url = (base_url or "").strip().rstrip("/")
        normalized_api_key = (admin_api_key or "").strip()
        if not normalized_base_url or not normalized_api_key:
            return {"success": False, "error": "Sub2API 地址或 Admin API Key 未配置"}

        try:
            safe_group_id = int(group_id)
            safe_validity_days = int(validity_days)
        except (TypeError, ValueError):
            return {"success": False, "error": "Sub2API 分组 ID 和有效天数必须为整数"}

        if safe_group_id <= 0:
            return {"success": False, "error": "Sub2API 订阅分组 ID 必须为正整数"}
        if safe_validity_days <= 0:
            return {"success": False, "error": "兑换码有效天数必须大于 0"}

        notes_parts = [f"team-manage warranty email-check: {email}"]
        if entry_id:
            notes_parts.append(f"entry_id={entry_id}")
        if sub2api_user_id:
            notes_parts.append(f"sub2api_user_id={sub2api_user_id}")
        request_body = {
            "code": code,
            "type": "subscription",
            "value": 0,
            "status": "unused",
            "group_id": safe_group_id,
            "validity_days": safe_validity_days,
            "notes": "; ".join(notes_parts),
        }
        idempotency_key = self.build_idempotency_key(code, request_body)
        url = f"{normalized_base_url}{self.CREATE_PATH}"

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
                response = await client.post(
                    url,
                    headers={
                        "x-api-key": normalized_api_key,
                        "Idempotency-Key": idempotency_key,
                        "Content-Type": "application/json",
                    },
                    json=request_body,
                )
        except httpx.RequestError as exc:
            logger.warning("Sub2API 质保兑换码创建请求失败: %s", exc)
            return {"success": False, "error": "Sub2API 请求失败，请稍后重试"}

        try:
            response_payload = response.json()
        except ValueError:
            response_payload = {}

        redeem_code_payload = self.parse_response_payload(response_payload)
        if 200 <= response.status_code < 300:
            return {
                "success": True,
                "code": redeem_code_payload.get("code") or code,
                "redeem_code": redeem_code_payload,
                "generated_at": get_now(),
                "request_body": request_body,
            }

        error_message = "Sub2API 创建兑换码失败"
        if isinstance(response_payload, dict):
            error_message = (
                response_payload.get("message")
                or response_payload.get("detail")
                or response_payload.get("error")
                or error_message
            )
        logger.warning(
            "Sub2API 质保兑换码创建失败 status=%s code=%s response=%s",
            response.status_code,
            code,
            response_payload,
        )
        return {"success": False, "error": error_message, "status_code": response.status_code}


sub2api_warranty_redeem_client = Sub2APIWarrantyRedeemClient()
