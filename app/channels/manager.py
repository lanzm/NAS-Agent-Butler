# -*- coding: utf-8 -*-
"""
manager.py - 多 IM 通道统一管理器 (ChannelManager)
负责动态发现、按需激活多通道、生命周期治理以及跨平台统一广播消息与晨报。
"""

import logging
from typing import Dict, List, Optional, Any
from app.channels.base import BaseChannel

logger = logging.getLogger("butler.channels")


class ChannelManager:
    """多 IM 通道统一调度管理器"""

    def __init__(self):
        self._channels: Dict[str, BaseChannel] = {}

    def register(self, channel: BaseChannel):
        """注册一个通道实例"""
        self._channels[channel.name] = channel
        logger.info(f"已注册 IM 通道: [{channel.display_name}] (enabled={channel.is_enabled()})")

    def get_channel(self, name: str) -> Optional[BaseChannel]:
        """获取指定名称的通道实例"""
        return self._channels.get(name)

    def get_active_channels(self) -> List[BaseChannel]:
        """获取当前配置有效且已启用的所有通道"""
        return [c for c in self._channels.values() if c.is_enabled()]

    def start_all(self):
        """启动所有已启用的通道"""
        active = self.get_active_channels()
        if not active:
            logger.warning("未检测到任何已启用的 IM 通道，请检查 .env 配置凭据")
            return

        for ch in active:
            try:
                logger.info(f"正在启动通道服务: [{ch.display_name}]...")
                ch.start()
            except Exception as e:
                logger.error(f"启动通道 [{ch.display_name}] 异常: {e}")

    def stop_all(self):
        """停止所有已激活的通道"""
        for ch in self.get_active_channels():
            try:
                ch.stop()
            except Exception as e:
                logger.error(f"停止通道 [{ch.display_name}] 异常: {e}")

    def broadcast_message(self, content: str, title: Optional[str] = None, **kwargs) -> Dict[str, bool]:
        """向所有已启用的通道广播文本/通知消息"""
        results = {}
        for ch in self.get_active_channels():
            try:
                ok = ch.send_message(target_id=None, content=content, title=title, **kwargs)
                results[ch.name] = ok
            except Exception as e:
                logger.error(f"通道 [{ch.name}] 广播消息失败: {e}")
                results[ch.name] = False
        return results

    def broadcast_card(self, card_data: Any, **kwargs) -> Dict[str, bool]:
        """向所有已启用的通道广播富文本卡片/排版消息"""
        results = {}
        for ch in self.get_active_channels():
            try:
                ok = ch.send_card(target_id=None, card_data=card_data, **kwargs)
                results[ch.name] = ok
            except Exception as e:
                logger.error(f"通道 [{ch.name}] 广播卡片失败: {e}")
                results[ch.name] = False
        return results
