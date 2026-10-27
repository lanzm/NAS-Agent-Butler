# -*- coding: utf-8 -*-
"""
tests/test_constants.py - 测试全局交互状态规范与契约完整性
校验：
1. 状态文案长度严格 <= 6 个字符约束
2. TOOL_STATUS_MAP 100% 覆盖 TOOLS_REGISTRY，无缺失或未知工具
"""

import unittest
from app.constants import TaskStatus, TOOL_STATUS_MAP
from app.nas_mcp_server import TOOLS_REGISTRY
from app.card_builder import build_loading_card


class TestStatusContract(unittest.TestCase):
    """测试状态枚举字数规范与完整性契约"""

    def test_task_status_length_within_limit(self):
        """所有任务状态文案必须 <= 6 个字"""
        for status in TaskStatus:
            text = str(status.value)
            self.assertLessEqual(
                len(text),
                6,
                f"状态文案 [{text}] 长度为 {len(text)}，超过了 <= 6 字约束！"
            )

    def test_tool_status_map_length_within_limit(self):
        """所有工具状态文案必须 <= 6 个字"""
        for tool_name, status_text in TOOL_STATUS_MAP.items():
            self.assertLessEqual(
                len(status_text),
                6,
                f"工具 [{tool_name}] 状态文案 [{status_text}] 长度为 {len(status_text)}，超过了 <= 6 字约束！"
            )

    def test_tool_status_map_covers_all_mcp_tools(self):
        """TOOL_STATUS_MAP 必须 100% 覆盖 TOOLS_REGISTRY 中声明的所有工具"""
        registered_tool_names = {t["name"] for t in TOOLS_REGISTRY}
        mapped_tool_names = set(TOOL_STATUS_MAP.keys())

        # 确保注册的工具在映射表中均有定义
        missing = registered_tool_names - mapped_tool_names
        self.assertEqual(
            missing,
            set(),
            f"以下 MCP 工具缺少对应的状态文案映射: {missing}"
        )

    def test_loading_card_uses_cloud_model_status(self):
        """测试加载卡片正确渲染 '请求云端模型' 状态"""
        card = build_loading_card(TaskStatus.REQUEST_CLOUD_MODEL)
        elements = card.get("elements", [])
        self.assertTrue(len(elements) > 0)
        content = elements[0].get("text", {}).get("content", "")
        self.assertIn("请求云端模型", content)

    def test_loading_card_clean_format(self):
        """测试加载卡片极简纯净排版（无多余跑马灯）"""
        card = build_loading_card(TaskStatus.REQUEST_CLOUD_MODEL, elapsed=3.2)
        elements = card.get("elements", [])
        self.assertTrue(len(elements) > 0)
        content = elements[0].get("text", {}).get("content", "")
        self.assertIn("请求云端模型", content)
        self.assertIn("(3.2s)", content)
        self.assertNotIn("■", content)
        self.assertNotIn("□", content)


if __name__ == "__main__":
    unittest.main()
