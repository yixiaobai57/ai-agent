# 常用开发命令。Windows 若没有 make，可直接照抄下面的命令在 PowerShell 里执行。
# 说明：本仓库统一用 `python -m <tool>` 调用，避免 PATH 里混进另一个解释器。

PY ?= .venv/Scripts/python.exe
ifeq ($(OS),)
	PY = .venv/bin/python
endif

.PHONY: help install install-dev fmt lint type test cov e2e frontend-build frontend-lint build run docker-build docker-run clean

help:
	@echo "install        安装运行依赖"
	@echo "install-dev    安装运行 + 开发依赖"
	@echo "fmt            ruff 自动修复"
	@echo "lint           ruff 静态检查"
	@echo "type           mypy 类型检查"
	@echo "test           pytest 全量"
	@echo "cov            带覆盖率报告"
	@echo "e2e            端到端冒烟（需先 make run，Mock 模式）"
	@echo "frontend-build 构建前端到 frontend/dist"
	@echo "run            启动服务（单端口同时托管前端）"
	@echo "docker-build   构建镜像"
	@echo "docker-run     用 compose 起服务"

install:
	$(PY) -m pip install -r requirements.txt

install-dev:
	$(PY) -m pip install -r requirements-dev.txt

fmt:
	$(PY) -m ruff check . --fix
	$(PY) -m ruff format .

lint:
	$(PY) -m ruff check .

type:
	$(PY) -m mypy

test:
	$(PY) -m pytest

cov:
	$(PY) -m pytest --cov=. --cov-report=term-missing --cov-report=html

e2e:
	$(PY) scripts/e2e_smoke.py

frontend-build:
	cd frontend && npm ci && npm run build

frontend-lint:
	cd frontend && npm run lint

build: frontend-build

run:
	$(PY) main.py

docker-build:
	docker build -t ai-agent:v3 .

docker-run:
	docker compose up --build

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage data/*.db
