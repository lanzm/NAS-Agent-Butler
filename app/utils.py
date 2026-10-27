# -*- coding: utf-8 -*-
"""
utils.py - 常用通用基础工具函数集合
涵盖：字节单位格式化、时间跨度可读格式化、候选路径降级探测等。
"""

import os
from typing import Optional, Union, List


def format_bytes(size: Optional[Union[int, float]], decimals: int = 1) -> str:
    """
    将字节大小转换为人类可读字符串 (B/KB/MB/GB/TB/PB)
    :param size: 字节数数值 (支持 None 或 0 兜底)
    :param decimals: 保留小数位数 (默认 1 位)
    """
    if size is None or size == 0:
        return "0B"
    try:
        val = float(size)
    except (ValueError, TypeError):
        return "0B"

    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    i = 0
    while val >= 1024.0 and i < len(units) - 1:
        val /= 1024.0
        i += 1

    if i == 0:
        return f"{int(val)}B"
    return f"{val:.{decimals}f}{units[i]}"


# 别名兼容，保留原有 human_bytes 契约
human_bytes = format_bytes


def format_duration_chinese(seconds: Union[int, float], compact: bool = False) -> str:
    """
    将秒数格式化为中文持续时间 (例如: '5天2小时', '3小时15分钟', '42分钟')
    :param seconds: 秒数数值
    :param compact: 若为 True，则最多保留前两级单位（如天+小时，或小时+分钟）
    """
    try:
        total_sec = max(0, int(seconds))
    except (ValueError, TypeError):
        return "未知"

    days = total_sec // 86400
    hours = (total_sec % 86400) // 3600
    minutes = (total_sec % 3600) // 60

    if compact:
        if days > 0:
            return f"{days}天{hours}小时"
        elif hours > 0:
            return f"{hours}小时{minutes}分钟"
        else:
            return f"{minutes}分钟"

    parts = []
    if days > 0:
        parts.append(f"{days}天")
    if hours > 0:
        parts.append(f"{hours}小时")
    if minutes > 0 or not parts:
        parts.append(f"{minutes}分钟")
    return "".join(parts) or "刚刚启动"


def find_first_existing_path(candidate_paths: List[str]) -> Optional[str]:
    """
    在多个候选路径中依次探测，返回首个存在的有效文件或目录路径
    """
    for p in candidate_paths:
        if p and os.path.exists(p):
            return p
    return None
