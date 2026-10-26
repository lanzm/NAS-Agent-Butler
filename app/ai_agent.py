# -*- coding: utf-8 -*-
"""
ai_agent.py - 基于标准 MCP 协议与全链路 Trace 追踪的 NAS SRE 架构师智能体
彻底解耦：
1. 人设 Prompts 从 nas_mcp_server 动态拉取 (sre_engineer 深度全景分析版)；
2. 动作 Tools 从 nas_mcp_server 动态拉取并自动映射为 OpenAI Function Calling 规范；
3. 工具执行通过 MCPClient (stdio) 隔离调度，杜绝任意 Shell 注入后门；
4. 全程集成 TraceTracker 生成唯一 #tr_xxx 追踪标识与各阶段微秒级耗时统计。
"""

import os
import json
import time
import logging
import datetime
import threading
import requests
from typing import Dict, Any, Optional

from app.sanitizer import sanitize_text
from app.mcp_client import MCPClient
from app.trace_tracker import TraceTracker
from app.card_builder import clean_ai_content
from app.calendar_helper import format_datetime_chinese
from app.config import settings

logger = logging.getLogger("butler.agent")

# 工具执行中面向飞书状态胶囊的人性化提示映射
STATUS_MAP = {
    "generate_daily_report": "生成巡检日报",
    "get_system_health": "采集系统指标",
    "manage_docker_container": "查询容器状态",
    "manage_aria2_download": "查询下载进度",
    "manage_firewall_security": "查询安全防护",
    "search_web_info": "联网检索资讯",
    "manage_pc_power": "发送电源控制",
    "get_container_logs": "读取容器日志",
    "get_weather_calendar": "获取天气与日历",
}


class AIAgent:
    def __init__(self, collector=None):
        self.collector = collector
        self.api_key = settings.openai_api_key
        self.api_base = settings.openai_api_base.rstrip("/")
        self.model = settings.openai_model
        self.history = []
        self._lock = threading.Lock()
        self._mcp_client: Optional[MCPClient] = None

    @property
    def mcp_client(self) -> MCPClient:
        """按需懒加载并启动标准 MCP Client（避免模块加载时抢占拉起子进程）"""
        if self._mcp_client is None:
            with self._lock:
                if self._mcp_client is None:
                    logger.info("正在初始化 MCPClient 并拉起本地 nas_mcp_server...")
                    client = MCPClient()
                    client.start()
                    self._mcp_client = client
        return self._mcp_client

    @mcp_client.setter
    def mcp_client(self, client: Optional[MCPClient]):
        self._mcp_client = client

    def stop(self):
        """安全停止并回收 MCP Client 子进程"""
        with self._lock:
            if self._mcp_client is not None:
                try:
                    self._mcp_client.stop()
                except Exception:
                    pass
                self._mcp_client = None

    def __del__(self):
        try:
            self.stop()
        except Exception:
            pass

    def is_configured(self) -> bool:
        return bool(self.api_key and self.api_base)

    def _trim_history(self, max_messages: int = 10, max_chars: int = 8000):
        """智能截断多轮对话历史：兼顾轮次上限与字符预算，防止 Context 溢出与内存膨胀"""
        if len(self.history) > max_messages:
            self.history = self.history[-max_messages:]

        total_chars = sum(len(str(m.get("content", ""))) for m in self.history)
        while total_chars > max_chars and len(self.history) > 2:
            removed = self.history.pop(0)
            total_chars -= len(str(removed.get("content", "")))

    def _call_model(self, url: str, headers: dict, payload: dict, retries: int = 4) -> tuple:
        """发起大模型标准非流式请求。返回: (message_dict, usage_dict, error_msg)"""
        req_payload = dict(payload)
        req_payload["stream"] = False
        last_error = ""

        for attempt in range(retries):
            try:
                resp = requests.post(url, headers=headers, json=req_payload, timeout=60)
                if resp.status_code == 429:
                    wait_time = 2.0 * (attempt + 1)
                    logger.warning(f"API 触发 429 频控，等待 {wait_time:.1f} 秒后重试...")
                    time.sleep(wait_time)
                    continue
                elif resp.status_code in [500, 502, 503, 504]:
                    wait_time = 2.0 * (attempt + 1)
                    logger.warning(f"API 服务端状态码 [{resp.status_code}]，等待 {wait_time:.1f} 秒后重试...")
                    time.sleep(wait_time)
                    continue
                elif resp.status_code == 404:
                    err_text = resp.text
                    logger.warning(f"模型调用返回 404: {err_text[:150]}")
                    if "no longer available" in err_text or "not found" in err_text.lower():
                        for fallback_m in ["gemini-flash-lite-latest", "gemini-2.5-flash", "gpt-4o-mini", "deepseek-chat"]:
                            if req_payload.get("model") != fallback_m:
                                logger.info(f"平滑切换至备选模型: {fallback_m}")
                                req_payload["model"] = fallback_m
                                self.model = fallback_m
                                break
                        time.sleep(1.0)
                        continue

                if resp.status_code != 200:
                    try:
                        err_json = resp.json()
                        err_detail = err_json.get("error", {}).get("message") or err_json.get("message") or resp.text[:200]
                    except Exception:
                        err_detail = resp.text[:200]
                    last_error = f"[HTTP {resp.status_code}] {err_detail}"
                    logger.error(f"API 请求失败: {last_error}")
                    return None, None, last_error

                res_json = resp.json()
                choices = res_json.get("choices", [])
                if not choices:
                    return None, None, "模型响应中未包含有效 choices 内容"

                message = choices[0].get("message", {})
                usage = res_json.get("usage", {})
                return message, usage, None

            except requests.exceptions.RequestException as e:
                last_error = f"网络请求异常: {str(e)}"
                logger.error(f"请求异常 (尝试 {attempt+1}/{retries}): {e}")
                time.sleep(2.0 * (attempt + 1))

        return None, None, last_error or "模型服务连接超时或无响应"


    def chat(self, user_prompt: str, image_url: Optional[str] = None, status_callback=None) -> Dict[str, Any]:
        """
        处理单轮对话请求（支持文本与图片多模态），全程接入 Trace 耗时监控与 MCP 工具中继
        返回字典: {"text": str, "trace_tag": str, "trace_id": str}
        """
        if not self.is_configured():
            return {
                "text": "⚠️ **未检测到有效的 AI API 配置**\n请先在 `.env` 中配置 `OPENAI_API_KEY` 和 `OPENAI_API_BASE`。",
                "trace_tag": ""
            }

        trace = TraceTracker()
        prompt_desc = f"[图片] {user_prompt[:40]}" if image_url else user_prompt[:50]
        logger.info(f"[TRACE #{trace.trace_id}] 开始处理指令: {prompt_desc}")
        if status_callback:
            status_callback("思考中")

        with self._lock:
            # 1. 动态生成时间并从 MCP 动态拉取 sre_engineer Prompt
            now_str = format_datetime_chinese()
            
            system_content = self.mcp_client.get_prompt("sre_engineer", current_time=now_str)
            if not system_content:
                logger.warning("未能从 MCP Server 拉取到 sre_engineer Prompt，使用安全应急 Prompt")
                system_content = f"你是全能家庭智能管家。当前绝对时间为 {now_str}。兼备生活数码常识与专业 NAS 运维能力，按需响应用户需求，开门见山，绝不强加无关指标。"

            # 2. 动态从 MCP 获取转换后的 OpenAI 格式工具列表
            available_tools = self.mcp_client.get_openai_tools()

            # 3. 维护对话历史上下文 (智能滑动窗口与字符预算截断，支持图片多模态组装)
            if image_url:
                text_prompt = user_prompt if user_prompt else "请详细分析识别这张图片的内容，并给出专业分析与针对性结论。"
                current_user_content = [
                    {"type": "text", "text": text_prompt},
                    {"type": "image_url", "image_url": {"url": image_url}}
                ]
                # 历史记录仅存储文字摘要，避免多轮对话重复发送大体积 Base64 图片导致超限
                self.history.append({"role": "user", "content": f"[图片] {text_prompt}"})
                self._trim_history()
                messages = [{"role": "system", "content": system_content}] + list(self.history[:-1]) + [{"role": "user", "content": current_user_content}]
            else:
                self.history.append({"role": "user", "content": user_prompt})
                self._trim_history()
                messages = [{"role": "system", "content": system_content}] + list(self.history)

            url = f"{self.api_base}/chat/completions"
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }

            last_tool_name = ""
            last_tool_output = ""

            # 最多支持 3 轮工具调用迭代
            for round_idx in range(3):
                round_start_t = time.time()
                payload = {
                    "model": self.model,
                    "messages": messages,
                    "tools": available_tools,
                    "tool_choice": "auto"
                }

                logger.info(f"[TRACE #{trace.trace_id}] 第 {round_idx+1} 轮推理发起，消息数: {len(messages)}")
                message, usage, err_msg = self._call_model(url, headers, payload)
                round_duration = time.time() - round_start_t

                if round_idx == 0:
                    trace.mark_first_thought(round_duration)
                else:
                    trace.mark_second_thought(round_duration)

                if usage:
                    trace.record_tokens(usage)

                if message is None:
                    logger.error(f"[TRACE #{trace.trace_id}] 第 {round_idx+1} 轮推理 API 异常: {err_msg}")
                    trace.finish()
                    reply_content = f"⚠️ **AI 模型服务响应异常**\n> `{err_msg or '网络通信超时或上游未返回数据'}`"
                    self.history.append({"role": "assistant", "content": reply_content})
                    trace.log_trace_summary()
                    return {"text": reply_content, "trace_tag": trace.get_summary_tag(), "trace_id": trace.trace_id}

                raw_content = message.get("content")
                tool_calls = message.get("tool_calls")

                # 若模型未产生工具调用，直接输出分析结论
                if not tool_calls:
                    reply_content = clean_ai_content(raw_content)
                    if not reply_content:
                        if last_tool_name:
                            reply_content = f"已完成操作 `{last_tool_name}`。"
                        else:
                            reply_content = "已收到您的请求。"

                    trace.finish()
                    self.history.append({"role": "assistant", "content": reply_content})
                    trace.log_trace_summary()
                    return {"text": reply_content, "trace_tag": trace.get_summary_tag(), "trace_id": trace.trace_id}

                # 记录原生完整的助手回复对象 (完整保留 extra_content 与 thought_signature，杜绝 400 报错)
                messages.append(message)

                for tc in tool_calls:
                    call_id = tc.get("id")
                    func_name = tc.get("function", {}).get("name")
                    raw_args = tc.get("function", {}).get("arguments", "{}")
                    try:
                        args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                    except Exception:
                        args = {}

                    if status_callback:
                        status_callback(STATUS_MAP.get(func_name, "执行命令"))

                    logger.info(f"[TRACE #{trace.trace_id}] 触发 MCP 工具: {func_name}(args={args})")
                    
                    tool_t0 = time.time()
                    tool_res = self.mcp_client.call_tool(func_name, args)
                    tool_dur = time.time() - tool_t0
                    
                    status_flag = "error" if "error" in tool_res else "ok"
                    trace.record_tool_call(func_name, tool_dur, status_flag)

                    last_tool_name = func_name
                    content_str = json.dumps(tool_res, ensure_ascii=False)
                    last_tool_output = content_str

                    if status_callback:
                        status_callback("正在生成报告")

                    sanitized_content = sanitize_text(content_str)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": sanitized_content
                    })

            # 若经历了工具调用但尚未产生自然语言结论，强制追加终局归纳总结轮（关闭工具调用）
            logger.info(f"[TRACE #{trace.trace_id}] 发起终局归纳总结推理 (关闭工具调用通道)")
            if status_callback:
                status_callback("正在提炼结论")

            final_start_t = time.time()
            final_payload = {
                "model": self.model,
                "messages": messages,
            }
            final_message, final_usage, final_err = self._call_model(url, headers, final_payload)
            final_duration = time.time() - final_start_t
            trace.mark_second_thought(final_duration)
            if final_usage:
                trace.record_tokens(final_usage)

            trace.finish()

            if final_message and final_message.get("content"):
                reply_content = clean_ai_content(final_message.get("content"))
                if reply_content:
                    self.history.append({"role": "assistant", "content": reply_content})
                    self._trim_history()
                    trace.log_trace_summary()
                    return {"text": reply_content, "trace_tag": trace.get_summary_tag(), "trace_id": trace.trace_id}

            # 极端异常兜底：若有具体报错则直接透传上游信息
            if final_err:
                fallback_msg = f"已完成底层操作，但在提炼结论时 AI 服务响应异常：\n> `{final_err}`"
            elif last_tool_name:
                fallback_msg = f"已完成操作 `{last_tool_name}`，但由于网络响应延迟未能完成最终提炼，请稍后查看相关状态或重试。"
            else:
                fallback_msg = "❌ 连接 AI 服务异常，未收到有效回复。"
            self.history.append({"role": "assistant", "content": fallback_msg})
            self._trim_history()
            trace.log_trace_summary()
            return {"text": fallback_msg, "trace_tag": trace.get_summary_tag(), "trace_id": trace.trace_id}
