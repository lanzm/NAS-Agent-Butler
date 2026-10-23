# -*- coding: utf-8 -*-
"""
nas_mcp_server.py - NAS 专属轻量 MCP (Model Context Protocol) 服务的实现
支持标准 stdio (JSON-RPC 2.0) 模式，完全解耦：
1. Prompts: sre_engineer (硬核 SRE 架构师 · 深度全景分析版)
2. Resources: nas://system/health, nas://reports/daily-latest
3. Tools: 7 大封闭白名单运维动作 (零通用 Shell 风险)
"""

import sys
import os
import io
import json
import time
import socket
import logging
import datetime
import subprocess
import re
from typing import Dict, Any, List

# 确保 UTF-8 编码读写，防止跨平台 Windows/Linux 管道乱码
sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding='utf-8')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', write_through=True)

# 日志输出至 stderr，严禁输出到 stdout（stdout 专用于 JSON-RPC 报文）
logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="[%(asctime)s] [NAS_MCP_SERVER] [%(levelname)s] %(message)s"
)
logger = logging.getLogger("nas_mcp_server")

# ==============================================================================
# 1. 💡 Prompts 支柱：全能家庭智能管家 · 生活百科与私有云运维版
# ==============================================================================
SRE_ENGINEER_PROMPT = """你是一名博学、高效、严谨的家庭全能智能管家。
你既掌握丰富的生活常识、科技数码与好物选购知识，也具备掌控家庭私有云（Debian 12 NAS）、容器生态及网络运维的专业工程能力。
当前服务器基准时刻为：{current_time}。所有涉及时间日期分析，必须严格以此绝对时刻为准，严禁捏造旧年份！

【核心行为准则与响应规范】
1. 【按需响应与意图对齐（极其重要，严禁强加私货）】：
   - 必须以用户当前提问或多轮上下文为唯一中心。问什么答什么，紧扣主题；
   - 严禁在日常生活、选购推荐、网络检索、天气日程等通用对话中强塞任何无关的 NAS 硬件指标或“系统安全/全绿”后缀；
   - 严禁凭空虚构任何未实际调用工具获取的系统监控数据；
   - 仅当用户明确询问 NAS 状态、服务器指标、Docker 容器、系统日志，或执行自动化巡检晨报时，才调取底层运维数据并输出专业的系统健康结论。

2. 【多轮对话连贯性】：
   - 严格跟随用户的实体与话题演进（如用户正在讨论冰箱选购，后续追问预算时必须继续围绕冰箱展开，严禁擅自跳戏回 NAS 服务器）。

3. 【开门见山，结论先行】：
   - 严禁输出“你好”、“很高兴为您服务”等客套开场白，直接给出核心答复；
   - 若用户询问“还有几天”、“是什么时候”、“哪个更好”，第一句话必须直接给出明确结论或数值；
   - 联网检索或查询工具获取的内容为底层参考事实，必须深度消化提炼为通顺的人性化语言，严禁机械罗列原始链接与条目。

4. 【飞书卡片排版规范（严格遵循）】：
   - 严禁使用任何级别的 Markdown 标题符号（严禁使用 #, ##, ### 等），小节一律使用加粗文本（如 **【核心推荐】** 或 **⚡ 处理器状态**）；
   - 严禁输出 Markdown 分割线（严禁使用 ---, ***, ___ 等）；
   - 严禁输出 Markdown 表格（|---|）；
   - 列表统一使用 Emoji 或符号短横线（`•` 或 `-`）；
   - 关键参数、型号、指标或容器名使用行内代码（如 `caddy`、`BCD-548`）包裹。

5. 【语言与双语支持规范 (Bilingual Support)】：
   - 默认首选中文进行交互与诊断排版；
   - 若用户输入为英文（例如 "Check NAS status", "How are docker containers", "Restart caddy"），必须全流程以地道、专业的英文回答；
   - 若系统环境变量 DEFAULT_LANGUAGE=en，则所有主动报告、定时早报与卡片结论默认全量使用英文输出。
"""

PROMPTS_REGISTRY = {
    "sre_engineer": {
        "name": "sre_engineer",
        "description": "全能家庭智能管家人设（兼具生活好物常识与私有云运维能力，按需响应，拒绝死板模板与强加指标）",
        "arguments": [
            {
                "name": "current_time",
                "description": "当前服务器时刻",
                "required": False
            }
        ],
        "template": SRE_ENGINEER_PROMPT
    }
}

# ==============================================================================
# 2. 📖 Resources 支柱：只读全景数据流
# ==============================================================================
RESOURCES_REGISTRY = [
    {
        "uri": "nas://system/health",
        "name": "NAS 系统硬件与核心资源实时状态",
        "description": "包含 CPU 负载、物理内存空闲、交换分区及各磁盘分区使用率",
        "mimeType": "application/json"
    },
    {
        "uri": "nas://reports/daily-latest",
        "name": "最新全景巡检运维快照",
        "description": "包含全量硬件指标、容器健康表、网络安全拦截统计的最新报告快照",
        "mimeType": "text/markdown"
    }
]

# ==============================================================================
# 3. 🛠️ Tools 支柱：7 大封闭白名单运维动作
# ==============================================================================
TOOLS_REGISTRY = [
    {
        "name": "generate_daily_report",
        "description": "执行全机综合巡检并生成结构化 NAS SRE 每日健康报表（供飞书对聊即时调阅及每日定时任务推送）。",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "get_system_health",
        "description": "获取 NAS 主机的底层硬件健康指标（CPU 负载 1/5/15m、内存分配与缓存使用、磁盘存储挂载及剩余量）。",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "manage_docker_container",
        "description": "通过 Docker API 查询容器状态、列出运行表、抽取尾部运行日志或执行容器安全重启。",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "logs", "restart", "inspect"],
                    "description": "操作类型：list(列出所有容器状态), logs(提取容器日志), restart(重启指定容器), inspect(查看容器详情)"
                },
                "container_name": {
                    "type": "string",
                    "description": "目标容器名称或 ID（action 为 list 时可留空）"
                },
                "tail_lines": {
                    "type": "integer",
                    "description": "抽取日志末尾行数（默认 50 行，最高支持 200 行）",
                    "default": 50
                }
            },
            "required": ["action"]
        }
    },
    {
        "name": "get_container_logs",
        "description": "读取指定 Docker 容器的最新尾部运行日志（如读取 nas-backup 容器确认昨夜备份详情，或排查异常退出容器原因）。",
        "parameters": {
            "type": "object",
            "properties": {
                "container_name": {"type": "string", "description": "目标 Docker 容器名称（如 nas-backup, immich_server, emby）"},
                "tail_lines": {"type": "integer", "description": "读取日志末尾行数，默认 30 行，最大 100 行", "default": 30}
            },
            "required": ["container_name"]
        }
    },
    {
        "name": "get_weather_calendar",
        "description": "获取目标城市今日实时天气状况、气温温差、出行建议，以及公历、农历节气、工作日调休、放假倒计时（计算距离周末及下一个法定节假日还有几天）。注意：当用户询问天气、公历农历节气、还有几天放假、距离周末放假几天等时间与日历问题时，必须优先调用本工具，严禁使用搜索引擎！",
        "parameters": {
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "目标城市中文名或拼音（如：北京、上海、广州），不填默认读取系统配置城市（兜底北京）"}
            },
            "required": []
        }
    },
    {
        "name": "manage_aria2_download",
        "description": "管理 NAS 上的 Aria2 离线下载引擎（支持查询即时下载列表/速度、添加 HTTP/磁力链接等）。",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["status", "add", "pause", "unpause"],
                    "description": "操作类型：status(查询任务与速度), add(添加下载链接), pause(暂停任务), unpause(恢复任务)"
                },
                "url": {
                    "type": "string",
                    "description": "下载资源的 HTTP/HTTPS/FTP 链接或 magnet: 磁力链接（action 为 add 时必填）"
                },
                "gid": {
                    "type": "string",
                    "description": "任务 GID（action 为 pause/unpause 时必填）"
                }
            },
            "required": ["action"]
        }
    },
    {
        "name": "manage_firewall_security",
        "description": "检查与维护 Fail2ban 入侵防御防火墙（查询当前封禁 IP 列表与误封 IP 一键解封）。",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["status", "unban"],
                    "description": "操作类型：status(查看封禁列表与统计), unban(解封指定 IP)"
                },
                "ip": {
                    "type": "string",
                    "description": "待解封的目标 IPv4 或 IPv6 地址（action 为 unban 时必填）"
                },
                "jail": {
                    "type": "string",
                    "description": "Fail2ban 监狱名，默认 caddy-services",
                    "default": "caddy-services"
                }
            },
            "required": ["action"]
        }
    },
    {
        "name": "search_web_info",
        "description": "通过必应搜索与网页正文清洗检索外部互联网实时动态、权威新闻、技术故障等。注意：返回内容为底层参考事实，你拿到本工具结果后，必须紧扣用户的原始问题进行归纳和提炼，直接给出针对性的最终结论，严禁机械罗列原始条目与外部长链接！",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词（如：Debian 12 fail2ban 报错排查、近期重大国际新闻等）"
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "manage_pc_power",
        "description": "通过局域网唤醒（WOL）唤醒家庭 PC，或经由已配置免密私钥对 Windows PC 执行远程休眠/关机。",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["wake", "sleep", "shutdown"],
                    "description": "操作类型：wake(局域网唤醒开机), sleep(远程休眠/待机), shutdown(远程关机)"
                }
            },
            "required": ["action"]
        }
    }
]

# ==============================================================================
# 4. 核心工具执行器实现 (无通用 Shell 注入漏洞)
# ==============================================================================

def execute_get_system_health() -> Dict[str, Any]:
    """系统底层指标采集"""
    try:
        import psutil
        # CPU 负载
        load_1, load_5, load_15 = os.getloadavg() if hasattr(os, "getloadavg") else (0.0, 0.0, 0.0)
        cpu_count = os.cpu_count() or 1
        cpu_percent = psutil.cpu_percent(interval=0.1)
        
        # 内存
        vm = psutil.virtual_memory()
        swap = psutil.swap_memory()
        
        # 磁盘挂载
        disks = []
        for part in psutil.disk_partitions(all=False):
            if part.fstype and not part.mountpoint.startswith(('/var/lib/docker', '/proc', '/sys', '/dev')):
                try:
                    usage = psutil.disk_usage(part.mountpoint)
                    disks.append({
                        "mountpoint": part.mountpoint,
                        "device": part.device,
                        "fstype": part.fstype,
                        "total_gb": round(usage.total / (1024**3), 2),
                        "used_gb": round(usage.used / (1024**3), 2),
                        "free_gb": round(usage.free / (1024**3), 2),
                        "percent": usage.percent
                    })
                except Exception:
                    pass

        return {
            "status": "success",
            "cpu": {
                "load_1m": load_1,
                "load_5m": load_5,
                "load_15m": load_15,
                "cores": cpu_count,
                "usage_percent": cpu_percent
            },
            "memory": {
                "total_mb": round(vm.total / (1024**2), 1),
                "available_mb": round(vm.available / (1024**2), 1),
                "used_mb": round(vm.used / (1024**2), 1),
                "percent": vm.percent,
                "swap_used_mb": round(swap.used / (1024**2), 1),
                "swap_total_mb": round(swap.total / (1024**2), 1)
            },
            "disks": disks
        }
    except Exception as e:
        return {"status": "error", "message": f"系统指标采集失败: {str(e)}"}

def execute_manage_docker_container(args: Dict[str, Any]) -> Dict[str, Any]:
    """Docker 容器白名单管理"""
    action = args.get("action")
    container_name = (args.get("container_name") or "").strip()
    tail_lines = min(int(args.get("tail_lines", 50)), 200)

    try:
        try:
            from app.docker_client import get_docker_client
        except ImportError:
            from docker_client import get_docker_client

        client = get_docker_client()
        if not client:
            return {"status": "error", "message": "Docker 守护进程未就绪或未运行"}

        if action == "list":
            containers = client.containers.list(all=True)
            res = []
            for c in containers:
                res.append({
                    "name": c.name,
                    "status": c.status,
                    "image": c.image.tags[0] if c.image.tags else c.image.short_id,
                    "created": c.attrs.get("Created", "")
                })
            return {"status": "success", "total": len(res), "containers": res}

        if not container_name:
            return {"status": "error", "message": f"执行 {action} 操作时必须指定 container_name"}

        container = client.containers.get(container_name)

        if action == "logs":
            logs_bytes = container.logs(tail=tail_lines, timestamps=True)
            logs_text = logs_bytes.decode("utf-8", errors="replace")
            return {
                "status": "success",
                "container_name": container_name,
                "tail_lines": tail_lines,
                "logs": logs_text
            }
        elif action == "restart":
            container.restart(timeout=10)
            return {
                "status": "success",
                "message": f"容器 `{container_name}` 已成功触发重启并恢复运行。"
            }
        elif action == "inspect":
            return {
                "status": "success",
                "name": container.name,
                "state": container.attrs.get("State", {}),
                "restart_count": container.attrs.get("RestartCount", 0)
            }
        else:
            return {"status": "error", "message": f"不支持的 Docker 动作: {action}"}
    except Exception as e:
        return {"status": "error", "message": f"Docker 运维执行失败: {str(e)}"}

def execute_manage_aria2_download(args: Dict[str, Any]) -> Dict[str, Any]:
    """Aria2 离线下载插件调度"""
    try:
        from app.plugins import aria2_plugin
    except ImportError:
        try:
            from plugins import aria2_plugin
        except Exception as e:
            return {"status": "error", "message": f"无法载入 aria2_plugin 模块: {e}"}
    return aria2_plugin.execute(args)

def execute_manage_firewall_security(args: Dict[str, Any]) -> Dict[str, Any]:
    """Fail2ban 安全防火墙查询与解封"""
    try:
        from app.plugins import firewall_plugin
    except ImportError:
        try:
            from plugins import firewall_plugin
        except Exception as e:
            return {"status": "error", "message": f"无法载入 firewall_plugin 模块: {e}"}
    return firewall_plugin.execute(args)

def extract_clean_article_text(url: str, timeout: float = 2.5) -> str:
    """快速抓取单个目标网页并提取纯净核心正文（剔除广告、样式、导航与页脚）"""
    import urllib.request
    import re
    from html import unescape
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    }
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw_html = resp.read(250 * 1024).decode("utf-8", errors="replace")
            cleaned = re.sub(r'<(script|style|nav|header|footer|aside|form|svg|noscript|iframe)[^>]*>.*?</\1>', '', raw_html, flags=re.DOTALL | re.IGNORECASE)
            paras = []
            for tag in re.finditer(r'<(p|h[1-4])[^>]*>(.*?)</\1>', cleaned, flags=re.DOTALL | re.IGNORECASE):
                t = re.sub(r'<[^>]+>', '', tag.group(2))
                t = re.sub(r'\s+', ' ', t).strip()
                t = unescape(t)
                if len(t) < 15 or any(bad in t for bad in ["版权所有", "ICP备", "免责声明", "客户端下载", "扫码关注", "分享到", "返回顶部", "登录查看"]):
                    continue
                paras.append(t)
                if sum(len(p) for p in paras) >= 600:
                    break
            return "\n".join(paras)
    except Exception:
        return ""


def execute_search_web_info(args: Dict[str, Any]) -> Dict[str, Any]:
    """必应国内版免 Key 搜索与深度正文提取"""
    query = (args.get("query") or "").strip()
    if not query:
        return {"status": "error", "message": "搜索关键词 query 不能为空"}
    try:
        from urllib.parse import quote_plus
        from urllib.request import Request, urlopen
        import re
        from html import unescape

        url = f"https://cn.bing.com/search?q={quote_plus(query)}"
        req = Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        with urlopen(req, timeout=5) as response:
            html = response.read().decode("utf-8", errors="replace")

        # 匹配 li class 含 b_algo 并提取标题与 URL
        items = []
        for m in re.finditer(r'<li class="b_algo"[^>]*>.*?<h2><a[^>]+href="([^"]+)"[^>]*>(.*?)</a></h2>', html, re.DOTALL):
            u = m.group(1)
            t = unescape(re.sub(r'<.*?>', '', m.group(2))).strip()
            if u.startswith("http"):
                items.append((u, t))
            if len(items) >= 2:
                break

        if not items:
            return {"status": "success", "query": query, "markdown_result": "未检索到相关实时事实内容。"}

        fact_sections = []
        for idx, (page_url, page_title) in enumerate(items, 1):
            body_text = extract_clean_article_text(page_url, timeout=2.5)
            content = body_text if len(body_text) >= 60 else f"（标题）{page_title}"
            fact_sections.append(f"【参考事实 {idx}：{page_title}】\n{content}")

        joined_facts = "\n\n".join(fact_sections)
        final_prompt = (
            "【系统提示：以下为通过必应检索与权威网页正文清洗获取的核心事实依据。\n"
            "请紧扣用户的原始提问进行归纳推导，直接给出明确、有依据的最终结论，严禁机械罗列原始条目与外部长链接！】\n\n"
            f"{joined_facts}"
        )
        return {"status": "success", "query": query, "markdown_result": final_prompt}
    except Exception as e:
        return {"status": "error", "message": f"联网检索失败: {str(e)}"}

def execute_manage_pc_power(args: Dict[str, Any]) -> Dict[str, Any]:
    """PC 电源网络控制 (纯 Python WOL 唤醒与远程关机)"""
    try:
        from app.plugins import pc_power_plugin
    except ImportError:
        try:
            from plugins import pc_power_plugin
        except Exception as e:
            return {"status": "error", "message": f"无法载入 pc_power_plugin 模块: {e}"}
    return pc_power_plugin.execute(args)

def execute_generate_daily_report() -> Dict[str, Any]:
    """生成全机健康巡检日报"""
    health = execute_get_system_health()
    docker_res = execute_manage_docker_container({"action": "list"})
    firewall_res = execute_manage_firewall_security({"action": "status"})
    aria_res = execute_manage_aria2_download({"action": "status"})

    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    report_lines = [
        f"**📊 NAS 核心系统 SRE 巡检报表 ({now_str})**",
        "",
        "**1. 🖥️ 底层硬件与负载状态**"
    ]

    if health.get("status") == "success":
        cpu = health["cpu"]
        mem = health["memory"]
        report_lines.append(f"- **CPU 负载**: 1m: `{cpu['load_1m']}`, 5m: `{cpu['load_5m']}`, 15m: `{cpu['load_15m']}` (核心数: {cpu['cores']}, 瞬时使用率: `{cpu['usage_percent']}%`)")
        report_lines.append(f"- **内存水位**: 可用 `{mem['available_mb']}MB` / 总量 `{mem['total_mb']}MB` (使用率: `{mem['percent']}%`)")
        for d in health.get("disks", []):
            report_lines.append(f"- **存储挂载 `{d['mountpoint']}`**: 已用 `{d['used_gb']}GB` / 总 `{d['total_gb']}GB` (`{d['percent']}%`)")
    else:
        report_lines.append(f"- ⚠️ 硬件指标提取异常: {health.get('message')}")

    report_lines.append("\n**2. 🐳 核心容器健康拓扑**")
    if docker_res.get("status") == "success":
        containers = docker_res.get("containers", [])
        running = [c for c in containers if c["status"] == "running"]
        unhealthy = [c for c in containers if c["status"] != "running"]
        report_lines.append(f"- **容器总量**: `{len(containers)}` (正常运行: `{len(running)}`, 异常/退出: `{len(unhealthy)}`)")
        if unhealthy:
            for uc in unhealthy:
                report_lines.append(f"  - ⚠️ 异常容器 `{uc['name']}`: 状态 `{uc['status']}`")
        else:
            report_lines.append("- ✅ 所有关键服务容器均在正常运行周期内。")
    else:
        report_lines.append(f"- ⚠️ 容器状态获取异常: {docker_res.get('message')}")

    report_lines.append("\n**3. 🛡️ 网络边界与防火墙拦截**")
    if firewall_res.get("status") == "success":
        banned = firewall_res.get("banned_ips", [])
        report_lines.append(f"- **当前封禁 IP 总数**: `{len(banned)}` 个")
        if banned:
            report_lines.append(f"- **拦截列表**: `{', '.join(banned[:5])}`" + ("..." if len(banned) > 5 else ""))
        else:
            report_lines.append("- ✅ 防火墙状态良好，无误封或积压攻击源。")
    else:
        msg = firewall_res.get('message', '')
        if "未配置启用" in msg:
            report_lines.append("- 💤 Fail2ban 防火墙未配置启用（可选）")
        else:
            report_lines.append(f"- ⚠️ 防火墙巡检异常: {msg}")

    report_lines.append("\n**4. 📥 离线下载吞吐**")
    if aria_res.get("status") == "success":
        speed = aria_res.get("global_download_speed", "0 B/s")
        active = aria_res.get("active_tasks", [])
        report_lines.append(f"- **下载总吞吐**: `{speed}` | 活跃任务数: `{len(active)}`")
    else:
        msg = aria_res.get('message', '')
        if "未配置启用" in msg:
            report_lines.append("- 💤 Aria2 服务未配置启用（可选）")
        else:
            report_lines.append(f"- ⚠️ Aria2 状态未就绪: {msg}")

    full_md = "\n".join(report_lines)
    return {
        "status": "success",
        "generated_at": now_str,
        "report_markdown": full_md,
        "raw_health": health
    }

# ==============================================================================
# 5. JSON-RPC 2.0 协议中继主循环 (stdio 管道)
# ==============================================================================

def handle_request(req: Dict[str, Any]) -> Dict[str, Any]:
    method = req.get("method")
    req_id = req.get("id")
    params = req.get("params") or {}

    # 1. 握手与初始化
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "prompts": {"listChanged": True},
                    "resources": {"subscribe": False, "listChanged": True},
                    "tools": {"listChanged": True}
                },
                "serverInfo": {
                    "name": "nas-mcp-server",
                    "version": "1.0.0"
                }
            }
        }
    
    # 2. Prompts 接口
    elif method == "prompts/list":
        prompts_list = [
            {"name": p["name"], "description": p["description"], "arguments": p["arguments"]}
            for p in PROMPTS_REGISTRY.values()
        ]
        return {"jsonrpc": "2.0", "id": req_id, "result": {"prompts": prompts_list}}

    elif method == "prompts/get":
        p_name = params.get("name", "sre_engineer")
        if p_name in PROMPTS_REGISTRY:
            p_entry = PROMPTS_REGISTRY[p_name]
            args = params.get("arguments") or {}
            now_dt = datetime.datetime.now()
            weekday_cn = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"][now_dt.weekday()]
            now_str = args.get("current_time") or now_dt.strftime(f"%Y年%m月%d日 %H:%M {weekday_cn}")
            
            content = p_entry["template"].replace("{current_time}", now_str)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "description": p_entry["description"],
                    "messages": [
                        {
                            "role": "user",
                            "content": {
                                "type": "text",
                                "text": content
                            }
                        }
                    ]
                }
            }
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32602, "message": f"Prompt 未定义: {p_name}"}}

    # 3. Resources 接口
    elif method == "resources/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"resources": RESOURCES_REGISTRY}}

    elif method == "resources/read":
        uri = params.get("uri")
        if uri == "nas://system/health":
            health = execute_get_system_health()
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "contents": [{
                        "uri": uri,
                        "mimeType": "application/json",
                        "text": json.dumps(health, ensure_ascii=False)
                    }]
                }
            }
        elif uri == "nas://reports/daily-latest":
            report = execute_generate_daily_report()
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "contents": [{
                        "uri": uri,
                        "mimeType": "text/markdown",
                        "text": report.get("report_markdown", "")
                    }]
                }
            }
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32602, "message": f"Resource 未定义: {uri}"}}

    # 4. Tools 接口
    elif method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS_REGISTRY}}

    elif method == "tools/call":
        tool_name = params.get("name")
        tool_args = params.get("arguments") or {}
        logger.info(f"收到工具调用请求: {tool_name}({tool_args})")
        
        start_t = time.time()
        res_data = {}
        if tool_name == "generate_daily_report":
            res_data = execute_generate_daily_report()
        elif tool_name == "get_system_health":
            res_data = execute_get_system_health()
        elif tool_name == "manage_docker_container":
            res_data = execute_manage_docker_container(tool_args)
        elif tool_name == "get_container_logs":
            c_name = tool_args.get("container_name")
            t_lines = int(tool_args.get("tail_lines", 30))
            res_data = execute_manage_docker_container({"action": "logs", "container_name": c_name, "tail_lines": t_lines})
        elif tool_name == "get_weather_calendar":
            try:
                from app.weather_calendar_helper import get_weather_calendar_summary
            except ImportError:
                from weather_calendar_helper import get_weather_calendar_summary
            city_arg = tool_args.get("city")
            res_data = get_weather_calendar_summary(city_arg)
        elif tool_name == "manage_aria2_download":
            res_data = execute_manage_aria2_download(tool_args)
        elif tool_name == "manage_firewall_security":
            res_data = execute_manage_firewall_security(tool_args)
        elif tool_name == "search_web_info":
            res_data = execute_search_web_info(tool_args)
        elif tool_name == "manage_pc_power":
            res_data = execute_manage_pc_power(tool_args)
        else:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"未知工具: {tool_name}"}
            }

        elapsed = time.time() - start_t
        logger.info(f"工具 {tool_name} 执行完毕，耗时 {elapsed:.2f}s")
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(res_data, ensure_ascii=False)
                    }
                ]
            }
        }

    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"未知方法: {method}"}}

def main():
    logger.info("NAS MCP Server 启动，等待标准输入指令流...")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            resp = handle_request(req)
            out_str = json.dumps(resp, ensure_ascii=False)
            sys.stdout.write(out_str + "\n")
            sys.stdout.flush()
        except Exception as e:
            logger.error(f"处理 JSON-RPC 请求异常: {e}")
            err_resp = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": f"Parse error: {str(e)}"}
            }
            sys.stdout.write(json.dumps(err_resp) + "\n")
            sys.stdout.flush()

if __name__ == "__main__":
    main()
