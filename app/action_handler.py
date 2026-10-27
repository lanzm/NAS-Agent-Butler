# -*- coding: utf-8 -*-
"""
action_handler.py - 飞书用户指令与交互动作分发器 (MCP + Trace 适配版)
"""
from typing import Optional
from app.collector import SystemCollector
from app.card_builder import (
    build_status_card,
    build_ai_response_card,
    build_message_card,
    get_i18n
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
        
        title = get_i18n("image_analysis_title") if image_url else get_i18n("bot_title")
        card = build_ai_response_card(content=content_text, title=title, trace_tag=trace_tag)
        return "CARD", card

    def handle_card_action(self, action_value: dict) -> dict:
        """响应历史卡片中的按钮交互动作"""
        act = action_value.get("action")
        
        if act == "refresh_status":
            new_data = self.collector.collect()
            new_card = build_status_card(new_data)
            return {
                "toast": {
                    "type": "success",
                    "content": get_i18n("toast_status_refreshed")
                },
                "card": new_card
            }
            
        elif act == "check_docker":
            prompt = get_i18n("check_docker_prompt")
            ai_res = self.agent.chat(prompt)
            return {
                "toast": {
                    "type": "info",
                    "content": get_i18n("toast_docker_updated")
                },
                "card": build_ai_response_card(
                    ai_res.get("text", "已更新。"),
                    title=get_i18n("check_docker_title"),
                    trace_tag=ai_res.get("trace_tag")
                )
            }

        elif act == "cancel_action":
            return {
                "toast": {
                    "type": "info",
                    "content": get_i18n("toast_op_cancelled")
                },
                "card": build_message_card(
                    title=get_i18n("cancel_op_title"),
                    content=get_i18n("cancel_op_content"),
                    template="grey"
                )
            }
            
        return {
            "toast": {
                "type": "warning",
                "content": get_i18n("toast_unknown_action", action=act)
            }
        }
