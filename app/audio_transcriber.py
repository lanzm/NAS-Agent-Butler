# -*- coding: utf-8 -*-
"""
audio_transcriber.py - 通用多模态语音转录服务 (基于 Gemini 原生音频接口)
可被飞书、Telegram 等所有前端聊天通道共享复用。
"""

import os
import base64
import logging
import requests
from typing import Tuple, Optional
from app.config import settings

logger = logging.getLogger("butler.transcriber")


def detect_audio_mime(audio_bytes: bytes) -> str:
    """根据文件头特征魔数嗅探真实音频 MIME 类型 (WAV/MP3/FLAC/MP4/AAC/OGG)"""
    if not audio_bytes:
        return "audio/ogg"
    if audio_bytes.startswith(b"RIFF") and len(audio_bytes) >= 12 and audio_bytes[8:12] == b"WAVE":
        return "audio/wav"
    if audio_bytes.startswith(b"ID3") or audio_bytes.startswith(b"\xff\xfb") or audio_bytes.startswith(b"\xff\xf3"):
        return "audio/mp3"
    if audio_bytes.startswith(b"fLaC"):
        return "audio/flac"
    if len(audio_bytes) >= 8 and audio_bytes[4:8] in [b"ftyp", b"M4A "]:
        return "audio/mp4"
    if audio_bytes.startswith(b"\xff\xf1") or audio_bytes.startswith(b"\xff\xf9"):
        return "audio/aac"
    if audio_bytes.startswith(b"OggS"):
        return "audio/ogg"
    return "audio/ogg"


def transcribe_audio_with_gemini(audio_bytes: bytes) -> Tuple[Optional[str], Optional[str]]:
    """
    使用 Gemini 原生多模态音频接口将语音二进制流直接自动转写为文字文本。
    返回: (transcribed_text: Optional[str], error_message: Optional[str])
    """
    if not audio_bytes:
        return None, "音频数据为空"

    try:
        mime_type = detect_audio_mime(audio_bytes)
        audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")

        raw_api_base = os.getenv("OPENAI_API_BASE", settings.openai_api_base) or "https://generativelanguage.googleapis.com/v1beta/openai"
        api_base = raw_api_base.rstrip("/")
        if api_base.endswith("/openai"):
            gemini_base = api_base[:-7]
        elif api_base.endswith("/v1"):
            gemini_base = api_base[:-3]
        else:
            gemini_base = api_base

        api_key = os.getenv("OPENAI_API_KEY", settings.openai_api_key)
        model = os.getenv("OPENAI_MODEL") or os.getenv("AI_MODEL", settings.openai_model) or "gemini-flash-lite-latest"

        # 安全防泄露：API Key 通过请求头传递，杜绝在 URL Query 中暴露明文凭据
        url = f"{gemini_base}/models/{model}:generateContent"
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
            "Authorization": f"Bearer {api_key}"
        }
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {
                            "text": "你是一个高精度的语音识别转写助手。请将这段语音转录为纯文本，准确记录说话内容。注意：只输出转录出的文字内容，严禁输出任何问候、说明或多余修饰。若完全为杂音或静音，请只回复[未能清晰识别语音]。"
                        },
                        {
                            "inline_data": {
                                "mime_type": mime_type,
                                "data": audio_b64
                            }
                        }
                    ]
                }
            ]
        }

        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        if resp.status_code != 200:
            try:
                err_json = resp.json()
                err_detail = err_json.get("error", {}).get("message") or err_json.get("message") or resp.text[:150]
            except Exception:
                err_detail = resp.text[:150]
            logger.warning(f"语音识别接口未成功 [code={resp.status_code}]: {err_detail}")
            return None, f"语音识别接口响应异常 [HTTP {resp.status_code}]：`{err_detail}`\n> 提示：当前配置的 AI 模型可能不支持音频多模态转写，建议直接在聊天框中发送文字交流。"

        res_json = resp.json()
        candidates = res_json.get("candidates", [])
        if not candidates:
            return None, "未能解析到有效转录内容，请靠近麦克风或重新录音。"

        parts = candidates[0].get("content", {}).get("parts", [])
        if not parts:
            return None, "转录结果为空，请重新录音。"

        transcribed = parts[0].get("text", "").strip()
        return transcribed, None

    except Exception as e:
        logger.warning(f"语音识别转写遇到异常: {e}")
        return None, "当前配置的 AI 模型暂不支持语音识别，请在聊天框中直接发送文字交流。"
