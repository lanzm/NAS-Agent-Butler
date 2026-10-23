# -*- coding: utf-8 -*-
"""
base.py - 多 IM 通道抽象基类
定义统一的通道生命周期（启动/停止）、状态检查与标准化消息发送接口。
"""

from abc import ABC, abstractmethod
from typing import Any, Optional, Dict


class BaseChannel(ABC):
    """
    IM 通道抽象基类。
    各具体渠道（飞书、Telegram、企业微信等）继承此类并实现抽象方法。
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """通道唯一英文标识符（例如 'feishu', 'telegram', 'wechat'）"""
        pass

    @property
    @abstractmethod
    def display_name(self) -> str:
        """通道人类可读中文名称（例如 '飞书 (Feishu)', 'Telegram'）"""
        pass

    @abstractmethod
    def is_enabled(self) -> bool:
        """根据环境变量与配置判断当前通道是否已启用且配置完整"""
        pass

    @abstractmethod
    def start(self):
        """
        启动通道监听与服务循环。
        可根据 SDK 机制在内部启动长连接（WebSocket / 长轮询）或阻塞事件循环。
        """
        pass

    @abstractmethod
    def stop(self):
        """停止通道监听并安全断开连接"""
        pass

    @abstractmethod
    def send_message(self, target_id: Optional[str], content: str, title: Optional[str] = None, **kwargs) -> bool:
        """
        向指定目标用户/会话主动发送普通文本或通知消息。
        :param target_id: 接收方用户 ID（若为空则使用通道默认配置的管理员 ID）
        :param content: 消息正文
        :param title: 消息标题（可选）
        :return: 是否发送成功
        """
        pass

    @abstractmethod
    def send_card(self, target_id: Optional[str], card_data: Any, **kwargs) -> bool:
        """
        向指定目标主动发送富文本卡片或高级排版消息。
        :param target_id: 接收方用户 ID（若为空则使用通道默认配置的管理员 ID）
        :param card_data: 卡片定义（各渠道可根据自己的原生格式解析或自动降级为 Markdown）
        :return: 是否发送成功
        """
        pass

    def send_file(self, target_id: Optional[str], file_path: str, **kwargs) -> bool:
        """
        向指定目标发送文件/图片（可选实现，默认不支持）
        :param target_id: 接收方用户 ID
        :param file_path: 本地文件路径
        :return: 是否发送成功
        """
        return False
