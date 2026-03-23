"""
Token 正则匹配工具
用于从文本中提取 AT Token、邮箱、Account ID 等信息
"""
import json
import re
from typing import Any, Dict, List, Optional
import logging

logger = logging.getLogger(__name__)


class TokenParser:
    """Token 正则匹配解析器"""

    # JWT Token 正则 (以 eyJ 开头的 Base64 字符串)
    # 简化匹配逻辑，三段式 Base64，Header 以 eyJ 开头
    JWT_PATTERN = r'eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+'

    # 邮箱正则 (更通用的邮箱格式)
    EMAIL_PATTERN = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'

    # Account ID 正则 (UUID 格式)
    ACCOUNT_ID_PATTERN = r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'

    # Refresh Token 正则 (支持 rt- 或 rt_ 前缀,且包含点号)
    REFRESH_TOKEN_PATTERN = r'rt[_-][A-Za-z0-9._-]+'
    
    # Session Token 正则 (通常比较长，包含两个点)
    SESSION_TOKEN_PATTERN = r'eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*\.[A-Za-z0-9_-]+(\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)?'

    # Client ID 正则 (严格匹配 app_ 开头)
    CLIENT_ID_PATTERN = r'app_[A-Za-z0-9]+'

    ACCESS_TOKEN_KEYS = ("accessToken", "access_token")
    REFRESH_TOKEN_KEYS = ("refreshToken", "refresh_token")
    SESSION_TOKEN_KEYS = ("sessionToken", "session_token")
    CLIENT_ID_KEYS = ("clientId", "client_id")

    def _entry_signature(self, entry: Dict[str, Optional[str]]) -> tuple:
        return (
            entry.get("token"),
            entry.get("email"),
            entry.get("account_id"),
            entry.get("refresh_token"),
            entry.get("session_token"),
            entry.get("client_id")
        )

    def _get_string_value(self, data: Dict[str, Any], keys: tuple[str, ...]) -> Optional[str]:
        for key in keys:
            value = data.get(key)
            if isinstance(value, str):
                value = value.strip()
                if value:
                    return value
        return None

    def _extract_json_segments(self, text: str) -> List[tuple[Any, int, int]]:
        decoder = json.JSONDecoder()
        segments = []
        index = 0
        text_length = len(text)

        while index < text_length:
            while index < text_length and text[index].isspace():
                index += 1

            if index >= text_length:
                break

            if text[index] not in "{[":
                index += 1
                continue

            try:
                payload, end = decoder.raw_decode(text, index)
            except json.JSONDecodeError:
                index += 1
                continue

            segments.append((payload, index, end))
            index = end

        return segments

    def _walk_json_candidates(self, payload: Any):
        if isinstance(payload, dict):
            yield payload
            for value in payload.values():
                yield from self._walk_json_candidates(value)
        elif isinstance(payload, list):
            for item in payload:
                yield from self._walk_json_candidates(item)

    def _extract_team_entry_from_json_object(self, data: Dict[str, Any]) -> Optional[Dict[str, Optional[str]]]:
        token = self._get_string_value(data, self.ACCESS_TOKEN_KEYS)
        refresh_token = self._get_string_value(data, self.REFRESH_TOKEN_KEYS)
        session_token = self._get_string_value(data, self.SESSION_TOKEN_KEYS)

        if token and not re.fullmatch(self.JWT_PATTERN, token):
            token = None
        if refresh_token and not re.fullmatch(self.REFRESH_TOKEN_PATTERN, refresh_token):
            refresh_token = None
        if session_token and not re.fullmatch(self.SESSION_TOKEN_PATTERN, session_token):
            session_token = None

        if not any([token, refresh_token, session_token]):
            return None

        email = self._get_string_value(data, ("email",))
        if not email and isinstance(data.get("user"), dict):
            email = self._get_string_value(data["user"], ("email",))
        if email and not re.fullmatch(self.EMAIL_PATTERN, email):
            email = None

        account_id = self._get_string_value(data, ("accountId", "account_id"))
        if not account_id and isinstance(data.get("account"), dict):
            account_id = self._get_string_value(data["account"], ("id", "accountId", "account_id"))
        if account_id and not re.fullmatch(self.ACCOUNT_ID_PATTERN, account_id, re.IGNORECASE):
            account_id = None

        client_id = self._get_string_value(data, self.CLIENT_ID_KEYS)
        if client_id and not re.fullmatch(self.CLIENT_ID_PATTERN, client_id):
            client_id = None

        return {
            "token": token,
            "email": email,
            "account_id": account_id,
            "refresh_token": refresh_token,
            "session_token": session_token,
            "client_id": client_id
        }

    def _extract_team_entries_from_json(self, text: str) -> List[Dict[str, Optional[str]]]:
        results = []
        seen = set()

        for payload, _, _ in self._extract_json_segments(text):
            for candidate in self._walk_json_candidates(payload):
                if not isinstance(candidate, dict):
                    continue

                entry = self._extract_team_entry_from_json_object(candidate)
                if not entry:
                    continue

                signature = self._entry_signature(entry)
                if signature in seen:
                    continue

                seen.add(signature)
                results.append(entry)

        return results

    def _remove_json_segments(self, text: str) -> str:
        chars = list(text)

        for _, start, end in self._extract_json_segments(text):
            for index in range(start, end):
                chars[index] = '\n' if chars[index] == '\n' else ' '

        return ''.join(chars)

    def extract_jwt_tokens(self, text: str) -> List[str]:
        """
        从文本中提取所有 JWT Token

        Args:
            text: 输入文本

        Returns:
            JWT Token 列表
        """
        tokens = re.findall(self.JWT_PATTERN, text)
        logger.info(f"从文本中提取到 {len(tokens)} 个 JWT Token")
        return tokens

    def extract_emails(self, text: str) -> List[str]:
        """
        从文本中提取所有邮箱地址

        Args:
            text: 输入文本

        Returns:
            邮箱地址列表
        """
        emails = re.findall(self.EMAIL_PATTERN, text)
        # 过滤掉无效邮箱
        emails = [email for email in emails if len(email) < 100]
        # 去重
        emails = list(set(emails))
        logger.info(f"从文本中提取到 {len(emails)} 个邮箱地址")
        return emails

    def extract_account_ids(self, text: str) -> List[str]:
        """
        从文本中提取所有 Account ID

        Args:
            text: 输入文本

        Returns:
            Account ID 列表
        """
        account_ids = re.findall(self.ACCOUNT_ID_PATTERN, text)
        # 去重
        account_ids = list(set(account_ids))
        logger.info(f"从文本中提取到 {len(account_ids)} 个 Account ID")
        return account_ids

    def parse_team_import_text(self, text: str) -> List[Dict[str, Optional[str]]]:
        """
        解析 Team 导入文本,提取 AT、邮箱、Account ID
        优先解析 [email]----[jwt]----[uuid] 等结构化格式

        Args:
            text: 导入的文本内容

        Returns:
            解析结果列表,每个元素包含 token, email, account_id
        """
        results = self._extract_team_entries_from_json(text)
        seen_signatures = {self._entry_signature(entry) for entry in results}

        # 对已经识别出的 JSON 片段做空白替换，避免逐行兜底重复命中
        non_json_text = self._remove_json_segments(text)

        # 按行分割文本
        lines = non_json_text.strip().split('\n')

        for line in lines:
            line = line.strip()
            if not line:
                continue

            token = None
            email = None
            account_id = None
            refresh_token = None
            session_token = None
            client_id = None

            # 1. 尝试使用分隔符解析 (支持 ----, | , \t, 以及多个空格)
            parts = [p.strip() for p in re.split(r'----|\||\t|\s{2,}', line) if p.strip()]
            
            if len(parts) >= 2:
                # 根据格式特征自动识别各部分
                for part in parts:
                    if not token and re.fullmatch(self.JWT_PATTERN, part):
                        token = part
                    elif not email and re.fullmatch(self.EMAIL_PATTERN, part):
                        email = part
                    elif not account_id and re.fullmatch(self.ACCOUNT_ID_PATTERN, part, re.IGNORECASE):
                        account_id = part
                    elif not refresh_token and re.match(self.REFRESH_TOKEN_PATTERN, part):
                        refresh_token = part
                    elif not session_token and re.match(self.SESSION_TOKEN_PATTERN, part):
                        # 如果已经有了 token (JWT)，则第二个匹配 JWT 模式的可能是 session_token
                        if token:
                            session_token = part
                        else:
                            token = part
                    elif not client_id and re.match(self.CLIENT_ID_PATTERN, part):
                        client_id = part

            # 2. 如果结构化解析未找到 Token，尝试全局正则提取结果 (兜底逻辑)
            if not token:
                tokens = re.findall(self.JWT_PATTERN, line)
                if tokens:
                    token = tokens[0]
                    if len(tokens) > 1:
                        session_token = tokens[1]
                
                # 只有在非结构化情况下才全局提取其他信息
                if not email:
                    emails = re.findall(self.EMAIL_PATTERN, line)
                    email = emails[0] if emails else None
                if not account_id:
                    account_ids = re.findall(self.ACCOUNT_ID_PATTERN, line, re.IGNORECASE)
                    account_id = account_ids[0] if account_ids else None
                if not refresh_token:
                    rts = re.findall(self.REFRESH_TOKEN_PATTERN, line)
                    refresh_token = rts[0] if rts else None
                if not client_id:
                    cids = re.findall(self.CLIENT_ID_PATTERN, line)
                    client_id = cids[0] if cids else None

            if token or session_token or refresh_token:
                entry = {
                    "token": token,
                    "email": email,
                    "account_id": account_id,
                    "refresh_token": refresh_token,
                    "session_token": session_token,
                    "client_id": client_id
                }
                signature = self._entry_signature(entry)
                if signature not in seen_signatures:
                    seen_signatures.add(signature)
                    results.append(entry)

        logger.info(f"解析完成,共提取 {len(results)} 条 Team 信息")
        return results

    def validate_jwt_format(self, token: str) -> bool:
        """
        验证 JWT Token 格式是否正确

        Args:
            token: JWT Token 字符串

        Returns:
            True 表示格式正确,False 表示格式错误
        """
        return bool(re.fullmatch(self.JWT_PATTERN, token))

    def validate_email_format(self, email: str) -> bool:
        """
        验证邮箱格式是否正确

        Args:
            email: 邮箱地址

        Returns:
            True 表示格式正确,False 表示格式错误
        """
        return bool(re.fullmatch(self.EMAIL_PATTERN, email))

    def validate_account_id_format(self, account_id: str) -> bool:
        """
        验证 Account ID 格式是否正确

        Args:
            account_id: Account ID

        Returns:
            True 表示格式正确,False 表示格式错误
        """
        return bool(re.fullmatch(self.ACCOUNT_ID_PATTERN, account_id))


# 创建全局实例
token_parser = TokenParser()
