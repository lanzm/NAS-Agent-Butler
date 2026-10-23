# -*- coding: utf-8 -*-
"""
card_builder.py - 飞书交互式消息卡片构建器 (分层渲染 + Trace 标签支持)
采用官方原生 markdown 组件规范，全面支持多行代码块 (```)、行内代码 (<text_tag color='neutral'>)、列表、加粗渲染与动态加载动效卡片
并在卡片底部无缝支持渲染全链路耗时与 Trace 追踪脚标。
"""

import os
import json
import re
from typing import Optional
from app.config import settings

I18N = {
    "zh": {
        "bot_title": "🤖 NAS 智能管家",
        "loading_title": "⚡ NAS 智能管家",
        "processing": "🌀 正在处理",
        "thinking": "思考中",
        "alarm_title": "🚨 NAS 系统异常告警",
        "status_title": "📊 NAS 系统运行概况",
        "active_alarms": "**⚠️ 当前活跃告警**：",
        "hardware_watermark": "**⚡ 核心运行水位**：",
        "cpu_usage": "• CPU 占用",
        "mem_usage": "• 内存占用",
        "disks_title": "**💾 磁盘与挂载点**：",
        "container_title": "**🐳 容器健康概况**",
        "container_summary": "共 `{total}` 个容器，`{running}` 个正在平稳运行。",
        "host_meta": "🖥️ 主机: `{hostname}` (`{host_ip}`) | ⏱️ 连续运行: `{uptime}`\n📅 采集时间: `{timestamp}`",
        "btn_status": "📊 查看系统概况",
        "btn_docker": "🐳 检查容器",
        "btn_cancel": "❌ 取消",
    },
    "en": {
        "bot_title": "🤖 NAS Smart Butler",
        "loading_title": "⚡ NAS Smart Butler",
        "processing": "🌀 Processing",
        "thinking": "Thinking",
        "alarm_title": "🚨 NAS System Alert",
        "status_title": "📊 NAS System Overview",
        "active_alarms": "**⚠️ Active Alerts**:",
        "hardware_watermark": "**⚡ Core System Metrics**:",
        "cpu_usage": "• CPU Usage",
        "mem_usage": "• Memory Usage",
        "disks_title": "**💾 Disks & Mount Points**:",
        "container_title": "**🐳 Container Health Overview**",
        "container_summary": "Total `{total}` containers, `{running}` running smoothly.",
        "host_meta": "🖥️ Host: `{hostname}` (`{host_ip}`) | ⏱️ Uptime: `{uptime}`\n📅 Collected: `{timestamp}`",
        "btn_status": "📊 System Overview",
        "btn_docker": "🐳 Check Containers",
        "btn_cancel": "❌ Cancel",
    }
}

def get_i18n(key: str, default: str = "") -> str:
    lang = "en" if os.getenv("DEFAULT_LANGUAGE", settings.default_language).strip().lower() == "en" else "zh"
    return I18N.get(lang, I18N["zh"]).get(key, default)


def format_feishu_markdown(text: str) -> str:
    """
    将标准 Markdown 格式转换为飞书卡片 Markdown 组件兼容格式：
    1. 保护多行代码块 (```...```) 不受任何干扰；
    2. 处理分割线 (---)：飞书要求 --- 前后必须有换行，且前后无空行时会被误判为标题下划线；转为严格换行包裹；
    3. 处理标题 (#, ##, ###, ####)：飞书卡片不支持 ### 及更小标题；
       将 ### 及 #### 转换为加粗小标题 (**标题**)；将 # / ## 标准化规范前置换行；
    4. 处理单反引号行内代码 (`code`)：转为飞书原生灰色中性标签 <text_tag color='neutral'>code</text_tag>；
    5. 清理多余空行，保持卡片紧凑排版。
    """
    if not text:
        return ""
    
    parts = re.split(r'(```[\s\S]*?```)', str(text))
    result = []
    for part in parts:
        if part.startswith('```') and part.endswith('```'):
            # 代码块内部完全原样保留
            result.append(part)
        else:
            # A. 彻底移除文本中裸露的分割线 (---, ***, ___ 等)，卡片分层应由原生 hr 组件负责
            converted = re.sub(r'(?m)^[ \t]*[-*_]{3,}[ \t]*$', '', part)
            
            # B. 彻底将所有层级的标题 (#, ##, ###, ####, #####) 转换为加粗文本，杜绝暴露 # 符号
            converted = re.sub(r'(?m)^#{1,6}\s*(.+?)\s*$', r'**\1**', converted)
            
            # C. 处理行内单反引号 `code` 转换为中性高亮标签
            converted = re.sub(r'(?<!`)`([^`\n]+?)`(?!`)', r"<text_tag color='neutral'>\1</text_tag>", converted)
            
            # D. 处理多余的连续空白换行
            converted = re.sub(r'\n{3,}', '\n\n', converted)
            
            result.append(converted)
            
    return "".join(result).strip()



def clean_ai_content(raw) -> str:
    """清洗 AI 返回的内容，剥离 JSON 包装（如 {'type': 'text', 'text': ...}）与转义字符，并做飞书 markdown 兼容转换"""
    if raw is None:
        return ""
    if not isinstance(raw, str):
        if isinstance(raw, dict) and "text" in raw:
            raw = str(raw["text"])
        elif isinstance(raw, list):
            texts = [item.get("text", "") for item in raw if isinstance(item, dict) and "text" in item]
            if texts:
                raw = "\n".join(texts)
            else:
                raw = str(raw)
        else:
            raw = str(raw)

    text = raw.strip()

    # 1. 优先尝试解析 JSON 结构
    if (text.startswith("{") and text.endswith("}")) or (text.startswith("[") and text.endswith("]")):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict) and "text" in parsed:
                text = str(parsed["text"]).strip()
            elif isinstance(parsed, list):
                texts = [item.get("text", "") for item in parsed if isinstance(item, dict) and "text" in item]
                if texts:
                    text = "\n".join(texts).strip()
        except Exception:
            pass

    # 2. 正则兜底防御：若存在 "text": "..."
    if text.startswith("{") and '"text"' in text:
        try:
            m = re.search(r'"text"\s*:\s*"(.*)"', text, re.DOTALL)
            if m:
                text = m.group(1)
        except Exception:
            pass

    # 3. 处理字面转义字符（如 \n, \t, \"）
    if "\\n" in text:
        text = text.replace("\\n", "\n")
    if "\\t" in text:
        text = text.replace("\\t", "\t")
    if '\\"' in text:
        text = text.replace('\\"', '"')

    # 4. 若大模型将整个回答包裹在 ```markdown ... ``` 或 ```text ... ``` 代码块中，剥离外层代码块外壳
    if text.startswith("```") and text.endswith("```"):
        lines = text.split("\n")
        if len(lines) >= 2:
            first_line = lines[0].strip().lower()
            if first_line in ["```", "```markdown", "```md", "```text"]:
                text = "\n".join(lines[1:-1]).strip()

    # 5. 转换为飞书卡片支持的 Markdown 格式（单反引号自动转为 neutral text_tag）
    return format_feishu_markdown(text.strip())


def build_status_card(data: dict, trace_tag: Optional[str] = None) -> dict:
    """构建 NAS 每日日报与系统全景状态卡片"""
    hostname = data.get("hostname", "NAS")
    host_ip = data.get("host_ip", "127.0.0.1")
    uptime = data.get("uptime", "未知")
    timestamp = data.get("timestamp", "")
    
    is_alarm = data.get("is_alarm", False)
    alarms = data.get("alarms", [])
    
    header_color = "red" if is_alarm else "blue"
    header_title = get_i18n("alarm_title") if is_alarm else get_i18n("status_title")
    
    elements = []
    
    # 1. 告警高亮展示
    if is_alarm and alarms:
        alarm_lines = [get_i18n("active_alarms")]
        for a in alarms:
            alarm_lines.append(f"• <font color='red'>**{a}**</font>")
        elements.append({
            "tag": "markdown",
            "content": format_feishu_markdown("\n".join(alarm_lines))
        })
        elements.append({"tag": "hr"})
        
    # 2. 硬件负载概览
    cpu_usage = data.get("cpu_usage", 0.0)
    cpu_temp = data.get("cpu_temp")
    temp_str = f" ({cpu_temp}°C)" if cpu_temp is not None else ""
    loadavg = data.get("loadavg", "未知")
    
    mem_usage = data.get("mem_usage", 0.0)
    mem_used = data.get("mem_used", "0 GB")
    mem_total = data.get("mem_total", "0 GB")
    
    hw_text = (
        f"{get_i18n('hardware_watermark')}\n"
        f"{get_i18n('cpu_usage')}: `{cpu_usage:.1f}%`{temp_str} | Load: `{loadavg}`\n"
        f"{get_i18n('mem_usage')}: `{mem_usage:.1f}%` (`{mem_used}` / `{mem_total}`)"
    )
    elements.append({
        "tag": "markdown",
        "content": format_feishu_markdown(hw_text)
    })
    
    # 3. 磁盘健康概况
    disks = data.get("disks", [])
    if disks:
        disk_lines = [get_i18n("disks_title")]
        for d in disks:
            mount = d.get("mount", "")
            percent = d.get("percent", 0.0)
            used = d.get("used", "0 GB")
            total = d.get("total", "0 GB")
            warning_mark = " ⚠️" if percent >= 90 else ""
            disk_lines.append(f"• `{mount}`: `{percent:.1f}%`{warning_mark} (`{used}` / `{total}`)")
        elements.append({
            "tag": "markdown",
            "content": format_feishu_markdown("\n".join(disk_lines))
        })
        
    # 4. Docker 容器状态
    containers = data.get("containers", [])
    if containers:
        total_c = len(containers)
        running_c = sum(1 for c in containers if c.get("status") == "running")
        elements.append({
            "tag": "markdown",
            "content": f"{get_i18n('container_title')}：" + get_i18n("container_summary").format(total=total_c, running=running_c)
        })
        
    # 5. 底部元数据
    elements.append({"tag": "hr"})
    footer_text = f"🖥️ 主机: `{hostname}` (`{host_ip}`) | ⏱️ 连续运行: `{uptime}`\n📅 采集时间: `{timestamp}`"
    if trace_tag:
        footer_text += f"\n<font color='grey'>{trace_tag}</font>"
        
    elements.append({
        "tag": "markdown",
        "content": format_feishu_markdown(footer_text)
    })
    
    return {
        "config": {
            "wide_screen_mode": True
        },
        "header": {
            "template": header_color,
            "title": {
                "tag": "plain_text",
                "content": header_title
            }
        },
        "elements": elements
    }


def build_loading_card(stage_text: str = "思考中", spinner: str = "", elapsed: float = 0.0) -> dict:
    """构建飞书原生状态胶囊标签 (Tag) 卡片（保留'正在处理'胶囊，文案精炼极简+动态秒数/跳点）"""
    clean_stage = stage_text.rstrip("。.…")
    if clean_stage == "思考中":
        clean_stage = get_i18n("thinking")
    dots = spinner or ""
    time_str = f" ({elapsed:.1f}s)" if elapsed >= 1.0 else ""
    dot_str = f" {dots}" if dots else ""
    suffix = f"{time_str}{dot_str}"
    processing_tag = get_i18n("processing")

    return {
        "config": {
            "wide_screen_mode": True
        },
        "header": {
            "template": "blue",
            "title": {
                "tag": "plain_text",
                "content": get_i18n("loading_title")
            }
        },
        "elements": [
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"<text_tag color='blue'>{processing_tag}</text_tag>　**{clean_stage}**{suffix}"
                }
            }
        ]
    }


def build_ai_response_card(content: str, title: Optional[str] = None, trace_tag: Optional[str] = None) -> dict:
    """构建 AI 自然语言诊断/回复卡片（使用原生 markdown 标签，底部支持可选 Trace 脚标）"""
    card_title = title or get_i18n("bot_title")
    safe_content = str(content) if content else ""
    if safe_content.count("```") % 2 != 0:
        safe_content = safe_content + "\n```"
    clean_text = clean_ai_content(safe_content)
    
    elements = [
        {
            "tag": "markdown",
            "content": clean_text
        }
    ]
    
    # 注入全链路跟踪灰色脚标
    if trace_tag:
        elements.append({"tag": "hr"})
        elements.append({
            "tag": "markdown",
            "content": f"<font color='grey'>{trace_tag}</font>"
        })

    return {
        "config": {
            "wide_screen_mode": True
        },
        "header": {
            "template": "indigo",
            "title": {
                "tag": "plain_text",
                "content": card_title
            }
        },
        "elements": elements
    }


def build_confirm_card(title: str, message: str, action_name: str, target: str) -> dict:
    """构建二次操作核准卡片 (防误触)"""
    clean_msg = format_feishu_markdown(message)
    elements = [
        {
            "tag": "markdown",
            "content": clean_msg
        },
        {"tag": "hr"},
        {
            "tag": "action",
            "actions": [
                {
                    "tag": "button",
                    "text": {
                        "tag": "plain_text",
                        "content": "✅ 确认执行"
                    },
                    "type": "danger",
                    "value": {
                        "action": action_name,
                        "target": target
                    }
                },
                {
                    "tag": "button",
                    "text": {
                        "tag": "plain_text",
                        "content": "❌ 取消"
                    },
                    "type": "default",
                    "value": {
                        "action": "cancel_action"
                    }
                }
            ]
        }
    ]
    return {
        "config": {
            "wide_screen_mode": True
        },
        "header": {
            "template": "orange",
            "title": {
                "tag": "plain_text",
                "content": title
            }
        },
        "elements": elements
    }


def build_message_card(title: str, content: str, template: str = "blue", show_back_button: bool = False, trace_tag: Optional[str] = None) -> dict:
    """通用消息卡片（原生 markdown 渲染，支持可选 Trace 脚标）"""
    if isinstance(content, str):
        if "\\n" in content:
            content = content.replace("\\n", "\n")
        if "\\t" in content:
            content = content.replace("\\t", "\t")
        if '\\"' in content:
            content = content.replace('\\"', '"')
    clean_content = format_feishu_markdown(content)
    elements = [
        {
            "tag": "markdown",
            "content": clean_content
        }
    ]
    
    if show_back_button:
        elements.append({"tag": "hr"})
        elements.append({
            "tag": "action",
            "actions": [
                {
                    "tag": "button",
                    "text": {
                        "tag": "plain_text",
                        "content": get_i18n("btn_status")
                    },
                    "type": "primary",
                    "value": {
                        "action": "refresh_status"
                    }
                },
                {
                    "tag": "button",
                    "text": {
                        "tag": "plain_text",
                        "content": get_i18n("btn_docker")
                    },
                    "type": "default",
                    "value": {
                        "action": "check_docker"
                    }
                }
            ]
        })
        
    if trace_tag:
        if not show_back_button:
            elements.append({"tag": "hr"})
        elements.append({
            "tag": "markdown",
            "content": f"<font color='grey'>{trace_tag}</font>"
        })
        
    return {
        "config": {
            "wide_screen_mode": True
        },
        "header": {
            "template": template,
            "title": {
                "tag": "plain_text",
                "content": title
            }
        },
        "elements": elements
    }
