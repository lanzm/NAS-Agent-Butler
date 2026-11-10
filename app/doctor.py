# -*- coding: utf-8 -*-
"""
app/doctor.py - 全能管家系统环境与依赖自检引擎 (System Doctor)
提供针对 Docker、Aria2、WOL 唤醒、天气接口及 AI 模型网关连通性的深层体检，
支持 MCP 工具调度 (diagnose_system_health) 与终端运维一键巡检 (python -m app.doctor)。
"""

import sys
import json
import time
import socket
import logging
from typing import Dict, Any, List
import requests

from app.config import settings
from app.docker_client import get_docker_client
from app.plugins import aria2_plugin, pc_power_plugin

logger = logging.getLogger("butler.doctor")


class SystemDoctor:
    """系统运行环境体检与诊断器"""

    def check_docker(self) -> Dict[str, Any]:
        """检查 Docker 守护进程连接与容器状态"""
        client = get_docker_client()
        if not client:
            return {
                "status": "error",
                "message": "无法连接 Docker 守护进程（请检查宿主机 /var/run/docker.sock 挂载及用户权限）"
            }

        try:
            client.ping()
            containers = client.containers.list(all=True)
            running = [c for c in containers if getattr(c, "status", "") == "running"]
            return {
                "status": "ok",
                "message": f"Docker 守护进程连接正常，共 {len(containers)} 个容器（运行中: {len(running)}）",
                "total_containers": len(containers),
                "running_containers": len(running)
            }
        except Exception as e:
            return {
                "status": "error",
                "message": f"Docker 通信异常: {str(e)}"
            }

    def check_pc_power(self) -> Dict[str, Any]:
        """检查远程 PC 电源管理（WOL 网络唤醒）配置"""
        if not pc_power_plugin.is_enabled():
            reasons = []
            if not settings.enable_pc_power:
                reasons.append("ENABLE_PC_POWER 未启用")
            if not settings.target_pc_mac:
                reasons.append("未配置 TARGET_PC_MAC 地址")
            reason_str = "，".join(reasons) if reasons else "未开启或未配置"
            return {
                "status": "disabled",
                "message": f"PC 电源管理功能未激活（{reason_str}）"
            }

        mac = settings.target_pc_mac
        clean_mac = mac.replace(":", "").replace("-", "")
        if len(clean_mac) != 12:
            return {
                "status": "warning",
                "message": f"TARGET_PC_MAC 格式非法（当前值: {mac}，标准应为 12 位十六进制如 A0:36:BC:A9:EC:2C）"
            }

        # 测试 UDP 广播套接字创建权限
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            return {
                "status": "ok",
                "message": f"PC 电源管理已就绪，目标物理 MAC: `{mac}`（支持 UDP 局域网唤醒广播）",
                "mac": mac
            }
        except Exception as e:
            return {
                "status": "warning",
                "message": f"UDP 广播套接字创建失败（可能受限于网络命名空间）: {str(e)}",
                "mac": mac
            }

    def check_aria2(self) -> Dict[str, Any]:
        """检查 Aria2 离线下载插件连通性"""
        if not aria2_plugin.is_enabled():
            return {
                "status": "disabled",
                "message": "Aria2 离线下载插件未激活（未配置 ARIA2_RPC_URL 环境变量，非必选）"
            }

        try:
            ver_res = aria2_plugin.rpc_call("aria2.getVersion")
            version = ver_res.get("version", "未知")
            stat_res = aria2_plugin.rpc_call("aria2.getGlobalStat")
            active = int(stat_res.get("numActive", 0))
            waiting = int(stat_res.get("numWaiting", 0))
            return {
                "status": "ok",
                "message": f"Aria2 RPC 连接正常（版本: v{version}，当前下载中: {active}，等待中: {waiting}）",
                "version": version,
                "active_tasks": active,
                "waiting_tasks": waiting
            }
        except Exception as e:
            return {
                "status": "error",
                "message": f"无法连接 Aria2 RPC 服务（URL: {settings.aria2_rpc_url}）: {str(e)}"
            }

    def check_ai_gateway(self) -> Dict[str, Any]:
        """检查 AI 模型网关网络连通性与 HTTP 往返延迟"""
        api_base = getattr(settings, "openai_api_base", "") or getattr(settings, "ai_api_base", "") or ""
        api_key = getattr(settings, "openai_api_key", "") or getattr(settings, "ai_api_key", "") or ""

        if not api_base:
            return {
                "status": "error",
                "message": "未配置 OPENAI_API_BASE 或 AI_API_BASE 环境变量"
            }

        target_url = api_base.rstrip("/")
        # 如果带有 /v1beta/openai 等后缀，取探测端点或 models 路径
        probe_url = f"{target_url}/models" if not target_url.endswith("/models") else target_url

        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        start_t = time.time()
        try:
            resp = requests.get(probe_url, headers=headers, timeout=3.5)
            latency_ms = int((time.time() - start_t) * 1000)
            if resp.status_code in (200, 401, 403, 404):
                # 200 正常；401/403/404 说明至少网络握手成功、网关存活
                status = "ok" if resp.status_code == 200 else "warning"
                msg = f"AI 模型端点连通正常（HTTP {resp.status_code}，往返延迟: {latency_ms}ms）"
                if resp.status_code in (401, 403):
                    msg += "，但 API Key 凭据可能无效或权限不足"
                return {
                    "status": status,
                    "message": msg,
                    "latency_ms": latency_ms,
                    "http_code": resp.status_code
                }
            elif resp.status_code == 504:
                return {
                    "status": "error",
                    "message": f"AI 反向代理网关超时（HTTP 504 Gateway Timeout，耗时: {latency_ms}ms）",
                    "latency_ms": latency_ms,
                    "http_code": 504
                }
            else:
                return {
                    "status": "warning",
                    "message": f"AI 模型网关响应非预期状态（HTTP {resp.status_code}，耗时: {latency_ms}ms）",
                    "latency_ms": latency_ms,
                    "http_code": resp.status_code
                }
        except requests.Timeout:
            return {
                "status": "error",
                "message": "AI 模型网关连接超时（超过 3.5s 无响应，可能代理节点不稳定或遭遇网络阻断）"
            }
        except Exception as e:
            return {
                "status": "error",
                "message": f"AI 模型网关网络握手失败: {str(e)}"
            }

    def diagnose(self) -> Dict[str, Any]:
        """运行全项诊断，聚合健康评级与改善建议"""
        checks = {
            "docker": self.check_docker(),
            "pc_power": self.check_pc_power(),
            "aria2": self.check_aria2(),
            "ai_gateway": self.check_ai_gateway()
        }

        # 统计异常状态
        errors = [k for k, v in checks.items() if v.get("status") == "error"]
        warnings = [k for k, v in checks.items() if v.get("status") == "warning"]

        suggestions: List[str] = []
        if "docker" in errors:
            suggestions.append("检查宿主机 docker.sock 挂载及容器权限")
        if "pc_power" in warnings or checks["pc_power"].get("status") == "disabled":
            if not settings.enable_pc_power:
                suggestions.append("若需使用网络唤醒开机功能，请在 .env 中设置 ENABLE_PC_POWER=true")
            elif not settings.target_pc_mac:
                suggestions.append("请在 .env 中正确配置 TARGET_PC_MAC 地址")
        if "ai_gateway" in errors:
            suggestions.append("AI 端点超时或无法连接，请检查反代服务 (如 Vercel/Cloudflare) 连通性")
        if "aria2" in errors:
            suggestions.append("Aria2 RPC 连通失败，请确认下载容器端口与 RPC 密码是否正确")

        if errors:
            overall_status = "error"
            summary = f"检测到 {len(errors)} 项核心服务异常，建议优先排查！"
        elif warnings:
            overall_status = "warning"
            summary = f"核心服务运行平稳，发现 {len(warnings)} 项警告或未配置项。"
        else:
            overall_status = "healthy"
            summary = "所有核心服务与硬件集成运行正常，状态极佳！"

        return {
            "overall_status": overall_status,
            "summary": summary,
            "checks": checks,
            "suggestions": suggestions
        }


def format_cli_report(diag: Dict[str, Any]) -> str:
    """生成终端 ANSI / Unicode 优雅报告"""
    lines = [
        "=" * 56,
        "🩺  NAS Agent Butler - 系统环境与核心依赖体检报告",
        "=" * 56,
        f"综合评定: [{diag['overall_status'].upper()}] - {diag['summary']}",
        "-" * 56
    ]

    status_icon = {
        "ok": "✅ [PASS]",
        "warning": "⚠️  [WARN]",
        "error": "❌ [FAIL]",
        "disabled": "⚪ [OFF ]"
    }

    for name, item in diag.get("checks", {}).items():
        st = item.get("status", "unknown")
        tag = status_icon.get(st, "[ ?  ]")
        lines.append(f"{tag} {name.ljust(12)}: {item.get('message', '')}")

    if diag.get("suggestions"):
        lines.append("-" * 56)
        lines.append("💡 修复建议:")
        for idx, sug in enumerate(diag["suggestions"], 1):
            lines.append(f"  {idx}. {sug}")

    lines.append("=" * 56)
    return "\n".join(lines)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    doctor = SystemDoctor()
    report = doctor.diagnose()
    if "--json" in sys.argv:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(format_cli_report(report))
    sys.exit(1 if report.get("overall_status") == "error" else 0)
