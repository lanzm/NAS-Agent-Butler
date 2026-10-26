# -*- coding: utf-8 -*-
"""
test_scheduler.py - YAML 任务加载、调度分发与告警生命周期单元测试
"""

import os
import unittest
from unittest.mock import patch, MagicMock
from app.main import (
    load_scheduled_tasks,
    run_health_check_task
)
import app.main as main_module


class TestScheduler(unittest.TestCase):

    def test_load_scheduled_tasks_from_yaml(self):
        """测试从 config/schedules.yaml 正确加载任务与属性解析"""
        tasks = load_scheduled_tasks()
        self.assertIsInstance(tasks, list)
        self.assertGreaterEqual(len(tasks), 2)

        # 1. 验证每日晨报任务
        daily_task = next((t for t in tasks if "晨报" in t.get("name", "")), None)
        self.assertIsNotNone(daily_task)
        self.assertEqual(daily_task.get("time"), "08:00")
        self.assertTrue(daily_task.get("enabled"))
        self.assertIn("今日生活简报", daily_task.get("prompt", ""))

        # 2. 验证周期巡检任务
        health_task = next((t for t in tasks if "巡检" in t.get("name", "")), None)
        self.assertIsNotNone(health_task)
        self.assertEqual(health_task.get("interval_minutes"), 5)
        self.assertTrue(health_task.get("notify_on_recovery"))
        self.assertIn("thresholds", health_task)
        self.assertEqual(health_task["thresholds"].get("cpu"), 85)

    def test_load_scheduled_tasks_with_custom_daily_report_time(self):
        """测试用户配置自定义 DAILY_REPORT_TIME 时动态覆盖晨报时间"""
        with patch("app.main.DAILY_REPORT_TIME", "07:30"):
            tasks = load_scheduled_tasks()
            daily_task = next((t for t in tasks if "晨报" in t.get("name", "")), None)
            self.assertIsNotNone(daily_task)
            self.assertEqual(daily_task.get("time"), "07:30")

    @patch("app.main.channel_manager.broadcast_card")
    @patch("app.main.collector.collect")
    def test_health_check_lifecycle_alarm_and_recovery(self, mock_collect, mock_broadcast):
        """测试健康巡检的告警与恢复闭环生命周期"""
        main_module.prev_alarm_state = False
        main_module.last_alarm_time = 0

        health_task = {
            "name": "🔍 测试巡检",
            "interval_minutes": 5,
            "enabled": True,
            "notify_on_recovery": True,
            "thresholds": {"cpu": 80}
        }

        # 步骤 1: 系统正常 (is_alarm=False) -> 静默，不发卡片
        mock_collect.return_value = {"is_alarm": False, "alarms": []}
        run_health_check_task(health_task)
        mock_broadcast.assert_not_called()
        self.assertFalse(main_module.prev_alarm_state)

        # 步骤 2: 发生异常 (is_alarm=True) -> 触发告警广播，标头为红色
        mock_collect.return_value = {
            "is_alarm": True,
            "alarms": ["CPU 使用率持续偏高: 92% (阈值 80%)"],
            "hostname": "test-nas",
            "host_ip": "192.168.1.100",
            "uptime": "1天",
            "timestamp": "2026-10-16 12:00:00",
            "cpu_usage": 92.0,
            "cpu_temp": 50,
            "loadavg": "1.0",
            "mem_usage": 40.0,
            "mem_used": "4GB",
            "mem_total": "16GB",
            "disks": [],
            "containers": []
        }
        run_health_check_task(health_task)
        self.assertEqual(mock_broadcast.call_count, 1)
        card = mock_broadcast.call_args[0][0]
        self.assertEqual(card["header"]["template"], "red")
        self.assertTrue(main_module.prev_alarm_state)

        # 步骤 3: 恢复正常 (is_alarm=False) -> 触发恢复通知广播，标头为绿色闭环
        mock_collect.return_value = {
            "is_alarm": False,
            "alarms": [],
            "hostname": "test-nas",
            "host_ip": "192.168.1.100",
            "uptime": "1天",
            "timestamp": "2026-10-16 12:05:00",
            "cpu_usage": 20.0,
            "cpu_temp": 45,
            "loadavg": "0.5",
            "mem_usage": 40.0,
            "mem_used": "4GB",
            "mem_total": "16GB",
            "disks": [],
            "containers": []
        }
        run_health_check_task(health_task)
        self.assertEqual(mock_broadcast.call_count, 2)
        recovery_card = mock_broadcast.call_args[0][0]
        self.assertEqual(recovery_card["header"]["template"], "green")
        self.assertIn("恢复正常", recovery_card["header"]["title"]["content"])
        self.assertFalse(main_module.prev_alarm_state)

    @patch("app.main.action_handler.agent.chat")
    @patch("app.main.channel_manager.broadcast_card")
    @patch("app.main.collector.collect")
    def test_health_check_with_ai_prompt_diagnosis(self, mock_collect, mock_broadcast, mock_ai_chat):
        """测试巡检任务配置 prompt 时，指标异常自动唤醒大模型进行诊断分析"""
        main_module.prev_alarm_state = False
        main_module.last_alarm_time = 0

        task_with_prompt = {
            "name": "🔍 智能诊断巡检",
            "interval_minutes": 5,
            "enabled": True,
            "thresholds": {"cpu": 80},
            "prompt": "请结合异常排查原因并给出处置建议"
        }

        mock_collect.return_value = {
            "is_alarm": True,
            "alarms": ["CPU 使用率持续偏高: 95% (阈值 80%)"],
            "hostname": "test-nas",
            "host_ip": "192.168.1.100",
            "uptime": "1天",
            "timestamp": "2026-10-16 12:00:00",
            "cpu_usage": 95.0,
            "cpu_temp": 50,
            "loadavg": "1.0",
            "mem_usage": 40.0,
            "mem_used": "4GB",
            "mem_total": "16GB",
            "disks": [],
            "containers": []
        }

        mock_ai_chat.return_value = {
            "text": "【AI 诊断分析】当前可能是 ffmpeg 转码占用 CPU，建议限流。",
            "trace_tag": "Trace: ai-diag-001"
        }

        run_health_check_task(task_with_prompt)

        # 验证 AI Agent chat 被调用，并且提示词中注入了异常信息
        mock_ai_chat.assert_called_once()
        called_prompt = mock_ai_chat.call_args[0][0]
        self.assertIn("请结合异常排查原因并给出处置建议", called_prompt)
        self.assertIn("CPU 使用率持续偏高", called_prompt)

        # 验证发送的卡片是红色标头的 AI 诊断卡片
        mock_broadcast.assert_called_once()
        card = mock_broadcast.call_args[0][0]
        self.assertEqual(card["header"]["template"], "red")
        self.assertIn("智能诊断巡检", card["header"]["title"]["content"])
        self.assertIn("ffmpeg 转码", str(card))


if __name__ == "__main__":
    unittest.main()
