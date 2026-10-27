# -*- coding: utf-8 -*-
"""
collector.py - NAS 宿主机硬件资源与 Docker 容器状态无感采集器
"""

import os
import time
import socket
import datetime
import psutil
from typing import Optional

from app.docker_client import get_docker_client
from app.utils import format_bytes, human_bytes, format_duration_chinese


def calc_container_uptime(started_at_str: str) -> str:
    """计算容器持续运行时间"""
    if not started_at_str or started_at_str.startswith("0001"):
        return "未启动"
    try:
        clean_str = started_at_str.split(".")[0].replace("Z", "")
        start_dt = datetime.datetime.fromisoformat(clean_str)
        now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
        diff = now - start_dt
        return format_duration_chinese(diff.total_seconds(), compact=True)
    except Exception:
        return "未知"


class SystemCollector:
    def __init__(self, disk_threshold=95, cpu_threshold=85, mem_threshold=90, temp_threshold=80):
        self.disk_threshold = int(disk_threshold)
        self.cpu_threshold = int(cpu_threshold)
        self.mem_threshold = int(mem_threshold)
        self.temp_threshold = int(temp_threshold)
        try:
            self.prev_net_io = psutil.net_io_counters()
        except Exception:
            self.prev_net_io = None
        self.prev_net_time = time.time()

    def get_uptime(self) -> str:
        """获取系统运行时间"""
        try:
            boot_time = psutil.boot_time()
            uptime_sec = int(time.time() - boot_time)
            return format_duration_chinese(uptime_sec)
        except Exception:
            return "未知"

    def get_cpu_temp(self):
        """跨平台采集 CPU 温度（支持 Linux /sys/class/thermal 与 psutil）"""
        for base in ["/host/sys/class/thermal", "/sys/class/thermal"]:
            if os.path.exists(base):
                for i in range(5):
                    tz = os.path.join(base, f"thermal_zone{i}", "temp")
                    if os.path.exists(tz):
                        try:
                            with open(tz, "r") as f:
                                t = int(f.read().strip())
                                if 0 < t < 120000:
                                    return t // 1000
                        except Exception:
                            pass
        try:
            if hasattr(psutil, "sensors_temperatures"):
                temps = psutil.sensors_temperatures()
                if temps:
                    for name, entries in temps.items():
                        for entry in entries:
                            if entry.current and entry.current > 0:
                                return int(entry.current)
        except Exception:
            pass
        return None

    def get_loadavg(self) -> str:
        """获取系统 1/5/15 分钟负载"""
        try:
            if hasattr(os, "getloadavg"):
                loads = os.getloadavg()
                return f"{loads[0]:.2f} / {loads[1]:.2f} / {loads[2]:.2f}"
        except Exception:
            pass
        return "N/A"

    def get_network_rates(self) -> dict:
        """获取网络实时上行/下行速率与累计吞吐"""
        try:
            curr_io = psutil.net_io_counters()
            curr_time = time.time()
            duration = max(curr_time - self.prev_net_time, 0.1)

            if self.prev_net_io:
                rx_bytes = curr_io.bytes_recv - self.prev_net_io.bytes_recv
                tx_bytes = curr_io.bytes_sent - self.prev_net_io.bytes_sent
            else:
                rx_bytes = 0
                tx_bytes = 0

            rx_rate = human_bytes(rx_bytes / duration) + "/s"
            tx_rate = human_bytes(tx_bytes / duration) + "/s"

            total_rx = human_bytes(curr_io.bytes_recv)
            total_tx = human_bytes(curr_io.bytes_sent)

            self.prev_net_io = curr_io
            self.prev_net_time = curr_time

            return {
                "rx_rate": rx_rate,
                "tx_rate": tx_rate,
                "total_rx": total_rx,
                "total_tx": total_tx
            }
        except Exception:
            return {"rx_rate": "0B/s", "tx_rate": "0B/s", "total_rx": "0B", "total_tx": "0B"}

    def get_disk_info(self, disk_threshold: Optional[int] = None):
        """获取关键挂载路径的磁盘容量与使用率"""
        target_th = disk_threshold if disk_threshold is not None else self.disk_threshold
        disks = []
        alarms = []
        targets = [
            ("/", "系统盘 /"),
            ("/host/mnt/data", "数据盘 /mnt/data"),
            ("/mnt/data", "数据盘 /mnt/data")
        ]
        seen = set()

        for path, label in targets:
            if not os.path.exists(path):
                continue
            if label in seen:
                continue
            try:
                if hasattr(os, "statvfs"):
                    st = os.statvfs(path)
                    total = st.f_blocks * st.f_frsize
                    free = st.f_bavail * st.f_frsize
                    used = total - free
                    pct = int((used / total) * 100) if total > 0 else 0
                else:
                    u = psutil.disk_usage(path)
                    total = u.total
                    free = u.free
                    used = u.used
                    pct = int(u.percent)
                seen.add(label)

                disks.append({
                    "mount": label,
                    "total": human_bytes(total),
                    "used": human_bytes(used),
                    "free": human_bytes(free),
                    "percent": pct
                })

                if pct >= target_th:
                    alarms.append(f"磁盘 {label} 使用率达 {pct}% (阈值 {target_th}%)")
            except Exception:
                pass

        # 兜底：若没有任何挂载点，读取当前根路径
        if not disks:
            try:
                du = psutil.disk_usage("/")
                pct = int(du.percent)
                disks.append({
                    "mount": "系统盘 /",
                    "total": human_bytes(du.total),
                    "used": human_bytes(du.used),
                    "free": human_bytes(du.free),
                    "percent": pct
                })
                if pct >= target_th:
                    alarms.append(f"磁盘 系统盘 / 使用率达 {pct}% (阈值 {target_th}%)")
            except Exception:
                pass

        return disks, alarms

    def get_docker_containers(self):
        """查询 Docker 容器列表与健康状态"""
        containers = []
        alarms = []
        client = get_docker_client()
        if not client:
            return [{"name": "Docker模块未就绪", "status": "missing_lib", "is_running": False, "health": "unknown"}], []

        try:
            for c in client.containers.list(all=True):
                health = "unknown"
                state = c.attrs.get("State", {})
                if "Health" in state:
                    health = state["Health"].get("Status", "unknown")

                is_running = c.status == "running"

                if health == "unhealthy":
                    alarms.append(f"容器 {c.name} 状态异常 (unhealthy)")

                image_name = c.image.tags[0] if c.image.tags else c.image.short_id
                started_at = state.get("StartedAt", "")
                uptime = calc_container_uptime(started_at) if is_running else "已停止"
                containers.append({
                    "name": c.name,
                    "status": c.status,
                    "health": health,
                    "is_running": is_running,
                    "uptime": uptime,
                    "image": image_name
                })
        except Exception as e:
            containers.append({"name": "Docker无法连接", "status": str(e), "is_running": False, "health": "error"})
        return containers, alarms

    def collect(self, thresholds: Optional[dict] = None) -> dict:
        """综合采集系统所有指标并触发阈值检查 (支持动态传入 thresholds 覆盖默认值)"""
        th = thresholds or {}
        cpu_th = th.get("cpu", self.cpu_threshold)
        mem_th = th.get("memory", self.mem_threshold)
        disk_th = th.get("disk", self.disk_threshold)
        temp_th = th.get("cpu_temp", self.temp_threshold)

        alarms = []

        # 1. CPU
        try:
            cpu_usage = int(psutil.cpu_percent(interval=0.1))
            if cpu_usage > cpu_th:
                time.sleep(0.5)
                cpu_usage = int(psutil.cpu_percent(interval=0.2))
                if cpu_usage > cpu_th:
                    alarms.append(f"CPU 使用率持续偏高: {cpu_usage}% (阈值 {cpu_th}%)")
        except Exception:
            cpu_usage = 0

        cpu_temp = self.get_cpu_temp()
        if cpu_temp and cpu_temp > temp_th:
            alarms.append(f"CPU 温度过高: {cpu_temp}°C (阈值 {temp_th}°C)")

        loadavg = self.get_loadavg()

        # 2. 内存
        try:
            mem = psutil.virtual_memory()
            mem_usage = int(mem.percent)
            if mem_usage > mem_th:
                alarms.append(f"内存使用率偏高: {mem_usage}% (阈值 {mem_th}%)")
            mem_used_str = human_bytes(mem.used)
            mem_total_str = human_bytes(mem.total)
        except Exception:
            mem_usage = 0
            mem_used_str = "0B"
            mem_total_str = "0B"

        try:
            swap = psutil.swap_memory()
            swap_pct = int(swap.percent) if swap.total > 0 else 0
        except Exception:
            swap_pct = 0

        # 3. 磁盘
        disks, disk_alarms = self.get_disk_info(disk_threshold=disk_th)
        alarms.extend(disk_alarms)

        # 4. 网络
        net_info = self.get_network_rates()

        # 5. 容器
        containers, docker_alarms = self.get_docker_containers()
        alarms.extend(docker_alarms)

        # 6. 获取出网 IP
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                host_ip = s.getsockname()[0]
        except Exception:
            host_ip = "127.0.0.1"

        return {
            "hostname": socket.gethostname(),
            "host_ip": host_ip,
            "uptime": self.get_uptime(),
            "cpu_usage": cpu_usage,
            "cpu_temp": cpu_temp,
            "loadavg": loadavg,
            "mem_usage": mem_usage,
            "mem_used": mem_used_str,
            "mem_total": mem_total_str,
            "swap_usage": swap_pct,
            "disks": disks,
            "net": net_info,
            "containers": containers,
            "backups": {},
            "alarms": alarms,
            "is_alarm": len(alarms) > 0,
            "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
