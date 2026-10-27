# -*- coding: utf-8 -*-
"""
status.py - 全局交互阶段与运维状态统一常量定义
所有状态文案严格遵守 <= 6 字约束，杜绝魔法字符串散落。
"""

try:
    from enum import StrEnum
except ImportError:
    from enum import Enum

    class StrEnum(str, Enum):
        pass


class TaskStatus(StrEnum):
    """前置接入与 AI 核心流转阶段状态 (严格 <= 6字)"""
    # 1. 前置消息输入处理阶段
    AUDIO_RECEIVING = "收听语音中"
    AUDIO_TRANSCRIBING = "识别语音中"
    IMAGE_ANALYZING = "分析图片中"

    # 2. AI 核心推理与总结阶段
    REQUEST_CLOUD_MODEL = "请求云端模型"
    GENERATE_REPORT = "生成报告中"
    SUMMARIZE_CONCLUSION = "提炼结论中"


# 3. 封闭白名单 MCP 本地运维工具动作映射 (100% 覆盖，严格 <= 6字，杜绝含糊兜底)
TOOL_STATUS_MAP: dict[str, str] = {
    "get_system_health": "采集系统指标",
    "manage_docker_container": "查询容器状态",
    "get_container_logs": "读取容器日志",
    "get_weather_calendar": "查询天气日历",
    "search_web_info": "联网检索资讯",
    "generate_daily_report": "生成巡检日报",
    "manage_pc_power": "发送电源控制",
    "manage_aria2_download": "查询下载进度",
    "manage_firewall_security": "查询安全防护",
}
