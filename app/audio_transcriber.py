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

logger = logging.getLogger("butler.transcriber")


def transcribe_audio_with_gemini(audio_bytes: bytes) -> Tuple[Optional[str], Optional[str]]:
    """
    使用 Gemini 原生多模态音频接口将语音二进制流直接自动转写为文字文本。
    返回: (transcribed_text: Optional[str], error_message: Optional[str])
    """
    if not audio_bytes:
        return None, "音频数据为空"

    try:
        # 识别魔数获取真实 MIME 类型
        mime_type = "audio/ogg"
        if audio_bytes.startswith(b"RIFF") and len(audio_bytes) >= 12 and audio_bytes[8:12] == b"WAVE":
            mime_type = "audio/wav"
        elif audio_bytes.startswith(b"ID3") or audio_bytes.startswith(b"\xff\xfb") or audio_bytes.startswith(b"\xff\xf3"):
            mime_type = "audio/mp3"
        elif audio_bytes.startswith(b"fLaC"):
            mime_type = "audio/flac"

        audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")

        api_base = os.getenv("OPENAI_API_BASE", "https://generativelanguage.googleapis.com/v1beta/openai").rstrip("/")
        if api_base.endswith("/openai"):
            gemini_base = api_base[:-7]
        else:
            gemini_base = api_base

        api_key = os.getenv("OPENAI_API_KEY", "")
        model = os.getenv("OPENAI_MODEL") or os.getenv("AI_MODEL", "gemini-flash-lite-latest")

        url = f"{gemini_base}/models/{model}:generateContent?key={api_key}"
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

        resp = requests.post(url, json=payload, timeout=30)
        if resp.status_code != 200:
            logger.error(f"Gemini 语音识别接口失败 [code={resp.status_code}]: {resp.text[:150]}")
            return None, f"语音识别接口异常 (状态码 {resp.status_code})"

        res_json = resp.json()
        candidates = res_json.get("candidates", [])
        if not candidates:
            return None, "未解析到转录内容"

        parts = candidates[0].get("content", {}).get("parts", [])
        if not parts:
            return None, "转录结果为空"

        transcribed = parts[0].get("text", "").strip()
        return transcribed, None

    except Exception as e:
        logger.error(f"语音识别转写异常: {e}")
        return None, str(e)
