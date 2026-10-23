# -*- coding: utf-8 -*-
"""
plugins - NAS 运维能力扩展插件包
提供 Fail2ban 防火墙拦截、Aria2 离线下载、PC 远程电源管理等可选插件。
"""

from app.plugins.base import BasePlugin
from app.plugins import firewall_plugin, aria2_plugin, pc_power_plugin

__all__ = ["BasePlugin", "firewall_plugin", "aria2_plugin", "pc_power_plugin"]
