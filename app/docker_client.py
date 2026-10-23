# -*- coding: utf-8 -*-
"""
docker_client.py - Docker 客户端单例与连接复用管理
"""

import logging
from typing import Optional

try:
    import docker
except ImportError:
    docker = None

logger = logging.getLogger("butler.docker")

_cached_client = None


def get_docker_client() -> Optional[object]:
    """获取全局共享缓存的 DockerClient 实例（单例复用，失败时自动重试）"""
    global _cached_client
    if not docker:
        return None

    if _cached_client is not None:
        try:
            _cached_client.ping()
            return _cached_client
        except Exception:
            logger.debug("Docker Client 连接失效，尝试重新初始化...")
            _cached_client = None

    try:
        _cached_client = docker.from_env()
        return _cached_client
    except Exception as e:
        logger.debug(f"无法初始化 Docker 客户端: {e}")
        return None
