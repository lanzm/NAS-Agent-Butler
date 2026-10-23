# -*- coding: utf-8 -*-
"""
channel.py - 飞书通道实现 (FeishuChannel)
实现基于官方 WebSocket 长连接的双向交互、多模态消息处理、状态动画与交互卡片无感刷新。
"""

import os
import json
import time
import base64
import logging
import threading
from typing import Optional, Any, Tuple

import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    P2ImMessageReceiveV1,
    CreateMessageRequest,
    CreateMessageRequestBody,
    ReplyMessageRequest,
    ReplyMessageRequestBody,
    PatchMessageRequest,
    PatchMessageRequestBody,
    GetMessageResourceRequest
)
from lark_oapi.event.callback.model.p2_card_action_trigger import (
    P2CardActionTrigger,
    P2CardActionTriggerResponse
)

from app.channels.base import BaseChannel
from app.action_handler import ActionHandler
from app.card_builder import (
    build_status_card,
    build_loading_card,
    build_ai_response_card,
    build_message_card,
    format_feishu_markdown
)
from app.audio_transcriber import transcribe_audio_with_gemini

try:
    from app.config import settings
except ImportError:
    from config import settings

logger = logging.getLogger("butler.feishu")


class FeishuChannel(BaseChannel):
    """飞书 (Lark) 接入通道"""

    def __init__(self, action_handler: ActionHandler):
        self.action_handler = action_handler
        self.app_id = settings.feishu_app_id
        self.app_secret = settings.feishu_app_secret
        self.receive_id = settings.feishu_receive_id
        self.receive_id_type = settings.feishu_receive_id_type

        self.api_client: Optional[lark.Client] = None
        self.ws_client: Optional[lark.ws.Client] = None
        self._is_running = False
        self._thread: Optional[threading.Thread] = None

        # 消息去重缓存与锁 (防飞书超时重发机制导致双重回复)
        self.processed_messages = {}
        self.processed_lock = threading.Lock()

        if self.is_enabled():
            self.api_client = (
                lark.Client.builder()
                .app_id(self.app_id)
                .app_secret(self.app_secret)
                .build()
            )

    @property
    def name(self) -> str:
        return "feishu"

    @property
    def display_name(self) -> str:
        return "飞书 (Feishu)"

    def is_enabled(self) -> bool:
        return bool(self.app_id and self.app_secret and not self.app_id.startswith("cli_your"))

    def send_message(self, target_id: Optional[str], content: str, title: Optional[str] = None, **kwargs) -> bool:
        """主动发送富文本卡片消息（若有标题）或纯文本消息"""
        if title:
            card = build_message_card(title=title, content=content, template=kwargs.get("template", "blue"))
            return self.send_card(target_id, card)

        if not self.api_client:
            return False
        rec_id = target_id or self.receive_id
        if not rec_id:
            return False

        try:
            req = (
                CreateMessageRequest.builder()
                .receive_id_type(self.receive_id_type)
                .request_body(
                    CreateMessageRequestBody.builder()
                    .receive_id(rec_id)
                    .msg_type("text")
                    .content(json.dumps({"text": content}))
                    .build()
                )
                .build()
            )
            resp = self.api_client.im.v1.message.create(req)
            return resp.success()
        except Exception as e:
            logger.error(f"发送纯文本消息失败: {e}")
            return False

    def send_card(self, target_id: Optional[str], card_data: Any, **kwargs) -> bool:
        """主动向指定用户或管理员推送飞书卡片"""
        if not self.api_client:
            logger.error("无法发送卡片: api_client 未初始化")
            return False

        rec_id = target_id or self.receive_id
        rec_type = kwargs.get("receive_id_type") or self.receive_id_type
        if not rec_id:
            logger.warning("未配置 FEISHU_RECEIVE_ID，跳过主动推送")
            return False

        try:
            req = (
                CreateMessageRequest.builder()
                .receive_id_type(rec_type)
                .request_body(
                    CreateMessageRequestBody.builder()
                    .receive_id(rec_id)
                    .msg_type("interactive")
                    .content(json.dumps(card_data) if isinstance(card_data, dict) else str(card_data))
                    .build()
                )
                .build()
            )
            resp = self.api_client.im.v1.message.create(req)
            if not resp.success():
                logger.error(f"发送卡片失败: code={resp.code}, msg={resp.msg}")
                return False
            logger.info(f"卡片发送成功 -> {rec_id}")
            return True
        except Exception as e:
            logger.error(f"发送卡片异常: {e}")
            return False

    def reply_text(self, message_id: str, text: str):
        """被动回复纯文本消息"""
        if not self.api_client:
            return
        try:
            req = (
                ReplyMessageRequest.builder()
                .message_id(message_id)
                .request_body(
                    ReplyMessageRequestBody.builder()
                    .content(json.dumps({"text": text}))
                    .msg_type("text")
                    .build()
                )
                .build()
            )
            self.api_client.im.v1.message.reply(req)
        except Exception as e:
            logger.error(f"回复消息异常: {e}")

    def reply_card(self, message_id: str, card_dict: dict) -> str:
        """回复卡片，成功时返回新卡片的消息 ID，便于后续原地无感更新"""
        if not self.api_client:
            return ""
        try:
            req = (
                ReplyMessageRequest.builder()
                .message_id(message_id)
                .request_body(
                    ReplyMessageRequestBody.builder()
                    .content(json.dumps(card_dict))
                    .msg_type("interactive")
                    .build()
                )
                .build()
            )
            resp = self.api_client.im.v1.message.reply(req)
            if not resp.success():
                logger.error(f"回复卡片失败: code={resp.code}, msg={resp.msg}")
                return ""
            return resp.data.message_id if resp.data else ""
        except Exception as e:
            logger.error(f"回复卡片异常: {e}")
            return ""

    def patch_card(self, message_id: str, card_dict: dict) -> bool:
        """在飞书中原地更新已有卡片的内容 (实现思考中->结论卡片原地更新体验)"""
        if not self.api_client or not message_id:
            return False
        try:
            req = (
                PatchMessageRequest.builder()
                .message_id(message_id)
                .request_body(
                    PatchMessageRequestBody.builder()
                    .content(json.dumps(card_dict))
                    .build()
                )
                .build()
            )
            resp = self.api_client.im.v1.message.patch(req)
            if resp.success():
                return True
            logger.warning(f"更新卡片未成功 [code={resp.code}, msg={resp.msg}]，将回退发送新卡片")
            return False
        except Exception as e:
            logger.warning(f"更新卡片异常: {e}，将回退发送新卡片")
            return False

    def download_file_bytes(self, msg_id: str, file_key: str, resource_type: str = "file") -> Tuple[Optional[bytes], Optional[str]]:
        """通过飞书 OpenAPI 下载消息中的资源二进制流"""
        if not self.api_client:
            return None, "飞书客户端未就绪"
        try:
            req = (
                GetMessageResourceRequest.builder()
                .message_id(msg_id)
                .file_key(file_key)
                .type(resource_type)
                .build()
            )
            resp = self.api_client.im.v1.message_resource.get(req)
            if not resp.success():
                err_msg = f"下载飞书资源文件失败 [code={resp.code}, msg={resp.msg}]"
                logger.error(err_msg)
                if resp.code in [99991663, 99991664, 400, 403]:
                    return None, f"⚠️ 获取资源权限不足（错误码 {resp.code}），请在飞书开放平台为应用开启「获取与下载消息中的资源文件 (im:resource)」权限并发布版本后重试。"
                return None, f"⚠️ 下载资源失败 (错误码 {resp.code}): {resp.msg}"

            file_obj = resp.file
            data_bytes = file_obj.read() if hasattr(file_obj, "read") else file_obj
            if not data_bytes:
                return None, "⚠️ 读取到的资源内容为空"

            # 安全防护：资源文件最大限制 15MB，防止内存占满溢出
            if len(data_bytes) > 15 * 1024 * 1024:
                return None, f"⚠️ 资源文件过大 ({len(data_bytes) / 1024 / 1024:.1f}MB)，超过系统 15MB 上限"

            return data_bytes, None
        except Exception as e:
            logger.error(f"下载资源文件异常: {e}")
            return None, f"⚠️ 下载资源异常: {str(e)}"

    def download_image_as_base64(self, msg_id: str, image_key: str) -> Tuple[Optional[str], Optional[str]]:
        """下载消息图片并转换为 Base64 Data URI"""
        image_bytes, err = self.download_file_bytes(msg_id, image_key, resource_type="image")
        if not image_bytes:
            return None, err

        # 安全防护：限制图片最大 10MB
        if len(image_bytes) > 10 * 1024 * 1024:
            return None, f"⚠️ 图片体积过大 ({len(image_bytes) / 1024 / 1024:.1f}MB)，超过 10MB 处理限制"

        mime_type = "image/jpeg"
        if image_bytes.startswith(b"\x89PNG"):
            mime_type = "image/png"
        elif image_bytes.startswith(b"GIF8"):
            mime_type = "image/gif"
        elif image_bytes.startswith(b"RIFF") and len(image_bytes) >= 12 and image_bytes[8:12] == b"WEBP":
            mime_type = "image/webp"

        b64_str = base64.b64encode(image_bytes).decode("utf-8")
        return f"data:{mime_type};base64,{b64_str}", None

    def _animate_loading(self, placeholder_msg_id: str, stop_event: threading.Event, status_holder: list, poke_event: threading.Event):
        """后台状态跳点与计时线程（智能降频防飞书 API 频控）"""
        start_time = time.time()
        dot_cycle = [".", "..", "..."]
        dot_idx = 0

        while not stop_event.is_set():
            # 阶段状态变化立即唤醒处理；默认等待 2.5 秒再刷新秒数跳点，减少 60% 冗余卡片 Patch 请求
            poke_event.wait(2.5)
            poke_event.clear()
            if stop_event.is_set():
                break

            elapsed = time.time() - start_time
            current_text = status_holder[0] if status_holder else "思考中"
            dot = dot_cycle[dot_idx % len(dot_cycle)]
            dot_idx += 1

            try:
                card = build_loading_card(current_text, spinner=dot, elapsed=elapsed)
                self.patch_card(placeholder_msg_id, card)
            except Exception as e:
                logger.debug(f"状态更新跳过: {e}")
                break

    def _run_with_loading_lifecycle(self, msg_id: str, initial_status: str, task_fn):
        """统一管理飞书状态交互卡片生命周期：占位动画、状态流转、结果 Patch 更新与异常兜底"""
        anim_stop_event = threading.Event()
        anim_poke_event = threading.Event()
        anim_thread = None
        placeholder_msg_id = ""
        status_holder = [initial_status]

        def on_status_change(new_status: str):
            if new_status and status_holder:
                if status_holder[0] != new_status:
                    status_holder[0] = new_status
                    anim_poke_event.set()

        def set_status(new_status: str):
            on_status_change(new_status)

        try:
            initial_loading_card = build_loading_card(stage_text=status_holder[0])
            placeholder_msg_id = self.reply_card(msg_id, initial_loading_card)

            if placeholder_msg_id:
                anim_thread = threading.Thread(
                    target=self._animate_loading,
                    args=(placeholder_msg_id, anim_stop_event, status_holder, anim_poke_event),
                    daemon=True
                )
                anim_thread.start()

            card_to_show = task_fn(on_status_change, set_status)

            anim_stop_event.set()
            anim_poke_event.set()
            if anim_thread:
                anim_thread.join(timeout=0.6)

            if card_to_show:
                updated = False
                if placeholder_msg_id:
                    updated = self.patch_card(placeholder_msg_id, card_to_show)
                if not updated:
                    self.reply_card(msg_id, card_to_show)

        except Exception as e:
            anim_stop_event.set()
            anim_poke_event.set()
            if anim_thread:
                anim_thread.join(timeout=0.6)
            logger.error(f"处理交互消息异常: {e}")
            err_card = build_message_card("❌ 处理异常", f"处理消息时发生异常: {str(e)}", template="red")
            if placeholder_msg_id:
                if not self.patch_card(placeholder_msg_id, err_card):
                    self.reply_card(msg_id, err_card)
            else:
                self.reply_card(msg_id, err_card)

    def _process_message_async(self, msg_id: str, raw_text: str, image_url: Optional[str] = None):
        """异步处理文本/图片指令"""
        initial_status = "分析图片中" if image_url else "思考中"

        def _handle(on_status_change, set_status):
            res_type, res_data = self.action_handler.handle_text_command(
                raw_text,
                image_url=image_url,
                status_callback=on_status_change
            )
            if res_type == "CARD":
                return res_data
            return build_message_card("🤖 NAS 智能管家", str(res_data))

        self._run_with_loading_lifecycle(msg_id, initial_status, _handle)

    def _process_image_message_async(self, msg_id: str, image_key: str, user_text: str = ""):
        """异步处理图片消息"""
        data_uri, err = self.download_image_as_base64(msg_id, image_key)
        if not data_uri:
            err_card = build_message_card("🖼️ 图片读取受限", err or "无法获取图片内容，请重试。", template="orange")
            self.reply_card(msg_id, err_card)
            return

        self._process_message_async(msg_id, user_text, image_url=data_uri)

    def _process_audio_message_async(self, msg_id: str, file_key: str):
        """异步处理语音留言"""
        def _handle(on_status_change, set_status):
            audio_bytes, dl_err = self.download_file_bytes(msg_id, file_key, resource_type="file")
            if not audio_bytes:
                return build_message_card("🎤 语音读取受限", dl_err or "未能获取音频内容，请重试。", template="orange")

            set_status("识别语音中")
            transcribed_text, asr_err = transcribe_audio_with_gemini(audio_bytes)
            if not transcribed_text or transcribed_text == "[未能清晰识别语音]":
                card_title = "🎤 语音识别接口异常" if asr_err else "🎤 语音未能识别"
                card_content = asr_err or "未能清晰识别到有效语音内容，请靠近麦克风或打字输入。"
                return build_message_card(card_title, card_content, template="orange")

            logger.info(f"语音识别结果: '{transcribed_text}'")
            set_status("思考中")

            res_type, res_data = self.action_handler.handle_text_command(
                transcribed_text,
                status_callback=on_status_change
            )

            voice_prefix = format_feishu_markdown(f"🎤 *听取语音：“{transcribed_text}”*") + "\n\n"
            if res_type == "CARD":
                try:
                    elements = res_data.get("elements", [])
                    if elements and elements[0].get("tag") == "markdown":
                        elements[0]["content"] = voice_prefix + elements[0]["content"].lstrip("\n")
                except Exception:
                    pass
                return res_data
            else:
                final_content = voice_prefix + str(res_data).lstrip("\n")
                return build_message_card("🤖 NAS 家庭智能管家", final_content)

        self._run_with_loading_lifecycle(msg_id, "正在收听语音", _handle)

    def _extract_post_content(self, content_dict: dict) -> Tuple[str, str]:
        """从富文本消息中提取文本与首张图片"""
        texts = []
        image_key = ""
        target_data = content_dict
        for lang in ["zh_cn", "en_us", "ja_jp"]:
            if lang in content_dict and isinstance(content_dict[lang], dict):
                target_data = content_dict[lang]
                break

        title = target_data.get("title", "")
        if title:
            texts.append(title)

        paragraphs = target_data.get("content", [])
        if isinstance(paragraphs, list):
            for para in paragraphs:
                if isinstance(para, list):
                    for elem in para:
                        if isinstance(elem, dict):
                            tag = elem.get("tag")
                            if tag == "text":
                                t = elem.get("text", "").strip()
                                if t and "@_user_" not in t:
                                    texts.append(t)
                            elif tag == "img" and not image_key:
                                image_key = elem.get("image_key", "")
        return " ".join(texts).strip(), image_key

    def _on_message_received(self, data: P2ImMessageReceiveV1):
        """飞书消息接收事件主回调"""
        try:
            msg = data.event.message
            msg_id = msg.message_id
            sender = data.event.sender
            sender_id = sender.sender_id.open_id if sender.sender_id else ""

            now = time.time()
            with self.processed_lock:
                # 内存保护与容量淘汰：超过 1000 条时先清理过期记录，再按 FIFO 淘汰最老数据，彻底杜绝内存泄漏
                if len(self.processed_messages) > 1000:
                    for old_id, ts in list(self.processed_messages.items()):
                        if now - ts > 300:
                            self.processed_messages.pop(old_id, None)
                    if len(self.processed_messages) > 1000:
                        for old_id in list(self.processed_messages.keys())[:300]:
                            self.processed_messages.pop(old_id, None)
                else:
                    for old_id, ts in list(self.processed_messages.items()):
                        if now - ts > 600:
                            self.processed_messages.pop(old_id, None)

                if msg_id in self.processed_messages:
                    logger.info(f"忽略重复推送的消息: msg_id={msg_id}")
                    return
                self.processed_messages[msg_id] = now

            logger.info(f"收到来自用户 [{sender_id}] 的消息 (msg_id={msg_id}, type={msg.message_type})")

            if not self.receive_id and sender_id:
                self.receive_id = sender_id
                logger.info(f"已自动绑定当前用户的 open_id: {self.receive_id}")

            if msg.message_type == "text":
                content_dict = json.loads(msg.content)
                raw_text = content_dict.get("text", "").strip()
                if "@_user_" in raw_text:
                    raw_text = raw_text.split(" ", 1)[-1].strip() if " " in raw_text else raw_text
                logger.info(f"用户指令文本: {raw_text}")

                threading.Thread(
                    target=self._process_message_async,
                    args=(msg_id, raw_text, None),
                    daemon=True
                ).start()

            elif msg.message_type == "image":
                content_dict = json.loads(msg.content)
                image_key = content_dict.get("image_key", "").strip()
                logger.info(f"收到用户图片消息: image_key={image_key}")
                if image_key:
                    threading.Thread(
                        target=self._process_image_message_async,
                        args=(msg_id, image_key, ""),
                        daemon=True
                    ).start()

            elif msg.message_type == "audio":
                content_dict = json.loads(msg.content)
                file_key = content_dict.get("file_key", "").strip()
                logger.info(f"收到用户语音消息: file_key={file_key}")
                if file_key:
                    threading.Thread(
                        target=self._process_audio_message_async,
                        args=(msg_id, file_key),
                        daemon=True
                    ).start()

            elif msg.message_type == "post":
                content_dict = json.loads(msg.content)
                raw_text, image_key = self._extract_post_content(content_dict)
                logger.info(f"收到用户富文本消息: text='{raw_text[:40]}', image_key={image_key}")
                if image_key:
                    threading.Thread(
                        target=self._process_image_message_async,
                        args=(msg_id, image_key, raw_text),
                        daemon=True
                    ).start()
                elif raw_text:
                    threading.Thread(
                        target=self._process_message_async,
                        args=(msg_id, raw_text, None),
                        daemon=True
                    ).start()

        except Exception as e:
            logger.error(f"处理用户消息入口失败: {e}")

    def _on_card_action(self, data: P2CardActionTrigger) -> P2CardActionTriggerResponse:
        """响应卡片按钮动作回调"""
        try:
            action_val = data.event.action.value
            logger.info(f"收到卡片按钮动作: {action_val}")
            res_dict = self.action_handler.handle_card_action(action_val)
            return P2CardActionTriggerResponse(d=res_dict)
        except Exception as e:
            logger.error(f"处理卡片动作失败: {e}")
            return P2CardActionTriggerResponse(d={"toast": {"type": "error", "content": f"执行失败: {str(e)}"}})

    def start(self):
        """启动飞书 WebSocket 长连接"""
        if not self.is_enabled():
            logger.warning("未配置有效的 FEISHU_APP_ID / FEISHU_APP_SECRET，飞书通道跳过启动")
            return

        self._is_running = True

        event_dispatcher = (
            lark.EventDispatcherHandler.builder("", "")
            .register_p2_im_message_receive_v1(self._on_message_received)
            .register_p2_card_action_trigger(self._on_card_action)
            .build()
        )

        logger.info("正在建立飞书开放平台 WebSocket 长连接...")
        self.ws_client = lark.ws.Client(
            app_id=self.app_id,
            app_secret=self.app_secret,
            event_handler=event_dispatcher,
            log_level=lark.LogLevel.INFO
        )

        def _ws_loop():
            while self._is_running:
                try:
                    self.ws_client.start()
                except Exception as e:
                    if not self._is_running:
                        break
                    logger.error(f"飞书 WebSocket 长连接断开: {e}，10秒后重连...")
                    time.sleep(10)

        self._thread = threading.Thread(target=_ws_loop, daemon=True, name="FeishuWSThread")
        self._thread.start()

    def stop(self):
        """停止飞书长连接"""
        self._is_running = False
        logger.info("正在停止飞书通道...")
