# -*- coding: utf-8 -*-
"""
channel.py - Telegram 通道实现 (TelegramChannel)
基于官方 Telegram Bot API 实现，原生支持：
1. Long Polling (长轮询) 双向交互，无需公网 IP 与反向代理穿透；
2. 跨渠道富文本卡片无缝转码为 Telegram 原生 HTML 格式（支持 Inline Keyboard 按钮）；
3. 交互按钮防超时异步解耦与即时 Toast 弹窗反馈；
4. 目标 Chat ID 安全鉴权与首个交互者自动绑定闭环。
"""

import re
import html
import time
import logging
import threading
import requests
from typing import Optional, Dict, Any, Tuple, List

from app.channels.base import BaseChannel
from app.action_handler import ActionHandler
from app.card_builder import get_i18n
from app.config import settings

logger = logging.getLogger("butler.telegram")

_RE_TEXT_TAG = re.compile(r"<text_tag[^>]*>(.*?)</text_tag>", re.IGNORECASE)
_RE_FONT_TAG = re.compile(r"<font[^>]*>(.*?)</font>", re.IGNORECASE)
_RE_CODE_BLOCK = re.compile(r"```([a-zA-Z0-9_\+\-]*)?\n?([\s\S]*?)```")
_RE_INLINE_CODE = re.compile(r"`([^`\n]+)`")
_RE_BOLD_DOUBLE = re.compile(r"\*\*([^\*\n]+?)\*\*")
_RE_BOLD_SINGLE = re.compile(r"(?<!\w)\*(?!\s)([^\*\n]+?)(?<!\s)\*(?!\w)")
_RE_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^\s\)]+)\)")


def convert_markdown_to_telegram_html(text: str) -> str:
    """
    将标准 Markdown 及飞书富文本标签转换为 Telegram Bot 原生支持的 HTML 格式。
    相比 Markdown/MarkdownV2，HTML 模式对点号、连字符、下划线具备极高容错性，杜绝 400 解析报错。
    """
    if not text:
        return ""

    # 1. 净化飞书专有标签
    text = _RE_TEXT_TAG.sub(r"`\1`", text)
    text = _RE_FONT_TAG.sub(r"\1", text)

    # 2. 隔离并保护多行代码块 (Code Blocks)
    code_blocks: List[str] = []

    def _save_code_block(match: re.Match) -> str:
        lang = (match.group(1) or "").strip().lower()
        code_content = match.group(2)
        escaped_code = html.escape(code_content, quote=False)
        if lang:
            block_html = f'<pre><code class="language-{lang}">{escaped_code}</code></pre>'
        else:
            block_html = f"<pre><code>{escaped_code}</code></pre>"
        placeholder = f"___TG_CODE_BLOCK_{len(code_blocks)}___"
        code_blocks.append(block_html)
        return placeholder

    text = _RE_CODE_BLOCK.sub(_save_code_block, text)

    # 3. 隔离并保护行内代码 (Inline Code)
    inline_codes: List[str] = []

    def _save_inline_code(match: re.Match) -> str:
        code_text = html.escape(match.group(1), quote=False)
        placeholder = f"___TG_INLINE_CODE_{len(inline_codes)}___"
        inline_codes.append(f"<code>{code_text}</code>")
        return placeholder

    text = _RE_INLINE_CODE.sub(_save_inline_code, text)

    # 4. 对正文文本做严格 HTML 转义 (杜绝未闭合 <, >, & 语法冲突)
    text = html.escape(text, quote=False)

    # 5. 解析 Markdown 格式语法 (加粗、强调、链接)
    text = _RE_BOLD_DOUBLE.sub(r"<b>\1</b>", text)
    text = _RE_BOLD_SINGLE.sub(r"<b>\1</b>", text)

    def _format_link(match: re.Match) -> str:
        safe_url = match.group(2).replace('"', '%22')
        return f'<a href="{safe_url}">{match.group(1)}</a>'

    text = _RE_LINK.sub(_format_link, text)

    # 6. 还原行内代码与代码块
    for i, code_html in enumerate(inline_codes):
        text = text.replace(f"___TG_INLINE_CODE_{i}___", code_html)

    for i, block_html in enumerate(code_blocks):
        text = text.replace(f"___TG_CODE_BLOCK_{i}___", block_html)

    return text


def card_to_telegram_payload(card_data: Any) -> Tuple[str, Optional[Dict[str, Any]]]:
    """
    将系统统一卡片结构转换为 Telegram HTML 消息正文与 InlineKeyboard 交互组件。
    :return: (text: str, reply_markup: Optional[dict])
    """
    if not isinstance(card_data, dict):
        return convert_markdown_to_telegram_html(str(card_data)), None

    lines: List[str] = []

    # 1. 解析标题 (Header)
    header_title = card_data.get("header", {}).get("title", {}).get("content", "").strip()
    if header_title:
        lines.append(f"<b>{html.escape(header_title)}</b>\n")

    inline_keyboard: List[List[Dict[str, str]]] = []
    current_btn_row: List[Dict[str, str]] = []

    # 2. 解析正文组件 (Elements)
    for elem in card_data.get("elements", []):
        tag = elem.get("tag", "")

        if tag == "markdown":
            content = elem.get("content", "")
            lines.append(convert_markdown_to_telegram_html(content))

        elif tag == "div":
            content = elem.get("text", {}).get("content", "")
            lines.append(convert_markdown_to_telegram_html(content))

        elif tag == "hr":
            lines.append("────────────────────")

        elif tag == "action":
            # 提取卡片内联交互按钮
            for act in elem.get("actions", []):
                btn_text = act.get("text", {}).get("content", "").strip() or "按钮"
                val = act.get("value", {})
                action_name = val.get("action", "") if isinstance(val, dict) else str(val)
                if action_name:
                    current_btn_row.append({
                        "text": btn_text,
                        "callback_data": action_name
                    })

    if current_btn_row:
        # 每行最多排列 2 个按钮，保持移动端整齐舒展
        for i in range(0, len(current_btn_row), 2):
            inline_keyboard.append(current_btn_row[i:i + 2])

    full_text = "\n".join(lines).strip()
    # 限制单条消息最大字符预算，防止超出 Telegram 4096 字符上限报错
    if len(full_text) > 4000:
        full_text = full_text[:3980] + "\n...(内容已截断)"

    reply_markup = {"inline_keyboard": inline_keyboard} if inline_keyboard else None
    return full_text or "（空消息）", reply_markup


class TelegramChannel(BaseChannel):
    """Telegram Bot 接入通道"""

    def __init__(self, action_handler: ActionHandler):
        self.action_handler = action_handler
        self.bot_token = settings.telegram_bot_token
        self.chat_id = settings.telegram_chat_id
        self.proxy = settings.telegram_proxy

        self.api_base = f"https://api.telegram.org/bot{self.bot_token}"
        self._is_running = False
        self._thread: Optional[threading.Thread] = None
        self._last_update_id = 0

        self.session = requests.Session()
        if self.proxy:
            self.session.proxies = {"http": self.proxy, "https": self.proxy}

    @property
    def name(self) -> str:
        return "telegram"

    @property
    def display_name(self) -> str:
        return "Telegram"

    def is_enabled(self) -> bool:
        """只要配置了有效的 TELEGRAM_BOT_TOKEN 且非示例占位符，即自动激活"""
        token = (self.bot_token or "").strip()
        return bool(token and not token.startswith("your_") and not token.startswith("cli_"))

    def send_message(self, target_id: Optional[str], content: str, title: Optional[str] = None, **kwargs) -> bool:
        """主动发送纯文本或 Markdown 通知消息（自动转换为 HTML 格式）"""
        dest = target_id or self.chat_id
        if not dest or not self.is_enabled():
            return False

        conv_content = convert_markdown_to_telegram_html(content)
        if title:
            text = f"<b>{html.escape(title)}</b>\n\n{conv_content}"
        else:
            text = conv_content
        return self._send_raw_message(dest, text)

    def send_card(self, target_id: Optional[str], card_data: Any, **kwargs) -> bool:
        """主动发送结构化排版卡片与内联按钮"""
        dest = target_id or self.chat_id
        if not dest or not self.is_enabled():
            return False

        text, reply_markup = card_to_telegram_payload(card_data)
        return self._send_raw_message(dest, text, reply_markup=reply_markup)

    def _send_raw_message(self, chat_id: str, text: str, reply_markup: Optional[dict] = None) -> bool:
        """底层 HTTP 发送封装（支持 HTML 格式与安全纯文本降级）"""
        url = f"{self.api_base}/sendMessage"
        payload: Dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup

        try:
            resp = self.session.post(url, json=payload, timeout=15)
            if resp.status_code == 200:
                return True
            # 若 HTML 格式解析冲突导致 400，降级为纯文本安全重试
            if resp.status_code == 400:
                payload.pop("parse_mode", None)
                fallback_resp = self.session.post(url, json=payload, timeout=15)
                return fallback_resp.status_code == 200
            logger.warning(f"Telegram 发送消息失败 [HTTP {resp.status_code}]: {resp.text[:150]}")
            return False
        except Exception as e:
            logger.error(f"Telegram 消息发送异常: {e}")
            return False

    def _send_chat_action(self, chat_id: str, action: str = "typing"):
        """向客户端发送 '正在输入...' 状态指示器"""
        try:
            url = f"{self.api_base}/sendChatAction"
            self.session.post(url, json={"chat_id": chat_id, "action": action}, timeout=5)
        except Exception:
            pass

    def _answer_callback_query(self, query_id: str, text: str = "") -> bool:
        """响应按钮点击事件并在客户端弹出 Toast 气泡"""
        try:
            url = f"{self.api_base}/answerCallbackQuery"
            payload = {"callback_query_id": query_id, "text": text}
            resp = self.session.post(url, json=payload, timeout=8)
            return resp.status_code == 200
        except Exception as e:
            logger.debug(f"响应 callback query 异常: {e}")
            return False

    def _edit_message(self, chat_id: str, message_id: int, card_data: Any) -> bool:
        """原地更新历史卡片正文与按钮（无感刷新）"""
        url = f"{self.api_base}/editMessageText"
        text, reply_markup = card_to_telegram_payload(card_data)
        payload: Dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup

        try:
            resp = self.session.post(url, json=payload, timeout=15)
            if resp.status_code == 200:
                return True
            if resp.status_code == 400:
                payload.pop("parse_mode", None)
                fb = self.session.post(url, json=payload, timeout=15)
                return fb.status_code == 200
            return False
        except Exception as e:
            logger.error(f"Telegram 编辑消息异常: {e}")
            return False

    def _handle_incoming_message(self, msg: dict):
        """处理用户私聊或群聊文本输入"""
        chat = msg.get("chat", {})
        chat_id = str(chat.get("id", ""))
        text = (msg.get("text") or "").strip()

        if not chat_id or not text:
            return

        # 安全鉴权逻辑
        if self.chat_id:
            if chat_id != str(self.chat_id):
                logger.warning(f"Telegram 拦截非管理员用户的交互请求 (chat_id: {chat_id})")
                self.send_message(chat_id, "⛔ *权限拒绝*: 当前 NAS 智能管家仅限授权管理员使用。")
                return
        else:
            # 首次交互自动绑定管理员
            self.chat_id = chat_id
            settings.telegram_chat_id = chat_id
            logger.info(f"✅ [Telegram] 自动记忆并绑定管理员 chat_id: {chat_id}")

        # 针对 /start 或 /help 输出交互欢迎卡片
        if text in ("/start", "/help"):
            welcome_card = {
                "header": {"title": {"content": get_i18n("bot_title")}},
                "elements": [
                    {
                        "tag": "markdown",
                        "content": "👋 您好！我是您的 **NAS 专属全能运维管家**。\n支持随时查询服务器健康、Docker 容器拓扑、生活天气以及网络控制。"
                    },
                    {"tag": "hr"},
                    {
                        "tag": "action",
                        "actions": [
                            {"text": {"content": get_i18n("btn_status")}, "value": {"action": "refresh_status"}},
                            {"text": {"content": get_i18n("btn_docker")}, "value": {"action": "check_docker"}}
                        ]
                    }
                ]
            }
            self.send_card(chat_id, welcome_card)
            return

        # 发送输入中指示器
        self._send_chat_action(chat_id, "typing")

        try:
            # 统一分发至核心 ActionHandler
            mode, card = self.action_handler.handle_text_command(text)
            self.send_card(chat_id, card)
        except Exception as e:
            logger.error(f"处理 Telegram 用户指令异常: {e}")
            self.send_message(chat_id, f"⚠️ 诊断执行异常: `{str(e)}`")

    def _handle_incoming_callback(self, query: dict):
        """处理卡片内联键盘按钮点击 (Inline Keyboard Callback)"""
        query_id = query.get("id", "")
        message = query.get("message", {})
        chat_id = str(message.get("chat", {}).get("id", ""))
        msg_id = message.get("message_id")
        action_name = query.get("data", "").strip()

        if not query_id or not chat_id:
            return

        # 权限校验
        if self.chat_id and chat_id != str(self.chat_id):
            self._answer_callback_query(query_id, text="⛔ 未授权用户")
            return

        action_val = {"action": action_name}

        # 针对耗时较长的 check_docker 动作实施异步解耦防超时
        if action_name == "check_docker":
            toast_text = get_i18n("toast_docker_analyzing", "🐳 正在排查中")
            self._answer_callback_query(query_id, text=toast_text)

            def _async_inspect():
                try:
                    res = self.action_handler.handle_card_action(action_val)
                    if isinstance(res, dict) and "card" in res:
                        self._edit_message(chat_id, msg_id, res["card"])
                except Exception as ex:
                    logger.error(f"Telegram 异步检查容器失败: {ex}")

            threading.Thread(target=_async_inspect, daemon=True, name="TgAsyncAction").start()
            return

        # 普通同步动作（如 refresh_status、cancel_action）
        try:
            res = self.action_handler.handle_card_action(action_val)
            toast_text = res.get("toast", {}).get("content", "")
            self._answer_callback_query(query_id, text=toast_text)
            if "card" in res:
                self._edit_message(chat_id, msg_id, res["card"])
        except Exception as e:
            logger.error(f"Telegram 处理按钮回调失败: {e}")
            self._answer_callback_query(query_id, text=f"执行失败: {e}")

    def _poll_loop(self):
        """基于官方 Long Polling 的消息监听主循环"""
        logger.info(f"Telegram 监听循环已就绪 (Long Polling)...")

        while self._is_running:
            url = f"{self.api_base}/getUpdates"
            params = {
                "offset": self._last_update_id + 1,
                "timeout": 20
            }
            try:
                resp = self.session.get(url, params=params, timeout=25)
                if resp.status_code == 200:
                    data = resp.json()
                    for update in data.get("result", []):
                        up_id = update.get("update_id", 0)
                        if up_id > self._last_update_id:
                            self._last_update_id = up_id

                        if "message" in update:
                            threading.Thread(
                                target=self._handle_incoming_message,
                                args=(update["message"],),
                                daemon=True,
                                name=f"TgMsg-{up_id}"
                            ).start()
                        elif "callback_query" in update:
                            threading.Thread(
                                target=self._handle_incoming_callback,
                                args=(update["callback_query"],),
                                daemon=True,
                                name=f"TgCb-{up_id}"
                            ).start()
                elif resp.status_code in (401, 404):
                    logger.error(f"Telegram Bot Token 无效或未找到，停止监听循环 [HTTP {resp.status_code}]")
                    break
                else:
                    time.sleep(2)
            except requests.Timeout:
                # 正常的长轮询超时，直接继续下一轮
                continue
            except Exception as e:
                if self._is_running:
                    logger.debug(f"Telegram 长轮询网络波动: {e}")
                    time.sleep(3)

        logger.info("Telegram 监听循环已安全退出。")

    def start(self):
        """启动 Telegram 长轮询后台监听"""
        if not self.is_enabled():
            logger.info("未配置有效的 TELEGRAM_BOT_TOKEN，Telegram 通道跳过启动")
            return

        self._is_running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True, name="TelegramPollThread")
        self._thread.start()

    def stop(self):
        """安全停止通道"""
        self._is_running = False
        try:
            self.session.close()
        except Exception:
            pass
