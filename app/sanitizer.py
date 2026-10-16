# -*- coding: utf-8 -*-
"""
sanitizer.py - 敏感信息脱敏与安全过滤工具
在任何数据（日志、配置、环境参数）发送给云端 AI 之前，进行深度清洗与脱敏，确保内网资产与凭证绝对安全。
"""

import re
import os

# 常见敏感键名正则匹配 (不区分大小写)
SENSITIVE_KEY_PATTERN = re.compile(
    r'(?i)(password|passwd|pwd|pass|db_pass|secret|token|api_key|apikey|app_secret|bduss|access_token|auth|private_key)\s*([:=])\s*([\'"]?)([^\s\'",;]{2,})\3'
)

# 常见 API Key 与 Token 格式正则
TOKEN_PATTERNS = [
    (re.compile(r'sk-[a-zA-Z0-9_-]{16,}'), '[PROTECTED_API_KEY]'),
    (re.compile(r'nvapi-[a-zA-Z0-9_-]{16,}'), '[PROTECTED_NV_KEY]'),
    (re.compile(r'Bearer\s+[a-zA-Z0-9_\-\.]{15,}'), 'Bearer [PROTECTED_TOKEN]'),
    (re.compile(r'cli_[a-zA-Z0-9]{16,}'), '[PROTECTED_APP_ID]'),
    # 数据库连接串中的密码部分 postgres://user:password@host:port
    (re.compile(r'(postgres(?:ql)?|mysql|redis|mongodb)://([^:]+):([^@]+)@'), r'\1://\2:[PROTECTED_DB_PWD]@'),
]


def sanitize_text(text: str) -> str:
    """
    通用文本脱敏函数：
    1. 动态比对并抹除当前环境变量中的真实敏感密钥
    2. 基于正则清洗日志与消息中的密码、Token、数据库连接串
    """
    if not text:
        return text

    # 1. 动态抹除当前系统加载的所有敏感环境变量值（最彻底的保底）
    sensitive_env_keys = [
        "FEISHU_APP_SECRET",
        "FEISHU_APP_ID",
        "OPENAI_API_KEY",
        "AI_API_KEY",
        "PEXELS_API_KEY",
        "ARIA2_SECRET",
        "PC_REMOTE_PASSWD",
        "PC_REMOTE_USER",
    ]
    for env_name in sensitive_env_keys:
        real_val = os.getenv(env_name, "").strip()
        if real_val and len(real_val) >= 4:
            text = text.replace(real_val, f"[PROTECTED_{env_name}]")

    # 2. 正则脱敏 key=value 类型的字段 (如 password=123456 -> password=[PROTECTED])
    text = SENSITIVE_KEY_PATTERN.sub(r'\1\2\3[PROTECTED]\3', text)

    # 3. 正则脱敏特定格式的 Token / Key / 数据库密码
    for pattern, replacement in TOKEN_PATTERNS:
        text = pattern.sub(replacement, text)

    return text
