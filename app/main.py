# -*- coding: utf-8 -*-
"""
main.py - NAS 智能运维管家主入口守护进程
支持：
- 架构全面升级为可扩展的 Channel 通道适配器模式（开箱即支持飞书，预留 Telegram/企业微信等无缝接入能力）；
- 多平台统一消息调度、广播通知与晨报卡片分发；
- 每日定时系统健康/生活早报推送 (基于 schedules.json 自主配置)；
- 5分钟系统指标后台自动巡检与异常告警；
- 本地微型 Webhook 服务（127.0.0.1:8999），用于接收本地脚本与容器的安全报警。
"""

import os
import json
import yaml
import time
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Optional, Dict, Any, List
from dotenv import load_dotenv

try:
    import schedule
except ImportError:
    schedule = None

from app.collector import SystemCollector
from app.action_handler import ActionHandler
from app.channels import ChannelManager, FeishuChannel
from app.card_builder import (
    build_status_card,
    build_ai_response_card,
    build_message_card
)

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("butler")

load_dotenv()

try:
    from app.config import settings
except ImportError:
    from config import settings

# --- 类型安全的系统配置 ---
DISK_THRESHOLD = settings.disk_threshold
CPU_THRESHOLD = settings.cpu_threshold
MEM_THRESHOLD = settings.mem_threshold
CPU_TEMP_THRESHOLD = settings.temp_threshold
DAILY_REPORT_TIME = settings.daily_report_time
ALARM_COOLDOWN = settings.alarm_cooldown

# --- 核心实例初始化 ---
collector = SystemCollector(
    disk_threshold=DISK_THRESHOLD,
    cpu_threshold=CPU_THRESHOLD,
    mem_threshold=MEM_THRESHOLD,
    temp_threshold=CPU_TEMP_THRESHOLD
)
action_handler = ActionHandler(collector)

# --- 多 IM 通道管理器 ---
channel_manager = ChannelManager()

# 1. 注册飞书通道 (若配置有效则自动激活)
feishu_channel = FeishuChannel(action_handler)
channel_manager.register(feishu_channel)

# 2. [预留通道扩展位] 未来的 Telegram / 企微等通道直接在此注册：
# tg_channel = TelegramChannel(action_handler)
# channel_manager.register(tg_channel)

# --- 报警状态记录（加锁保障调度线程与回调并发安全） ---
_alarm_lock = threading.Lock()
last_alarm_time = 0
prev_alarm_state = False


def load_scheduled_tasks() -> list:
    """加载定时任务配置（从 config/schedules.yaml 读取，纯 YAML 规范）"""
    possible_paths = [
        "/app/config/schedules.yaml",
        "/app/config/schedules.yml",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config", "schedules.yaml"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config", "schedules.yml"),
        os.path.join(os.getcwd(), "config", "schedules.yaml"),
        os.path.join(os.getcwd(), "config", "schedules.yml"),
    ]
    for p in possible_paths:
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    tasks = yaml.safe_load(f)
                    if isinstance(tasks, list):
                        logger.info(f"成功从 YAML 配置文件加载 {len(tasks)} 个定时任务: {p}")
                        return tasks
            except Exception as e:
                logger.error(f"解析定时任务 YAML 配置文件失败 ({p}): {e}")

    # 默认兜底任务
    default_prompt = (
        "请先调用 get_weather_calendar 获取今日天气状况、温差、出行建议、农历节气及放假倒计时（距离周末/法定节假日），"
        "再综合分析宿主机健康状态、各容器运行状态，并检查常见备份容器（如 nas-backup、restic、duplicati 等，未部署则直接跳过）。"
        "输出一份精炼专业的晨报，分为【今日生活简报】【系统核心结论】【运行水位】【备份报告】【风险与建议】五段。在【今日生活简报】中注明放假倒计时，在【备份报告】中总结昨夜备份状态（未部署可注明无），语言专业生动，限 260 字以内。"
    )
    return [
        {
            "name": "🌅 今日 SRE 运维与生活晨报",
            "time": DAILY_REPORT_TIME or "08:00",
            "enabled": True,
            "prompt": default_prompt
        },
        {
            "name": "🔍 系统健康例行巡检与智能诊断",
            "interval_minutes": 5,
            "enabled": True,
            "notify_on_recovery": True,
            "thresholds": {
                "cpu": 85,
                "memory": 90,
                "disk": 95,
                "cpu_temp": 80
            }
        }
    ]


def execute_scheduled_agent_task(task_name: str, prompt: str):
    """触发定时 Agent 任务：由大模型自主调用 MCP 工具链并向所有活跃通道广播推送"""
    logger.info(f"⏰ [定时任务触发] 正在执行: [{task_name}]")
    try:
        ai_res = action_handler.agent.chat(prompt)
        content_text = ai_res.get("text", "定时任务已执行完毕。")
        trace_tag = ai_res.get("trace_tag", "")

        # 构造高颜值交互卡片
        card = build_ai_response_card(
            content=content_text,
            title=f"🤖 {task_name}",
            trace_tag=trace_tag
        )

        # 统一向所有激活的通道分发广播
        results = channel_manager.broadcast_card(card)
        logger.info(f"✅ 定时任务 [{task_name}] 广播推送完成: {results}")
    except Exception as e:
        logger.error(f"❌ 定时任务 [{task_name}] 执行异常: {e}")


def run_health_check_task(task_config: dict):
    """周期性系统指标巡检与智能诊断任务（支持 thresholds 覆盖、静默判定、AI 深度排查与恢复闭环）"""
    global last_alarm_time, prev_alarm_state
    task_name = task_config.get("name", "系统健康例行巡检")
    thresholds = task_config.get("thresholds")
    notify_on_recovery = task_config.get("notify_on_recovery", True)
    prompt_template = task_config.get("prompt")

    try:
        data = collector.collect(thresholds=thresholds)
        is_alarm = data.get("is_alarm", False)
        alarms = data.get("alarms", [])
        now = time.time()

        with _alarm_lock:
            if is_alarm:
                if not prev_alarm_state or (now - last_alarm_time > ALARM_COOLDOWN):
                    logger.warning(f"检测到系统异常告警 [{task_name}]: {alarms}")
                    if prompt_template:
                        alarm_context = "\n".join(f"- {a}" for a in alarms)
                        full_prompt = (
                            f"{prompt_template.strip()}\n\n"
                            f"【系统当前检测到的活跃异常告警】：\n{alarm_context}"
                        )
                        ai_res = action_handler.agent.chat(full_prompt)
                        content_text = ai_res.get("text", "异常诊断分析完成。")
                        trace_tag = ai_res.get("trace_tag", "")
                        card = build_ai_response_card(
                            content=content_text,
                            title=f"🚨 {task_name}",
                            trace_tag=trace_tag
                        )
                        card["header"]["template"] = "red"
                    else:
                        card = build_status_card(data)

                    channel_manager.broadcast_card(card)
                    last_alarm_time = now
                    prev_alarm_state = True
            else:
                if prev_alarm_state:
                    logger.info(f"系统各项指标已从异常中恢复正常 [{task_name}]")
                    if notify_on_recovery:
                        card = build_status_card(data)
                        card["header"]["template"] = "green"
                        card["header"]["title"]["content"] = "✅ NAS 运行指标恢复正常"
                        channel_manager.broadcast_card(card)
                    prev_alarm_state = False
    except Exception as e:
        logger.error(f"[{task_name}] 巡检异常: {e}")


def run_scheduler_loop():
    """后台定时任务调度引擎（通用触发器与分发器）"""
    if not schedule:
        logger.warning("未安装 schedule 模块，定时任务引擎跳过启动")
        return

    tasks = load_scheduled_tasks()
    active_count = 0
    for t in tasks:
        if not t.get("enabled", True):
            continue

        task_name = t.get("name", "未命名任务")
        has_thresholds = "thresholds" in t
        time_str = t.get("time")
        interval_min = t.get("interval_minutes")

        # 确定执行动作 (Action)
        if has_thresholds:
            action_fn = (lambda task=t: run_health_check_task(task))
        else:
            prompt = t.get("prompt", "")
            action_fn = (lambda name=task_name, p=prompt: execute_scheduled_agent_task(name, p))

        # 注册触发器 (Trigger)
        if time_str:
            schedule.every().day.at(str(time_str)).do(action_fn)
            logger.info(f"  └─ 已注册每日定点任务: [{task_name}] (每日 {time_str})")
            active_count += 1
        elif interval_min is not None:
            try:
                mins = int(interval_min)
                schedule.every(mins).minutes.do(action_fn)
                logger.info(f"  └─ 已注册周期巡检任务: [{task_name}] (每 {mins} 分钟)")
                active_count += 1
            except ValueError:
                logger.error(f"任务 [{task_name}] 的 interval_minutes 配置无效: {interval_min}")

    logger.info(f"定时调度引擎已就绪: 共激活 {active_count} 个调度任务")
    while not _shutdown_event.is_set():
        schedule.run_pending()
        _shutdown_event.wait(10)


class InternalNotifyHandler(BaseHTTPRequestHandler):
    """本地内部通知 Webhook 处理程序（只监听 127.0.0.1）"""

    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"status":"healthy"}')
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/notify":
            try:
                content_length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(content_length).decode('utf-8')
                data = json.loads(body)

                title = data.get("title", "🚨 安全网关告警")
                content = data.get("content", "")
                template = data.get("template", "red")

                logger.info(f"收到内部事件通知: {title}")
                card = build_message_card(
                    title=title,
                    content=content,
                    template=template,
                    show_back_button=False
                )

                # 向所有通道分发此内部告警
                results = channel_manager.broadcast_card(card)

                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok", "delivered": results}).encode('utf-8'))
            except Exception as e:
                logger.error(f"处理内部告警异常: {e}")
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))
        elif self.path == "/health":
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"status":"healthy"}')
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass


_shutdown_event = threading.Event()
_webhook_server: Optional[HTTPServer] = None


def run_internal_webhook_server():
    """启动仅监听 127.0.0.1:8999 的本地微型 HTTP 服务"""
    global _webhook_server
    try:
        _webhook_server = HTTPServer(('127.0.0.1', 8999), InternalNotifyHandler)
        logger.info("内部通知 Webhook 服务已启动 -> http://127.0.0.1:8999/notify")
        _webhook_server.serve_forever()
    except Exception as e:
        if not _shutdown_event.is_set():
            logger.error(f"启动内部通知 Webhook 失败: {e}")


def graceful_shutdown(signum=None, frame=None):
    """优雅安全停机：释放所有子进程、关闭 HTTP 服务、断开 WebSocket 长连接"""
    logger.info("收到停机信号，执行优雅安全退出...")
    _shutdown_event.set()

    # 1. 停止通道
    try:
        channel_manager.stop_all()
    except Exception as e:
        logger.error(f"关闭通道服务异常: {e}")

    # 2. 关闭内部 Webhook 服务
    global _webhook_server
    if _webhook_server:
        try:
            _webhook_server.shutdown()
        except Exception as e:
            logger.error(f"关闭 Webhook 服务异常: {e}")

    # 3. 关闭 MCP Client 子进程
    try:
        if hasattr(action_handler, "agent") and hasattr(action_handler.agent, "mcp_client"):
            action_handler.agent.mcp_client.stop()
    except Exception as e:
        logger.error(f"关闭 MCP Client 异常: {e}")

    logger.info("所有服务已安全终止，进程退出。")


def main():
    logger.info("=== NAS 多平台智能运维管家正在启动 ===")

    try:
        import signal
        signal.signal(signal.SIGTERM, graceful_shutdown)
        signal.signal(signal.SIGINT, graceful_shutdown)
    except Exception:
        pass

    # 1. 启动后台定时任务
    scheduler_thread = threading.Thread(target=run_scheduler_loop, daemon=True, name="SchedulerThread")
    scheduler_thread.start()

    # 2. 启动内部本地通知 Webhook 服务 (127.0.0.1:8999)
    webhook_thread = threading.Thread(target=run_internal_webhook_server, daemon=True, name="WebhookThread")
    webhook_thread.start()

    # 3. 启动所有已启用的通道 (例如飞书 WebSocket 长连接)
    channel_manager.start_all()

    # 4. 守护主线程常驻
    try:
        while not _shutdown_event.is_set():
            _shutdown_event.wait(3600)
    except (KeyboardInterrupt, SystemExit):
        graceful_shutdown()


if __name__ == "__main__":
    main()
