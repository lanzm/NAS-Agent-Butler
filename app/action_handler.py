# -*- coding: utf-8 -*-
"""
action_handler.py - 飞书用户指令与交互动作分发器 (MCP + Trace 适配版)
"""
import os
from typing import Optional
from app.collector import SystemCollector
from app.card_builder import (
    build_status_card,
    build_ai_response_card,
    build_message_card
)
from app.ai_agent import AIAgent

class ActionHandler:
    def __init__(self, collector: SystemCollector):
        self.collector = collector
        self.agent = AIAgent()

    def handle_text_command(self, text: str, image_url: Optional[str] = None, status_callback=None):
        """所有用户输入一律交由全能 AI Agent 理解与 MCP 工具调度（支持图片多模态），回传卡片与 Trace 脚标"""
        cmd = text.strip() if text else ""
        ai_result = self.agent.chat(cmd, image_url=image_url, status_callback=status_callback)
        content_text = ai_result.get("text", "已处理。")
        trace_tag = ai_result.get("trace_tag", "")
        
        lang = os.getenv("DEFAULT_LANGUAGE", "zh").strip().lower()
        if image_url:
            title = "🖼️ Image Analysis" if lang == "en" else "🖼️ 图片视觉诊断"
        else:
            title = "🤖 NAS Smart Butler" if lang == "en" else "🤖 NAS 家庭智能管家"
        card = build_ai_response_card(content=content_text, title=title, trace_tag=trace_tag)
        return "CARD", card

    def handle_card_action(self, action_value: dict) -> dict:
        """响应历史卡片中的按钮交互动作"""
        act = action_value.get("action")
        lang = os.getenv("DEFAULT_LANGUAGE", "zh").strip().lower()
        
        if act == "refresh_status":
            new_data = self.collector.collect()
            new_card = build_status_card(new_data)
            toast_msg = "✅ System metrics refreshed" if lang == "en" else "✅ 系统指标已刷新"
            return {
                "toast": {
                    "type": "success",
                    "content": toast_msg
                },
                "card": new_card
            }
            
        elif act == "check_docker":
            prompt = (
                "Please inspect the health status and abnormal exits of all Docker containers from an SRE architect perspective."
                if lang == "en"
                else "请以 SRE 架构师视角深度检查当前所有 Docker 容器拓扑健康状态与异常退出情况"
            )
            ai_res = self.agent.chat(prompt)
            toast_msg = "🐳 Containers updated" if lang == "en" else "🐳 容器状态已更新"
            title = "🐳 Docker Container Health Inspection" if lang == "en" else "🐳 Docker 容器拓扑健康诊断"
            return {
                "toast": {
                    "type": "info",
                    "content": toast_msg
                },
                "card": build_ai_response_card(
                    ai_res.get("text", "已更新。"),
                    title=title,
                    trace_tag=ai_res.get("trace_tag")
                )
            }
            
        toast_unknown = f"Unknown action: {act}" if lang == "en" else f"未知动作: {act}"
        return {
            "toast": {
                "type": "warning",
                "content": toast_unknown
            }
        }
