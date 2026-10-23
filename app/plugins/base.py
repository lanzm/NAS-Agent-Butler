# -*- coding: utf-8 -*-
"""
base.py - 运维扩展插件抽象基类
定义统一的插件契约（标识符、Tool Spec 描述、激活状态探测与执行入口）。
"""

from abc import ABC, abstractmethod
from typing import Dict, Any


class BasePlugin(ABC):
    """
    NAS 运维扩展插件抽象基类。
    所有扩展能力（安全防火墙、下载器管理、PC 电源调度等）均实现此接口，
    保证与 MCP 协议工具链（nas_mcp_server）标准对接。
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """插件及对应 MCP 工具的唯一标识名（如 'manage_firewall_security'）"""
        pass

    @property
    @abstractmethod
    def tool_spec(self) -> Dict[str, Any]:
        """符合 MCP / OpenAI 规范的工具元数据字典（包含 name, description, parameters）"""
        pass

    @abstractmethod
    def is_enabled(self) -> bool:
        """根据当前配置与环境状态判断插件是否已激活启用"""
        pass

    @abstractmethod
    def execute(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        封闭安全执行插件动作。
        :param args: 前端工具调用传入的参数字典
        :return: 包含 'status' ('success' 或 'error') 与详细信息的字典
        """
        pass
