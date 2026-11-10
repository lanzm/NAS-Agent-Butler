.PHONY: help test doctor doctor-json run lint clean

help:
	@echo "NAS-Agent-Butler 常用开发与运维命令:"
	@echo "  make test         - 执行全量离线自动化单元测试"
	@echo "  make doctor       - 执行系统环境与依赖健康体检 (终端格式)"
	@echo "  make doctor-json  - 执行健康体检并输出 JSON (便于容器监控探针读取)"
	@echo "  make run          - 启动管家常驻守护进程"
	@echo "  make lint         - 快速检查 Python 代码语法编译"
	@echo "  make clean        - 清理 __pycache__ 与临时构建缓存"

test:
	python -m unittest discover tests

doctor:
	python -m app.doctor

doctor-json:
	python -m app.doctor --json

run:
	python -u app/main.py

lint:
	python -m compileall app/ tests/

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
