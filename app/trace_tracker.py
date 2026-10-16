# -*- coding: utf-8 -*-
"""
trace_tracker.py - 全链路调用链与阶段耗时追踪器 (开源规范版)
"""

import time
import uuid
import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger("butler.trace")

class TraceTracker:
    def __init__(self, trace_id: Optional[str] = None):
        self.trace_id = trace_id or f"tr_{uuid.uuid4().hex[:8]}"
        self.start_time = time.time()
        self.end_time: Optional[float] = None
        
        # 阶段耗时度量 (秒)
        self.first_thought_duration: float = 0.0
        self.tool_execution_duration: float = 0.0
        self.second_thought_duration: float = 0.0
        
        # 工具执行详情记录: [{"name": str, "duration": float, "status": "ok"|"error"}]
        self.tool_calls: List[Dict[str, Any]] = []
        
        # Token 消耗统计 (若 API 返回)
        self.prompt_tokens: int = 0
        self.completion_tokens: int = 0
        self.total_tokens: int = 0

    def mark_first_thought(self, duration: float):
        self.first_thought_duration = round(duration, 2)

    def record_tool_call(self, name: str, duration: float, status: str = "ok"):
        d = round(duration, 2)
        self.tool_execution_duration = round(self.tool_execution_duration + duration, 2)
        self.tool_calls.append({
            "name": name,
            "duration": d,
            "status": status
        })

    def mark_second_thought(self, duration: float):
        self.second_thought_duration = round(duration, 2)

    def record_tokens(self, usage: Optional[Dict[str, Any]]):
        if not usage or not isinstance(usage, dict):
            return
        self.prompt_tokens += usage.get("prompt_tokens", 0)
        self.completion_tokens += usage.get("completion_tokens", 0)
        self.total_tokens += usage.get("total_tokens", 0)

    def finish(self) -> float:
        self.end_time = time.time()
        return round(self.end_time - self.start_time, 2)

    @property
    def total_duration(self) -> float:
        if self.end_time is not None:
            return round(self.end_time - self.start_time, 2)
        return round(time.time() - self.start_time, 2)

    def get_summary_tag(self) -> str:
        """生成在飞书卡片底部渲染的极简灰色标签"""
        total = self.total_duration
        model_time = round(self.first_thought_duration + self.second_thought_duration, 2)
        tool_time = round(self.tool_execution_duration, 2)
        
        tool_count = len(self.tool_calls)
        tool_names = list(dict.fromkeys([t["name"] for t in self.tool_calls]))
        tool_str = f"{tool_count}步 [{', '.join(tool_names)}]" if tool_count > 0 else "0步直出"

        tag = f"⚡ 耗时: {total}s (模型: {model_time}s, 工具: {tool_time}s) · {tool_str} · #{self.trace_id}"
        if self.total_tokens > 0:
            tag += f" · 🪙 {self.total_tokens}T"
        return tag

    def log_trace_summary(self):
        """记录结构化日志供排障与审计"""
        logger.info(
            f"[TRACE_SUMMARY] ID=#{self.trace_id} Total={self.total_duration}s "
            f"First={self.first_thought_duration}s Tool={self.tool_execution_duration}s "
            f"Second={self.second_thought_duration}s Tools={self.tool_calls} "
            f"Tokens={self.total_tokens}"
        )
