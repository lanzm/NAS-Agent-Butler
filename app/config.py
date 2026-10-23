# -*- coding: utf-8 -*-
"""
config.py - 系统核心配置与类型安全校验层
提供环境变量读取、类型转换、边界检查与缺省兜底，杜绝因格式错误导致程序崩溃。
"""

import os
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("butler.config")


def get_int(key: str, default: int, min_val: Optional[int] = None, max_val: Optional[int] = None) -> int:
    """安全解析整型环境变量，带范围边界校验"""
    val_str = os.getenv(key, "").strip()
    if not val_str:
        return default
    try:
        val = int(val_str)
        if min_val is not None and val < min_val:
            logger.warning(f"配置项 {key}={val} 低于安全下限 {min_val}，自动取为 {min_val}")
            return min_val
        if max_val is not None and val > max_val:
            logger.warning(f"配置项 {key}={val} 超出安全上限 {max_val}，自动取为 {max_val}")
            return max_val
        return val
    except ValueError:
        logger.warning(f"配置项 {key}='{val_str}' 格式非法（非有效整数），已安全降级为默认值 {default}")
        return default


def get_str(key: str, default: str = "") -> str:
    """安全读取字符串环境变量"""
    return os.getenv(key, default).strip()


@dataclass
class ButlerConfig:
    # 告警阈值配置 (百分比与度数)
    disk_threshold: int = 95
    cpu_threshold: int = 85
    mem_threshold: int = 90
    temp_threshold: int = 80
    alarm_cooldown: int = 3600

    # 基础行为配置
    daily_report_time: str = "08:00"
    default_city: str = "北京"
    default_language: str = "zh"

    # 大模型凭据
    openai_api_key: str = ""
    openai_api_base: str = "https://api.openai.com/v1"
    openai_model: str = "gemini-flash-lite-latest"

    # 飞书凭据
    feishu_app_id: str = ""
    feishu_app_secret: str = ""
    feishu_receive_id: str = ""

    @classmethod
    def load(cls) -> "ButlerConfig":
        """从当前环境加载并校验配置"""
        return cls(
            disk_threshold=get_int("DISK_THRESHOLD", 95, min_val=10, max_val=99),
            cpu_threshold=get_int("CPU_THRESHOLD", 85, min_val=10, max_val=99),
            mem_threshold=get_int("MEM_THRESHOLD", 90, min_val=10, max_val=99),
            temp_threshold=get_int("CPU_TEMP_THRESHOLD", 80, min_val=30, max_val=110),
            alarm_cooldown=get_int("ALARM_COOLDOWN", 3600, min_val=60, max_val=86400),
            daily_report_time=get_str("DAILY_REPORT_TIME", "08:00"),
            default_city=get_str("DEFAULT_CITY", "北京") or "北京",
            default_language=get_str("DEFAULT_LANGUAGE", "zh").lower(),
            openai_api_key=get_str("OPENAI_API_KEY", ""),
            openai_api_base=get_str("OPENAI_API_BASE", "https://api.openai.com/v1"),
            openai_model=get_str("OPENAI_MODEL", "gemini-flash-lite-latest") or "gemini-flash-lite-latest",
            feishu_app_id=get_str("FEISHU_APP_ID", ""),
            feishu_app_secret=get_str("FEISHU_APP_SECRET", ""),
            feishu_receive_id=get_str("FEISHU_RECEIVE_ID", ""),
        )


settings = ButlerConfig.load()
